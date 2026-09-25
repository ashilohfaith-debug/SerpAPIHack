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

    def handle(self, text):
        self.handled.append(text)
        return []

    def say(self, text, *a, **k):
        self.said.append(text)


def _loop(session, wake_required):
    # pass a sentinel stt so VoiceLoop does not construct a real WhisperSTT
    return VoiceLoop(session, stt=object(), wake_required=wake_required)


def test_wake_required_ignores_unaddressed_speech():
    s = _FakeSession()
    _loop(s, True).on_transcript("open notepad and delete everything")
    assert s.handled == []                    # never acted without the wake word


def test_wake_required_dispatches_command_after_wake_word():
    s = _FakeSession()
    _loop(s, True).on_transcript("relay open notepad")
    assert s.handled == ["open notepad"]


def test_bare_wake_word_prompts_and_does_not_act():
    s = _FakeSession()
    _loop(s, True).on_transcript("relay")
    assert s.handled == []
    assert s.said and "?" in s.said[0]


def test_push_to_talk_dispatches_every_utterance():
    s = _FakeSession()
    _loop(s, False).on_transcript("open notepad")
    assert s.handled == ["open notepad"]


def test_empty_transcript_is_ignored():
    s = _FakeSession()
    _loop(s, False).on_transcript("   ")
    assert s.handled == []


def test_on_utterance_survives_stt_error():
    class BadSTT:
        def transcribe(self, audio):
            raise RuntimeError("decode blew up")

    s = _FakeSession()
    loop = VoiceLoop(s, stt=BadSTT(), wake_required=False)
    loop.on_utterance(b"\x00\x01" * 100)      # must not raise
    assert s.handled == []


def test_on_utterance_transcribes_and_dispatches():
    class FixedSTT:
        def transcribe(self, audio):
            return "open notepad"

    s = _FakeSession()
    loop = VoiceLoop(s, stt=FixedSTT(), wake_required=False)
    loop.on_utterance(b"\x00\x01" * 100)
    assert s.handled == ["open notepad"]
