"""Sarvam voice (Bulbul) and speech recognition (Saaras) from the .env file.

A local mock of the Sarvam API checks the real requests (auth header, JSON / multipart
bodies, base64 WAV answers). Also: the offline voice takes over on any failure, secrets
never leave the PC, and room conversation is never uploaded (wake word checked locally).
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from relay.sarvam import (
    SarvamClient,
    SarvamError,
    SarvamSTT,
    SarvamTTS,
    float_to_wav,
    settings,
    wav_to_float,
)

KEY = "sk_test_sarvam_123"


class MockSarvam(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    log = []                  # (path, port, headers, body bytes)
    status = 200

    def log_message(self, *a):
        pass

    def _send(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        MockSarvam.log.append((self.path, self.client_address[1], dict(self.headers), b""))
        self._send(200, {"ok": True})

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        MockSarvam.log.append((self.path, self.client_address[1], dict(self.headers), body))
        if self.headers.get("api-subscription-key") != KEY:
            return self._send(403, {"error": {"message": "Invalid API key"}})
        if MockSarvam.status != 200:
            return self._send(MockSarvam.status, {"error": {"message": "busy"}})
        if self.path == "/text-to-speech":
            req = json.loads(body)
            tone = 0.3 * np.sin(np.linspace(0, 200, 4410)).astype(np.float32)
            wav = float_to_wav(tone, 22050)
            return self._send(200, {"request_id": "r1", "audios": [
                base64.b64encode(wav).decode()], "echo": req})
        if self.path == "/speech-to-text":
            ok = b'name="mode"' in body and b"RIFF" in body and b'name="file"' in body
            return self._send(200, {"transcript": "What time is it?" if ok else "",
                                    "language_code": "hi-IN"})
        self._send(404, {"detail": "not found"})


@pytest.fixture(scope="module")
def base():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), MockSarvam)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def _reset():
    MockSarvam.log.clear()
    MockSarvam.status = 200


class OfflineTTS:
    rate = 1.0

    def __init__(self):
        self.said = []

    def synth_to_array(self, text):
        self.said.append(text)
        return np.zeros(160, dtype=np.float32), 16000

    def set_rate(self, r):
        self.rate = r


class OfflineSTT:
    def __init__(self, text="offline words"):
        self.text, self.calls = text, 0

    def transcribe(self, audio):
        self.calls += 1
        return self.text


# ---------------------------------------------------------------- client
def test_tts_request_and_audio(base):
    audio, sr = SarvamClient(KEY, base=base).tts("Hello there", "hi-IN", speaker="shubh",
                                                 pace=1.2)
    assert sr == 22050 and len(audio) == 4410 and audio.dtype == np.float32
    path, _port, headers, body = MockSarvam.log[-1]
    req = json.loads(body)
    assert path == "/text-to-speech" and headers["api-subscription-key"] == KEY
    assert req == {"text": "Hello there", "language_code": "hi-IN", "model": "bulbul:v3",
                   "pace": 1.2, "speaker": "shubh"}


def test_stt_sends_multipart_wav(base):
    text, lang = SarvamClient(KEY, base=base).stt(float_to_wav(np.zeros(1600)),
                                                  mode="translate")
    assert (text, lang) == ("What time is it?", "hi-IN")
    body = MockSarvam.log[-1][3]
    assert b"saaras:v3" in body and b"translate" in body


def test_one_connection_for_many_sentences(base):
    c = SarvamClient(KEY, base=base)
    c.warm()
    for s in ("one", "two", "three"):
        c.tts(s)
    assert len({port for _p, port, _h, _b in MockSarvam.log}) == 1


def test_bad_key_is_an_error_not_a_crash(base):
    with pytest.raises(SarvamError) as e:
        SarvamClient("wrong", base=base).tts("hi")
    assert e.value.status == 403 and "Invalid API key" in str(e.value)
    assert not e.value.offline


def test_no_network_is_an_offline_error():
    with pytest.raises(SarvamError) as e:
        SarvamClient(KEY, base="http://127.0.0.1:9", timeout=2).tts("hi")
    assert e.value.offline


def test_key_never_in_repr():
    assert KEY not in repr(SarvamClient(KEY))


def test_gateway_base_url_with_a_path(base):
    """SARVAM_BASE_URL can be the developer's own proxy (which adds the real key)."""
    class Prefixed(MockSarvam):
        def do_POST(self):
            assert self.path.startswith("/sarvam/")
            self.path = self.path[len("/sarvam"):]
            super().do_POST()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Prefixed)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/sarvam/"
        audio, sr = SarvamClient(KEY, base=url).tts("via gateway")
        assert sr == 22050 and len(audio)
    finally:
        srv.shutdown()


