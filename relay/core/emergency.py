"""Emergency stop — the safety backstop.

"Emergency stop" must halt queued automation and input injection IMMEDIATELY and
stay responsive even if the planner, UIA worker or an inference worker is blocked.
So it depends on NOTHING but a threading.Event and a list of registered flush
callbacks — it never calls into those workers.

Contract:
  * ``engage()`` sets a global flag, flushes registered queues (e.g. the pending
    input-injection queue, the TTS queue), and notifies listeners. It is safe to
    call from any thread, including a dedicated hotkey-listener thread.
  * The executor MUST check ``is_engaged`` before dispatching any input event and
    abort if set. That is what makes a stop during a blocked worker effective:
    the moment the worker unblocks, the next dispatch is refused.
  * ``reset()`` clears the flag for a fresh session (explicit, never automatic
    mid-task).
"""

from __future__ import annotations

import threading
from collections.abc import Callable


class EmergencyStop:
    def __init__(self) -> None:
        self._engaged = threading.Event()
        self._flushers: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    @property
    def is_engaged(self) -> bool:
        return self._engaged.is_set()

    def register_flush(self, flush: Callable[[], None]) -> None:
        """Register a queue-flush callback (input queue, speech queue, …). Called
        synchronously on engage; must itself be non-blocking and worker-free."""
        with self._lock:
            self._flushers.append(flush)

    def add_listener(self, listener: Callable[[], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def engage(self, reason: str = "user") -> None:
        """Trip the stop. Idempotent. Never blocks on a worker."""
        first = not self._engaged.is_set()
        self._engaged.set()
        if not first:
            return
        with self._lock:
            flushers = list(self._flushers)
            listeners = list(self._listeners)
        for f in flushers:
            try:
                f()
            except Exception:
                pass  # a failing flusher must not prevent the others
        for ln in listeners:
            try:
                ln()
            except Exception:
                pass

    def reset(self) -> None:
        self._engaged.clear()
