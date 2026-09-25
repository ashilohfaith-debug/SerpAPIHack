"""Connected mode (Sarvam) with a fake HTTP layer — no network, no key needed:
request shapes, response parsing, error mapping, the voice adapters' fallbacks and
privacy guard, and validation of the chat model's suggested command."""

from __future__ import annotations

import base64
import io
import json
import urllib.error

import numpy as np
import pytest

from relay.connected.sarvam import SarvamClient, SarvamError, float_to_wav, wav_to_float


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return FakeResp(json.dumps(r).encode())


def _wav_b64(seconds=0.1, sr=22050):
    return base64.b64encode(float_to_wav(np.zeros(int(sr * seconds), dtype=np.float32),
                                         sr)).decode()


def test_wav_roundtrip():
    a = np.linspace(-0.5, 0.5, 1600).astype(np.float32)
    b, sr = wav_to_float(float_to_wav(a, 16000))
    assert sr == 16000 and np.allclose(a, b, atol=1e-3)


def test_stt_multipart_and_parse():
    op = FakeOpener([{"transcript": "open whatsapp", "language_code": "hi-IN"}])
    c = SarvamClient("k", opener=op)
    text, lang = c.stt(b"RIFFfake", mode="translate")
    assert (text, lang) == ("open whatsapp", "hi-IN")
    req = op.requests[0]
    assert req.full_url.endswith("/speech-to-text")
    assert req.get_header("Api-subscription-key") == "k"
    body = req.data.decode("latin-1")
    assert 'name="mode"' in body and "translate" in body and 'name="file"' in body
    assert "saaras:v3" in body


def test_tts_translate_chat():
    op = FakeOpener([
        {"audios": [_wav_b64()]},
        {"translated_text": "नमस्ते"},
        {"choices": [{"message": {"content": "<think>hmm</think>open whatsapp"}}]},
    ])
    c = SarvamClient("k", opener=op)
    audio, sr = c.tts("hello", "hi-IN")
    assert sr == 22050 and len(audio) > 0
    sent = json.loads(op.requests[0].data)
    assert sent["language_code"] == "hi-IN" and sent["model"].startswith("bulbul")
    assert c.translate("hello", target="hi-IN") == "नमस्ते"
    tr = json.loads(op.requests[1].data)
    assert tr["target_language_code"] == "hi-IN" and tr["source_language_code"] == "auto"
    assert c.chat([{"role": "user", "content": "x"}]) == "open whatsapp"


def test_errors_are_mapped_and_key_never_leaks():
    err = urllib.error.HTTPError("u", 403, "Forbidden", {},
                                 io.BytesIO(b'{"error": {"message": "invalid key"}}'))
    c = SarvamClient("secret-key", opener=FakeOpener([err, urllib.error.URLError("down")]))
    with pytest.raises(SarvamError) as e1:
        c.translate("hi", target="hi-IN")
    assert e1.value.status == 403 and "invalid key" in e1.value.message
    with pytest.raises(SarvamError) as e2:
        c.translate("hi", target="hi-IN")
    assert e2.value.offline
    assert "secret-key" not in repr(c) and "secret-key" not in str(e1.value)


class OfflineTTS:
    rate = 1.0

    def __init__(self):
        self.said = []

    def synth_to_array(self, text):
        self.said.append(text)
        return np.zeros(10, dtype=np.float32), 22050

    def set_rate(self, r):
        self.rate = r


class OfflineSTT:
    def transcribe(self, audio):
        return "offline words"


def test_connected_voice_translates_and_falls_back():
    from relay.connected import ConnectedVoice
    op = FakeOpener([{"translated_text": "नमस्ते"}, {"audios": [_wav_b64()]},
                     urllib.error.URLError("down")])
    warned = []
    cv = ConnectedVoice(SarvamClient("k", opener=op), OfflineSTT(), OfflineTTS(),
                        on_offline=warned.append)
    cv.output_language = "hi-IN"
    audio, sr = cv.synth_to_array("Hello")
    assert len(audio) > 0 and len(op.requests) == 2      # translated, then Bulbul
    cv.synth_to_array("Another line")                     # network down -> offline voice
    assert cv.offline_tts.said == ["Another line"] and warned


def test_connected_voice_never_sends_secrets():
    from relay.connected import ConnectedVoice
    op = FakeOpener([])
    cv = ConnectedVoice(SarvamClient("k", opener=op), OfflineSTT(), OfflineTTS())
    cv.synth_to_array("your password is hunter2")
    assert op.requests == [] and cv.offline_tts.said == ["your password is hunter2"]


def test_connected_stt_modes_language_and_fallback():
    from relay.connected import ConnectedVoice
    op = FakeOpener([{"transcript": "open notepad", "language_code": "te-IN"},
                     {"transcript": "నమస్కారం", "language_code": "te-IN"},
                     urllib.error.URLError("down")])
    cv = ConnectedVoice(SarvamClient("k", opener=op), OfflineSTT(), OfflineTTS())
    assert cv.transcribe(np.zeros(1600, dtype=np.float32)) == "open notepad"
    assert cv.last_input_language == "te-IN" and cv.speak_language == "te-IN"
    cv.native_dictation = True
    assert cv.transcribe(np.zeros(1600, dtype=np.float32)) == "నమస్కారం"
    assert b"transcribe" in op.requests[1].data
    assert cv.transcribe(np.zeros(1600, dtype=np.float32)) == "offline words"


@pytest.mark.parametrize("line,ok", [
    ("open whatsapp", True), ("Command: search the web for cricket score", True),
    ("UNKNOWN", False), ("confirm delete", False), ("quit relay", False),
    ("emergency stop", False), ("turn on connected mode", False), ("gibberish words", False),
    ("delete my notes", False),
])
def test_nlu_validation(line, ok):
    from relay.connected.nlu import validate
    assert (validate(line) is not None) == ok
