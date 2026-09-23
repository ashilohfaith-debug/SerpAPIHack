"""Cooperative cancellation.

Long-running work (planning, a UIA enumeration, an executor step) periodically
checks a CancellationToken and bails out cleanly. This is how "cancel task"
stops pending work without killing threads mid-write. Emergency stop is a
stronger, separate mechanism (see emergency.py) that also flushes queued input.
"""

from __future__ import annotations

import threading
from collections.abc import Callable


class Cancelled(Exception):
    """Raised by ``raise_if_cancelled`` when a token is set."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        already = self._event.is_set()
        self._event.set()
        if already:
            return
        with self._lock:
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb()
            except Exception:
                pass

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise Cancelled()

    def on_cancel(self, callback: Callable[[], None]) -> None:
        """Register a callback fired once on cancel (or immediately if already
        cancelled)."""
        with self._lock:
            if self._event.is_set():
                run_now = True
            else:
                self._callbacks.append(callback)
                run_now = False
        if run_now:
            try:
                callback()
            except Exception:
                pass

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancelled or timeout; returns True if cancelled."""
        return self._event.wait(timeout)
