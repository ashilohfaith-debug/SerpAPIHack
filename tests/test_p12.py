"""P12 packaging/lifecycle units: single-instance lock, model status, wake-gated loop."""

from __future__ import annotations

from relay.core.single_instance import SingleInstance
from relay.loop import VoiceLoop


def test_single_instance_second_acquire_fails_then_succeeds_after_release():
    a, b = SingleInstance("p12test"), SingleInstance("p12test")
    try:
        assert a.acquire() is True
        assert b.acquire() is False          # locked by a
        a.release()
        assert b.acquire() is True           # free again
    finally:
        a.release()
        b.release()


def test_single_instance_context_manager():
    with SingleInstance("p12ctx") as guard:
        assert guard.acquired is True
        other = SingleInstance("p12ctx")
        assert other.acquire() is False
        other.release()


def test_models_status_shape_and_text():
    from relay import models_manager
    rows = models_manager.status()
    assert isinstance(rows, list) and rows
    for r in rows:
        assert {"name", "present", "how"} <= set(r)
        assert isinstance(r["present"], bool)
    txt = models_manager.status_text()
    assert "Managed models" in txt


class _FakeSession:
    def __init__(self):
        self.handled = []
        self.said = []
        self.earcons = []

    def handle(self, text):
        self.handled.append(text)
        return []

    def say(self, text, *a, **k):
        self.said.append(text)


def _loop(session, wake_required, stt=None):
    # a sentinel stt so VoiceLoop does not construct a real WhisperSTT
    return VoiceLoop(session.handle, stt=stt or object(), wake_required=wake_required,
                     say=session.say, play_earcon=session.earcons.append, threaded=False)


def test_wake_required_ignores_unaddressed_speech():
    s = _FakeSession()
    _loop(s, True).on_transcript("open notepad and delete everything")
    assert s.handled == []                    # never acted without the wake word


def test_wake_required_dispatches_command_after_wake_word():
    s = _FakeSession()
    _loop(s, True).on_transcript("relay open notepad")
    assert s.handled == ["open notepad"]


def test_bare_wake_word_arms_listening_and_does_not_act():
    s = _FakeSession()
    loop = _loop(s, True)
    loop.on_transcript("relay")
    assert s.handled == []
    assert "listen" in s.earcons and loop._armed      # chirps, then takes the next command


def test_wake_word_mid_sentence_is_not_a_command():
    s = _FakeSession()
    _loop(s, True).on_transcript("the relay race was great open notepad")
    assert s.handled == []


def test_prompted_speech_needs_no_wake_word():
    s = _FakeSession()
    _loop(s, False).on_transcript("open notepad", prompted=True)
    assert s.handled == ["open notepad"]


def test_prompted_speech_strips_a_spoken_wake_word():
    s = _FakeSession()
    _loop(s, False).on_transcript("Relay, open notepad", prompted=True)
    assert s.handled == ["open notepad"]


def test_wake_off_ignores_ambient_speech():
    s = _FakeSession()
    _loop(s, False).on_transcript("relay open notepad")   # not prompted, wake word off
    assert s.handled == []


def test_empty_transcript_is_ignored_and_prompted_empty_says_so():
    s = _FakeSession()
    _loop(s, False).on_transcript("   ")
    assert s.handled == [] and s.said == []
    _loop(s, False).on_transcript("", prompted=True)
    assert s.handled == [] and any("didn't catch" in t for t in s.said)


def test_on_utterance_survives_stt_error():
    class BadSTT:
        def transcribe(self, audio):
            raise RuntimeError("decode blew up")

    s = _FakeSession()
    loop = _loop(s, False, stt=BadSTT())
    loop.on_utterance(b"\x00\x01" * 100, prompted=True)      # must not raise
    assert s.handled == []
    assert any("couldn't process" in t for t in s.said)


def test_on_utterance_transcribes_and_dispatches_when_prompted():
    class FixedSTT:
        def transcribe(self, audio):
            return "open notepad"

    s = _FakeSession()
    loop = _loop(s, False, stt=FixedSTT())
    loop.on_utterance(b"\x00\x01" * 100, prompted=True)
    assert s.handled == ["open notepad"]


def test_near_miss_wake_word_only_with_a_real_command():
    s = _FakeSession()
    loop = VoiceLoop(s.handle, stt=object(), wake_required=True, say=s.say, threaded=False)
    loop.on_transcript("Really? How much battery do I have?")
    assert s.handled == ["How much battery do I have?"]
    loop.on_transcript("Really, that's great, thanks for telling me")
    assert s.handled == ["How much battery do I have?"]     # conversation: ignored
