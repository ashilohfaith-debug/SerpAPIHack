"""Speech output queue with reliable interruption (barge-in) and emergency flush.

Two threads form a short pipeline so speech has no gaps: a synthesis thread turns the
next queued text into audio while the playback thread is still playing the current
one. (Streamed answers arrive sentence by sentence; without the overlap every
sentence boundary would add the synthesis time as silence.) ``interrupt()`` stops the
current utterance and drops everything queued or pre-synthesised, so "stop" is
perceived within one playback poll. The emergency stop flushes the same path.

Each item can carry ``on_done(completed)`` — called after it finishes (True) or is
interrupted/dropped (False) — which is how continuous reading advances paragraph by
paragraph and stops exactly where the user interrupted. ``last_active`` lets the
microphone loop ignore RELAY's own voice (half-duplex).

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
    gen: int = 0


class SpeechQueue:
    def __init__(self, tts, player: Optional[Player] = None, emergency=None) -> None:
        self._tts = tts
        self._player = player or _sounddevice_player
        self._q: "queue.Queue[_Item | None]" = queue.Queue()  # text to synthesise
        self._ready: "queue.Queue[_Item | None]" = queue.Queue(maxsize=2)  # audio to play
        self._stop_current = threading.Event()
        self._speaking = threading.Event()
        self._synthesising = threading.Event()
        self._shutdown = threading.Event()
        self._gen = 0
        self._synth_gen = -1  # generation of the text being synthesised now
        self._gen_lock = threading.Lock()
        self._last_active = 0.0
        self._synth_thread = threading.Thread(
            target=self._synth_worker, name="speech-synth", daemon=True
        )
        self._thread = threading.Thread(target=self._play_worker, name="speech", daemon=True)
        self._synth_thread.start()
        self._thread.start()
        if emergency is not None:
            emergency.register_flush(self.interrupt)

    @property
    def tts(self):
        return self._tts

    def set_tts(self, tts) -> None:
        """Swap the voice engine (e.g. Piper <-> the Windows SAPI fallback)."""
        self._tts = tts

    @property
    def is_speaking(self) -> bool:
        # a synthesis still running for an interrupted generation (e.g. an online voice
        # request in flight) is not speech: after "stop" the microphone must open at once
        synthesising = self._synthesising.is_set() and self._synth_gen == self._gen
        return (
            self._speaking.is_set()
            or synthesising
            or not self._q.empty()
            or not self._ready.empty()
        )

    @property
    def last_active(self) -> float:
        """monotonic time audio last finished (or now, while speaking)."""
        return time.monotonic() if self._speaking.is_set() else self._last_active

    def say(self, text: str, on_done: Optional[Done] = None) -> None:
        if text and text.strip():
            self._q.put(_Item(text=text, on_done=on_done, gen=self._gen))
        elif on_done is not None:
            on_done(True)

    def play(self, audio: np.ndarray, sr: int, on_done: Optional[Done] = None) -> None:
        """Queue a short sound (earcon) on the same output path as speech."""
        self._q.put(_Item(audio=audio, sr=sr, on_done=on_done, gen=self._gen))

    def interrupt(self) -> None:
        """Barge-in: stop the current utterance and drop everything queued."""
        with self._gen_lock:
            self._gen += 1  # anything synthesised for the old generation is stale
        self._stop_current.set()
        dropped: list[_Item] = []
        for q in (self._q, self._ready):
            while True:
                try:
                    it = q.get_nowait()
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
        self._q.put(None)  # unblock the synth worker
        try:
            self._ready.put_nowait(None)  # unblock the play worker
        except queue.Full:
            pass

    @staticmethod
    def _finish(it: _Item, completed: bool) -> None:
        if it.on_done is not None:
            try:
                it.on_done(completed)
            except Exception as e:
                log.warning("speech callback failed: %s", e)

    # ---- stage 1: synthesis (runs ahead of playback) ----
    def _synth_worker(self) -> None:
        while not self._shutdown.is_set():
            it = self._q.get()
            if it is None or self._shutdown.is_set():
                self._ready.put(None)
                return
            if it.gen != self._gen:  # interrupted while waiting
                self._finish(it, False)
                continue
            if it.audio is None:
                self._synth_gen = it.gen
                self._synthesising.set()
                try:
                    it.audio, it.sr = self._tts.synth_to_array(it.text)
                except Exception as e:  # never let one utterance kill speech
                    log.warning("speech synthesis failed: %s", e)
                    it.audio, it.sr = np.zeros(0, dtype=np.float32), 16000
                finally:
                    self._synthesising.clear()
            if it.gen != self._gen:  # interrupted during synthesis
                self._finish(it, False)
                continue
            while not self._shutdown.is_set():
                try:
                    self._ready.put(it, timeout=0.1)
                    break
                except queue.Full:
                    if it.gen != self._gen:
                        self._finish(it, False)
                        break

    # ---- stage 2: playback ----
    def _play_worker(self) -> None:
        while not self._shutdown.is_set():
            it = self._ready.get()
            if it is None or self._shutdown.is_set():
                return
            if it.gen != self._gen:
                self._finish(it, False)
                continue
            self._stop_current.clear()
            self._speaking.set()
            completed = False
            try:
                if it.audio is not None and len(it.audio):
                    self._player(it.audio, it.sr, self._stop_current)
                completed = not self._stop_current.is_set() and it.gen == self._gen
            except Exception as e:
                log.warning("speech playback failed: %s", e)
            finally:
                self._last_active = time.monotonic()
                self._speaking.clear()
            self._finish(it, completed)
