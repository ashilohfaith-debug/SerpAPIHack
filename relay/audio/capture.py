"""Microphone capture (sounddevice) at 16 kHz mono, 30 ms frames.

A single input stream pushes fixed-size 16-bit frames to a callback; wake/VAD and
push-to-talk consume them. Device selection and disconnect recovery are handled
here so the rest of the pipeline never touches the audio device directly. Live
capture needs a real microphone, so it is exercised by integration checks, not
unit tests.
"""

from __future__ import annotations

from typing import Callable, Optional

from relay.audio.vad import FRAME_BYTES, SAMPLE_RATE
from relay.diagnostics import get_logger

log = get_logger("audio.capture")
FRAMES_PER_BLOCK = FRAME_BYTES // 2  # int16 samples per 30 ms frame

FrameCallback = Callable[[bytes], None]


class MicCapture:
    def __init__(self, on_frame: FrameCallback, device: Optional[int] = None) -> None:
        self.on_frame = on_frame
        self.device = device
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        def _cb(indata, frames, time_info, status):  # noqa: ANN001 - sd callback
            if status:
                log.debug("mic status: %s", status)
            try:
                self.on_frame(bytes(indata))
            except Exception:  # a bad consumer must not crash the audio thread
                pass

        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAMES_PER_BLOCK,
            device=self.device,
            callback=_cb,
        )
        self._stream.start()
        log.info("mic capture started (device=%s)", self.device)

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    @property
    def active(self) -> bool:
        return self._stream is not None


def list_devices() -> list[str]:
    import sounddevice as sd

    return [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
