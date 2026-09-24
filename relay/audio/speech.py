"""Speech output queue with reliable interruption (barge-in) and emergency flush.

A single worker thread owns the one audio-output path: it pulls text, synthesizes
it with the TTS engine, and plays it. ``interrupt()`` stops the current utterance
and clears the queue so the user perceives a stop within one playback callback —
this is what makes barge-in feel instant. The emergency stop flushes the same
queue through the same path.

Playback is injectable (``player``) so the queue logic is unit-tested headlessly
with a fake player; the default uses sounddevice.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, Optional

import numpy as np

from relay.diagnostics import get_logger

log = get_logger("audio.speech")

# player(audio, sample_rate, stop_event) -> plays until done or stop_event is set.
Player = Callable[[np.ndarray, int, threading.Event], None]


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


class SpeechQueue:
    def __init__(self, tts, player: Optional[Player] = None, emergency=None) -> None:
        self._tts = tts
        self._player = player or _sounddevice_player
        self._q: "queue.Queue[str]" = queue.Queue()
        self._stop_current = threading.Event()
        self._speaking = threading.Event()
        self._shutdown = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="speech", daemon=True)
        self._thread.start()
        if emergency is not None:
            emergency.register_flush(self.interrupt)

    @property
    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def say(self, text: str) -> None:
        if text and text.strip():
            self._q.put(text)

    def interrupt(self) -> None:
        """Barge-in: stop the current utterance and drop everything queued."""
        self._stop_current.set()
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def shutdown(self) -> None:
        self._shutdown.set()
        self.interrupt()
        self._q.put("")  # unblock the worker

    def _worker(self) -> None:
        while not self._shutdown.is_set():
            text = self._q.get()
            if self._shutdown.is_set():
                return
            if not text.strip():
                continue
            self._stop_current.clear()
            self._speaking.set()
            try:
                audio, sr = self._tts.synth_to_array(text)
                if len(audio) and not self._stop_current.is_set():
                    self._player(audio, sr, self._stop_current)
            except Exception as e:  # never let one utterance kill the speech thread
                log.warning("speech failed: %s", e)
            finally:
                self._speaking.clear()
