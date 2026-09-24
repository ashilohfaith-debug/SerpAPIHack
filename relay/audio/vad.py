"""Voice activity detection (webrtcvad).

webrtcvad is chosen over Silero for Essential mode because it is tiny and pulls no
torch/onnx runtime — important for the 4 GB budget. It classifies short frames
(10/20/30 ms of 16-bit PCM) as speech or not; SpeechSegmenter turns that stream
into utterance boundaries with a little hangover so word endings aren't clipped.
"""

from __future__ import annotations

import webrtcvad

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_BYTES = int(SAMPLE_RATE * FRAME_MS / 1000) * 2  # 16-bit mono


class VAD:
    def __init__(self, aggressiveness: int = 2) -> None:
        # 0 (permissive) .. 3 (aggressive). 2 is a good default for a quiet room.
        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame_bytes: bytes) -> bool:
        if len(frame_bytes) != FRAME_BYTES:
            return False
        return self._vad.is_speech(frame_bytes, SAMPLE_RATE)


class SpeechSegmenter:
    """Feed 30 ms frames; get utterance start/end events.

    start after ``start_frames`` consecutive speech frames; end after
    ``end_frames`` consecutive non-speech frames (hangover). Returns one of
    ``None`` | ``"start"`` | ``"end"`` per frame.
    """

    def __init__(self, aggressiveness: int = 2, start_frames: int = 3,
                 end_frames: int = 20) -> None:
        self.vad = VAD(aggressiveness)
        self.start_frames = start_frames
        self.end_frames = end_frames
        self._speech_run = 0
        self._silence_run = 0
        self._in_speech = False

    def push(self, frame_bytes: bytes) -> str | None:
        speech = self.vad.is_speech(frame_bytes)
        if not self._in_speech:
            self._speech_run = self._speech_run + 1 if speech else 0
            if self._speech_run >= self.start_frames:
                self._in_speech = True
                self._silence_run = 0
                return "start"
        else:
            self._silence_run = 0 if speech else self._silence_run + 1
            if self._silence_run >= self.end_frames:
                self._in_speech = False
                self._speech_run = 0
                return "end"
        return None

    @property
    def in_speech(self) -> bool:
        return self._in_speech
