"""P3 audio: wake/command parsing, VAD segmentation, speech-queue barge-in, and a
real offline TTS->STT round-trip. The round-trip loads real models (Piper + faster-
whisper) and is the P3 acceptance check; the rest are headless unit tests."""

import threading
import time

import numpy as np
import pytest


# ---- wake word + control commands (pure string logic) ----
def test_detect_wake_variants_and_command_split():
    from relay.audio.wake import detect_wake
    assert detect_wake("relay open notepad") == (True, "open notepad")
    assert detect_wake("hey relay, what's on my screen") == (True, "what's on my screen")
    assert detect_wake("relay") == (True, "")
    assert detect_wake("please open the file")[0] is False


def test_match_control_commands():
    from relay.audio.wake import Command, match_command
    assert match_command("stop") == Command.STOP_TALKING
    assert match_command("emergency stop") == Command.EMERGENCY_STOP
    assert match_command("cancel task") == Command.CANCEL_TASK
    assert match_command("pause") == Command.PAUSE
    assert match_command("continue please") == Command.CONTINUE
    assert match_command("open notepad") is None


# ---- VAD segmenter state machine (inject a scripted classifier) ----
def test_speech_segmenter_start_and_end():
    from relay.audio.vad import SpeechSegmenter

    class FakeVAD:
        def __init__(self, script):
            self.script = list(script)
        def is_speech(self, _frame):
            return self.script.pop(0)

    # 3 speech frames -> start ; then 20 silence -> end
    script = [True, True, True] + [True] * 5 + [False] * 20
    seg = SpeechSegmenter(start_frames=3, end_frames=20)
    seg.vad = FakeVAD(script)
    events = [seg.push(b"") for _ in range(len(script))]
    assert "start" in events
    assert "end" in events
    assert events.index("start") < events.index("end")


# ---- speech queue: barge-in stops current playback and clears the queue ----
def test_speech_queue_interrupt_is_barge_in():
    from relay.audio.speech import SpeechQueue

    class FakeTTS:
        def synth_to_array(self, text):
            return np.ones(16000, dtype=np.float32), 16000

    started = threading.Event()

    def fake_player(audio, sr, stop):
        started.set()
        stop.wait(3.0)  # a real player cuts off promptly when stop is set

    q = SpeechQueue(FakeTTS(), player=fake_player)
    try:
        q.say("a long sentence")
        q.say("queued second")
        assert started.wait(1.0)
        assert q.is_speaking
        t0 = time.perf_counter()
        q.interrupt()
        # worker should stop the current item quickly and drop the queued one
        for _ in range(100):
            if not q.is_speaking:
                break
            time.sleep(0.02)
        assert not q.is_speaking
        assert time.perf_counter() - t0 < 1.0
        assert q._q.qsize() == 0
    finally:
        q.shutdown()


def test_emergency_stop_flushes_speech():
    from relay.audio.speech import SpeechQueue
    from relay.core import EmergencyStop

    class FakeTTS:
        def synth_to_array(self, text):
            return np.ones(16000, dtype=np.float32), 16000

    es = EmergencyStop()
    q = SpeechQueue(FakeTTS(), player=lambda a, s, stop: stop.wait(3.0), emergency=es)
    try:
        q.say("hello")
        time.sleep(0.2)
        es.engage("test")  # registered flush == interrupt
        for _ in range(100):
            if not q.is_speaking:
                break
            time.sleep(0.02)
        assert not q.is_speaking
    finally:
        q.shutdown()


# ---- real offline round-trip (loads Piper + faster-whisper) ----
@pytest.mark.integration
def test_offline_tts_to_stt_roundtrip():
    from relay.audio import WhisperSTT, make_tts
    from relay.audio.wake import detect_wake

    # Scope: prove the offline TTS->STT pipeline preserves content. Piper synthesis
    # is slightly non-deterministic and tiny.en can mis-hear a single hard word, so
    # we assert word-overlap over common words rather than one brittle token.
    # (Wake-word matching is unit-tested on realistic transcripts separately.)
    phrase = "please open the file and read the text out loud"
    tts = make_tts(prefer_piper=True)
    audio, sr = tts.synth_to_array(phrase)
    assert len(audio) > 0
    if sr != 16000:
        n = int(len(audio) * 16000 / sr)
        audio = np.interp(np.linspace(0, len(audio), n, endpoint=False),
                          np.arange(len(audio)), audio).astype(np.float32)
    text = WhisperSTT().transcribe(audio).lower()
    want = set(phrase.split())
    heard = set(text.replace(".", "").replace(",", "").split())
    overlap = len(want & heard) / len(want)
    assert overlap >= 0.7, f"low STT overlap {overlap:.2f}: {text!r}"
    # detect_wake on a realistic transcript still splits the command cleanly
    assert detect_wake("relay " + text)[0] is True
