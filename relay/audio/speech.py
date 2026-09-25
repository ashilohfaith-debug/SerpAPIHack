"""Speech output queue with reliable interruption (barge-in) and emergency flush.

A single worker thread owns the one audio-output path: it pulls text (or a short
earcon), synthesizes it with the TTS engine, and plays it. ``interrupt()`` stops the
current utterance and clears the queue so the user perceives a stop within one
playback poll — this is what makes "stop" feel instant. The emergency stop flushes
the same queue through the same path.

Each item can carry ``on_done(completed)`` — called after it finishes (True) or is
interrupted/dropped (False) — which is how continuous reading advances paragraph by
paragraph and stops exactly where the user interrupted. ``last_active`` lets the
microphone loop ignore RELAY's own voice (half-duplex), so RELAY never hears itself.

Playback is injectable (``player``) so the queue logic is unit-tested headlessly
with a fake player; the default uses sounddevice.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from relay.diagnostics import get_logger

log = get_logger("audio.speech")

# player(audio, sample_rate, stop_event) -> plays until done or stop_event is set.
Player = Callable[[np.ndarray, int, threading.Event], None]
Done = Callable[[bool], None]


def _sounddevice_player(audio: np.ndarray, sr: int, stop: threading.Event) -> None:
    import sounddevice as sd
    sd.play(audio, sr)
    # Poll so a set stop_event cuts playback promptly (barge-in latency ~ one poll).
    stream = sd.get_stream()
    while stream is not None and stream.active:
        if stop.wait(0.02):
            sd.stop()
            return
        stream = sd.get_stream()


@dataclass
class _Item:
    text: str = ""
    audio: Optional[np.ndarray] = None
    sr: int = 0
    on_done: Optional[Done] = None


class SpeechQueue:
    def __init__(self, tts, player: Optional[Player] = None, emergency=None) -> None:
        self._tts = tts
        self._player = player or _sounddevice_player
        self._q: "queue.Queue[_Item | None]" = queue.Queue()
        self._stop_current = threading.Event()
        self._speaking = threading.Event()
        self._shutdown = threading.Event()
        self._last_active = 0.0
        self._thread = threading.Thread(target=self._worker, name="speech", daemon=True)
        self._thread.start()
        if emergency is not None:
            emergency.register_flush(self.interrupt)

    @property
    def tts(self):
        return self._tts

    def set_tts(self, tts) -> None:
        """Swap the voice (e.g. offline Piper <-> connected Indian-language voice)."""
        self._tts = tts

    @property
    def is_speaking(self) -> bool:
        return self._speaking.is_set() or not self._q.empty()

    @property
    def last_active(self) -> float:
        """monotonic time audio last finished (or now, while speaking)."""
        return time.monotonic() if self._speaking.is_set() else self._last_active

    def say(self, text: str, on_done: Optional[Done] = None) -> None:
        if text and text.strip():
            self._q.put(_Item(text=text, on_done=on_done))
        elif on_done is not None:
            on_done(True)

    def play(self, audio: np.ndarray, sr: int, on_done: Optional[Done] = None) -> None:
        """Queue a short sound (earcon) on the same output path as speech."""
        self._q.put(_Item(audio=audio, sr=sr, on_done=on_done))

    def interrupt(self) -> None:
        """Barge-in: stop the current utterance and drop everything queued."""
        self._stop_current.set()
        dropped: list[_Item] = []
        while True:
            try:
                it = self._q.get_nowait()
            except queue.Empty:
                break
            if it is not None:
                dropped.append(it)
        for it in dropped:
            self._finish(it, False)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until nothing is queued or playing (used by CLI demos/tests)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not self.is_speaking:
                return True
            time.sleep(0.05)
        return False

    def shutdown(self) -> None:
        self._shutdown.set()
        self.interrupt()
        self._q.put(None)  # unblock the worker

    @staticmethod
    def _finish(it: _Item, completed: bool) -> None:
        if it.on_done is not None:
            try:
                it.on_done(completed)
            except Exception as e:
                log.warning("speech callback failed: %s", e)

    def _worker(self) -> None:
        while not self._shutdown.is_set():
            it = self._q.get()
            if it is None or self._shutdown.is_set():
                return
            self._stop_current.clear()
            self._speaking.set()
            completed = False
            try:
                if it.audio is not None:
                    audio, sr = it.audio, it.sr
                else:
                    audio, sr = self._tts.synth_to_array(it.text)
                if len(audio) and not self._stop_current.is_set():
                    self._player(audio, sr, self._stop_current)
                completed = not self._stop_current.is_set()
            except Exception as e:  # never let one utterance kill the speech thread
                log.warning("speech failed: %s", e)
            finally:
                self._last_active = time.monotonic()
                self._speaking.clear()
            self._finish(it, completed)
