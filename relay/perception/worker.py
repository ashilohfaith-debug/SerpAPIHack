"""Dedicated UI Automation worker + live-screen (L1) holder.

All UIA access is confined to one dedicated thread so a blocked/hung accessibility
provider can never freeze the core, audio or emergency stop. Calls are bounded by a
caller-side timeout; if the worker thread hangs on a bad provider, it is abandoned
(daemon) and a fresh worker thread is started for subsequent observations — the
caller stays responsive and just gets ``None`` for the timed-out call.

Change detection uses a lightweight foreground-window poll (a cheap Win32 call)
rather than native UIA event callbacks, which would need a COM message pump on the
UIA thread; a full observe runs only when that cheap signal changes. The most recent
ScreenSnapshot is L1 live-screen memory: held in RAM, replaced (not accumulated) on
each observe, so stale element references from an old observation are never reused.

The observe function is injectable so the worker's timeout/restart logic is unit-
tested headlessly; the real one is perception.uia.observe.
"""

from __future__ import annotations

import ctypes
import queue
import threading
from typing import Callable, Optional

from relay.diagnostics import get_logger
from relay.perception.semantic import ScreenSnapshot

log = get_logger("perception.worker")

ObserveFn = Callable[[int], ScreenSnapshot]


def _default_observe(version: int) -> ScreenSnapshot:
    from relay.perception import uia
    return uia.observe(version)


class _WorkerThread:
    """One COM-owning thread that serves callables from a queue."""

    def __init__(self) -> None:
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="uia-worker", daemon=True)
        self.alive = True
        self._thread.start()

    def _run(self) -> None:
        # Let the uiautomation/comtypes library initialise COM on this thread; all
        # UIA calls happen here, so the apartment stays consistent.
        while True:
            fn, box, done = self._q.get()
            if fn is None:
                return
            try:
                box["value"] = fn()
            except BaseException as e:  # report any provider failure to the caller
                box["error"] = e
            finally:
                done.set()

    def submit(self, fn: Callable, timeout: float):
        box: dict = {}
        done = threading.Event()
        self._q.put((fn, box, done))
        if not done.wait(timeout):
            self.alive = False  # thread is stuck on a bad provider; abandon it
            return None, True
        return box, False


class UIAWorker:
    def __init__(self, bus=None, observe_fn: Optional[ObserveFn] = None) -> None:
        self._observe_fn = observe_fn or _default_observe
        self._bus = bus
        self._version = 0
        self._current: ScreenSnapshot | None = None
        self._worker: _WorkerThread | None = None
        self._lock = threading.Lock()
        self._monitor_stop = threading.Event()
        self._monitor: threading.Thread | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = _WorkerThread()

    def _ensure_worker(self) -> _WorkerThread:
        with self._lock:
            if self._worker is None or not self._worker.alive:
                if self._worker is not None:
                    log.warning("UIA worker unresponsive; starting a replacement")
                self._worker = _WorkerThread()
            return self._worker

    def observe(self, timeout: float = 2.0) -> ScreenSnapshot | None:
        """Take a fresh observation. Returns the snapshot, or None on timeout
        (worker restarted). Publishes ``perception.change`` when the structure
        changed vs the previous snapshot."""
        worker = self._ensure_worker()
        self._version += 1
        version = self._version
        box, timed_out = worker.submit(lambda: self._observe_fn(version), timeout)
        if timed_out or box is None:
            log.warning("observe timed out (v%s)", version)
            return None
        if "error" in box:
            log.warning("observe failed: %s", box["error"])
            return None
        snap: ScreenSnapshot = box["value"]
        prev = self._current
        self._current = snap  # L1 replace (never accumulate stale elements)
        if self._bus is not None and (prev is None or prev.fingerprint() != snap.fingerprint()):
            self._bus.emit("perception.change",
                           foreground_app=snap.foreground_app,
                           foreground_title=snap.foreground_title,
                           summary=snap.summary(),
                           observation_version=snap.observation_version)
        return snap

    @property
    def live(self) -> ScreenSnapshot | None:
        """Current L1 snapshot (may be stale between observes)."""
        return self._current

    def is_stale(self, snap: ScreenSnapshot | None) -> bool:
        """True if the given snapshot is not the current observation — callers
        must re-observe before acting on its elements."""
        return snap is None or self._current is None \
            or snap.observation_version != self._current.observation_version

    # --- lightweight change monitor (foreground-window poll) ---
    def start_change_monitor(self, interval: float = 0.3) -> None:
        if self._monitor is not None:
            return
        self._monitor_stop.clear()
        self._monitor = threading.Thread(target=self._monitor_loop, args=(interval,),
                                         name="uia-change-monitor", daemon=True)
        self._monitor.start()

    def _monitor_loop(self, interval: float) -> None:
        last_hwnd = None
        user32 = ctypes.windll.user32
        while not self._monitor_stop.wait(interval):
            try:
                hwnd = user32.GetForegroundWindow()
            except Exception:
                continue
            if hwnd != last_hwnd:
                last_hwnd = hwnd
                self.observe()  # publishes a change event if the structure differs

    def stop(self) -> None:
        self._monitor_stop.set()
        with self._lock:
            w = self._worker
            self._worker = None
        if w is not None:
            try:
                w._q.put((None, None, None))
            except Exception:
                pass