def test_wav_round_trip():
    x = (0.5 * np.sin(np.linspace(0, 50, 1600))).astype(np.float32)
    y, sr = wav_to_float(float_to_wav(x, 16000))
    assert sr == 16000 and np.max(np.abs(x - y)) < 1e-3


# ---------------------------------------------------------------- voice
def test_sarvam_voice_used_when_online(base):
    off = OfflineTTS()
    tts = SarvamTTS(SarvamClient(KEY, base=base), off)
    audio, sr = tts.synth_to_array("Good morning.")
    assert sr == 22050 and off.said == []


def test_falls_back_to_offline_voice_and_says_so_once(base):
    off, notes = OfflineTTS(), []
    tts = SarvamTTS(SarvamClient("wrong", base=base), off, on_fallback=notes.append)
    for s in ("one", "two", "three"):
        _audio, sr = tts.synth_to_array(s)
        assert sr == 16000
    assert off.said == ["one", "two", "three"] and len(notes) == 1
    assert "offline voice" in notes[0]


def test_offline_notice_when_network_is_down():
    notes = []
    tts = SarvamTTS(SarvamClient(KEY, base="http://127.0.0.1:9", timeout=2), OfflineTTS(),
                    on_fallback=notes.append)
    tts.synth_to_array("hello")
    assert notes == ["I can't reach the online voice right now, so I'm using my offline "
                     "voice."]


def test_secrets_are_spoken_offline_only(base):
    off = OfflineTTS()
    SarvamTTS(SarvamClient(KEY, base=base), off).synth_to_array("Your password is Hunter2!")
    assert MockSarvam.log == [] and off.said == ["Your password is Hunter2!"]


def test_speech_rate_reaches_both_voices(base):
    off = OfflineTTS()
    tts = SarvamTTS(SarvamClient(KEY, base=base), off)
    tts.set_rate(1.5)
    tts.synth_to_array("Faster now.")
    assert off.rate == 1.5 and json.loads(MockSarvam.log[-1][3])["pace"] == 1.5


def test_stt_falls_back_to_whisper(base):
    off = OfflineSTT()
    stt = SarvamSTT(SarvamClient("wrong", base=base), off)
    assert stt.transcribe(np.zeros(1600, dtype=np.float32)) == "offline words"
    ok = SarvamSTT(SarvamClient(KEY, base=base), OfflineSTT())
    assert ok.transcribe(np.zeros(1600, dtype=np.float32)) == "What time is it?"
    assert ok.last_language == "hi-IN"


def test_settings_from_environment(monkeypatch):
    monkeypatch.delenv("RELAY_OFFLINE")
    assert settings()["key"] == "" and settings()["stt"] is False
    assert settings()["base"] == "https://api.sarvam.ai"
    monkeypatch.setenv("SARVAM_API_KEY", " abc ")
    monkeypatch.setenv("SARVAM_STT", "on")
    monkeypatch.setenv("SARVAM_SPEAKER", "shubh")
    s = settings()
    assert s["key"] == "abc" and s["stt"] and s["speaker"] == "shubh"
    assert s["tts_model"] == "bulbul:v3" and s["language"] == "en-IN"


# ---------------------------------------------------------------- privacy gate
def _loud(seconds=1.0):
    n = int(16000 * seconds)
    return (8000 * np.sin(np.linspace(0, 900, n))).astype(np.int16).tobytes()


def _loop(local_text, dispatched):
    from relay.loop import VoiceLoop
    cloud = OfflineSTT("Relay, what time is it?")
    loop = VoiceLoop(dispatched.append, stt=cloud, wake_required=True, threaded=False)
    loop.wake_stt = OfflineSTT(local_text)
    return loop, cloud


def test_room_conversation_is_never_uploaded():
    for heard in ("so what are we having for dinner", "really nice weather today"):
        dispatched = []
        loop, cloud = _loop(heard, dispatched)
        loop.on_utterance(_loud())
        assert cloud.calls == 0 and dispatched == [], heard


def test_speech_addressed_to_relay_uses_the_online_recogniser():
    dispatched = []
    loop, cloud = _loop("relay what time is it", dispatched)
    loop.on_utterance(_loud())
    assert cloud.calls == 1 and dispatched == ["what time is it?"]


def test_near_miss_wake_word_with_a_real_command_is_accepted():
    dispatched = []
    loop, cloud = _loop("really, what time is it", dispatched)
    cloud.text = "Really, what time is it?"
    loop.on_utterance(_loud())
    assert cloud.calls == 1 and dispatched == ["what time is it?"]


def test_talk_key_speech_goes_straight_online():
    dispatched = []
    loop, cloud = _loop("", dispatched)
    loop.on_utterance(_loud(), prompted=True)
    assert cloud.calls == 1 and loop.wake_stt.calls == 0
