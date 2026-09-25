"""The live voice loop — ties the pieces into a running assistant.

Mic frames -> VAD segments -> STT -> wake-gated dispatch to the Session. RELAY only
acts on utterances addressed to it ("relay …") so it never triggers on ambient speech
or the user talking to someone else — the safe, transparent default. When RELAY is
speaking and the user starts talking, that's a barge-in: speech is interrupted.

The dispatch core (``on_transcript``) is pure and unit-tested with a fake STT; the
live ``run`` wires a real microphone.
"""

from __future__ import annotations

import threading

from relay.audio import SpeechSegmenter, WhisperSTT
from relay.audio.wake import detect_wake
from relay.diagnostics import get_logger

log = get_logger("loop")


class VoiceLoop:
    def __init__(self, session, stt=None, speech=None, wake_required: bool = True) -> None:
        self.session = session
        self.stt = stt or WhisperSTT()
        self.speech = speech            # SpeechQueue, for barge-in
        self.wake_required = wake_required
        self._mic = None

    def on_transcript(self, text: str) -> None:
        """Dispatch one recognised utterance. Wake-gated: only 'relay …' is acted on."""
        text = (text or "").strip()
        if not text:
            return
        if self.wake_required:
            woke, rest = detect_wake(text)
            if not woke:
                log.debug("ignored (no wake word): %r", text)
                return
            if rest.strip():
                self.session.handle(rest)
            else:
                self.session.say("Yes? What would you like to do?")
            return
        # push-to-talk mode: every utterance is a command
        self.session.handle(text)

    def on_utterance(self, pcm_bytes: bytes) -> None:
        import numpy as np
        if not pcm_bytes:
            return
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            text = self.stt.transcribe(audio)
        except Exception as e:  # a bad decode must not kill the loop
            log.warning("STT failed: %s", e)
            return
        self.on_transcript(text)

    def run(self):
        """Start listening on the default microphone. Returns the MicCapture (call
        .stop() to end). Non-blocking."""
        from relay.audio import MicCapture
        seg = SpeechSegmenter()
        buf = bytearray()

        def on_frame(frame: bytes) -> None:
            nonlocal buf
            ev = seg.push(frame)
            if ev == "start" and self.speech is not None and self.speech.is_speaking:
                self.speech.interrupt()          # barge-in
            if seg.in_speech or ev == "end":
                buf.extend(frame)
            if ev == "end":
                pcm = bytes(buf)
                buf = bytearray()
                threading.Thread(target=self.on_utterance, args=(pcm,), daemon=True).start()

        self._mic = MicCapture(on_frame)
        self._mic.start()
        return self._mic

    def stop(self) -> None:
        if self._mic is not None:
            self._mic.stop()
            self._mic = None
