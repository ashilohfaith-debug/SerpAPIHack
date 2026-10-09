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


_ACTIVE_WORKERS: list[_WorkerThread] = []
_WORKERS_LOCK = threading.Lock()


class _WorkerThread:
    """One COM-owning thread that serves callables from a queue."""

    def __init__(self) -> None:
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="uia-worker", daemon=True)
        self.alive = True
        self._observing = False
        with _WORKERS_LOCK:
            _ACTIVE_WORKERS.append(self)
            # Prune dead threads to prevent unbound list growth
            _ACTIVE_WORKERS[:] = [w for w in _ACTIVE_WORKERS if w.alive and w._thread.is_alive()]
        self._thread.start()

    def is_observing(self) -> bool:
        return self._observing

    def set_observing(self, val: bool) -> None:
        self._observing = val

    def _run(self) -> None:
        from relay.perception.ocr import attach_thread_to_active_desktop

        attach_thread_to_active_desktop()
        # All UIA calls happen on this thread, so it owns COM: initialise it here, as a
        # single-threaded apartment (what comtypes' own import does). Relying on that
        # import only worked while this thread happened to import comtypes first; now
        # other threads (audio-device watch, volume) may do so earlier.
        try:
            import comtypes

            comtypes.CoInitialize()
        except Exception:
            pass

        try:
            import uiautomation as auto

            auto.SetGlobalSearchTimeout(1.0)
            auto.TIME_OUT_SECOND = 1.0
        except Exception:
            pass
        try:
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
                if not self.alive:
                    # Thread was abandoned due to caller timeout; terminate upon unblocking
                    log.info("abandoned UIA thread unblocked and self-terminated")
                    return
        finally:
            self.alive = False
            with _WORKERS_LOCK:
                if self in _ACTIVE_WORKERS:
                    _ACTIVE_WORKERS.remove(self)

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
        self._observe_lock = threading.Lock()
        self._retired_workers: list[_WorkerThread] = []
        self._monitor_stop = threading.Event()
        self._monitor: threading.Thread | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = _WorkerThread()

    def _ensure_worker(self) -> _WorkerThread | None:
        with self._lock:
            if self._worker is None or not self._worker.alive:
                self._retired_workers = [w for w in self._retired_workers if w._thread.is_alive()]
                if (
                    self._worker is not None
                    and self._worker._thread.is_alive()
                    and self._worker not in self._retired_workers
                ):
                    self._retired_workers.append(self._worker)
                # A hung COM call cannot be killed safely. Bound abandoned threads
                # instead of creating an unlimited number during provider failures.
                if len(self._retired_workers) >= 2:
                    return None
                if self._worker is not None:
                    log.warning("UIA worker unresponsive; starting a replacement")
                self._worker = _WorkerThread()
            return self._worker

    def observe(self, timeout: float = 5.0) -> ScreenSnapshot | None:
        """Take a fresh observation. Returns the snapshot, or None on timeout
        (worker restarted). Publishes ``perception.change`` when the structure
        changed vs the previous snapshot."""
        if not self._observe_lock.acquire(blocking=False):
            return self._current
        try:
            return self._observe_once(timeout)
        finally:
            self._observe_lock.release()

    def _observe_once(self, timeout: float) -> ScreenSnapshot | None:
        worker = self._ensure_worker()
        if worker is None:
            return None
        self._version += 1
        version = self._version
        worker.set_observing(True)
        try:
            box, timed_out = worker.submit(lambda: self._observe_fn(version), timeout)
        finally:
            worker.set_observing(False)
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
            self._bus.emit(
                "perception.change",
                foreground_app=snap.foreground_app,
                foreground_title=snap.foreground_title,
                summary=snap.summary(),
                observation_version=snap.observation_version,
            )
        return snap

    def run(self, fn: Callable, timeout: float = 2.0):
        """Run an arbitrary callable ON the UIA thread (for executor UIA actions,
        which must touch controls on the same thread). Returns (value, ok): ok is
        False on timeout/restart or if the callable raised."""
        worker = self._ensure_worker()
        if worker is None:
            return None, False
        box, timed_out = worker.submit(fn, timeout)
        if timed_out or box is None or "error" in box:
            if box is not None and "error" in box:
                log.warning("UIA action failed: %s", box["error"])
            return None, False
        return box["value"], True

    def activate_app(self, app: str, timeout: float = 3.0) -> bool:
        """Bring a launched app's window to the foreground (best-effort — Windows
        may refuse a foreground change; the caller still verifies)."""
        from relay.perception import uia

        val, ok = self.run(lambda: uia.find_and_activate(app), timeout)
        return bool(ok and val)

    def list_windows(self, timeout: float = 3.0) -> list[dict]:
        """All visible top-level windows (title/app/hwnd)."""
        from relay.perception import uia

        val, ok = self.run(uia.list_top_windows, timeout)
        return val if (ok and val) else []

    @property
    def live(self) -> ScreenSnapshot | None:
        """Current L1 snapshot (may be stale between observes)."""
        return self._current

    @live.setter
    def live(self, val: ScreenSnapshot | None) -> None:
        self._current = val

    def is_stale(self, snap: ScreenSnapshot | None) -> bool:
        """True if the given snapshot is not the current observation — callers
        must re-observe before acting on its elements."""
        return (
            snap is None
            or self._current is None
            or snap.observation_version != self._current.observation_version
        )

    # --- event-driven change monitor (WinEvents + debouncing + polling fallback) ---
    def start_change_monitor(self, interval: float = 0.3) -> None:
        if self._monitor is not None or getattr(self, "_winevent_monitor", None) is not None:
            return
        try:
            from relay.perception.events import WinEventMonitor

            self._winevent_monitor = WinEventMonitor(
                on_change=lambda: self.observe(), debounce_s=0.15
            )
            if self._winevent_monitor.start():
                log.info("event-driven screen observation active (WinEvents)")
                return
        except Exception as e:
            log.warning("could not initialize WinEvent monitor: %s", e)
        # Polling fallback if WinEvents unavailable
        self._monitor_stop.clear()
        self._monitor = threading.Thread(
            target=self._monitor_loop, args=(interval,), name="uia-change-monitor", daemon=True
        )
        self._monitor.start()

    def _monitor_loop(self, interval: float) -> None:
        from relay.perception.ocr import attach_thread_to_active_desktop

        attach_thread_to_active_desktop()
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
        if hasattr(self, "_winevent_monitor") and self._winevent_monitor is not None:
            try:
                self._winevent_monitor.stop()
            except Exception:
                pass
            self._winevent_monitor = None
        self._monitor_stop.set()
        if self._monitor is not None and self._monitor.is_alive():
            try:
                self._monitor.join(timeout=1.0)
            except Exception:
                pass
            self._monitor = None
        with self._lock:
            w = self._worker
            self._worker = None
        if w is not None:
            try:
                w._q.put((None, None, None))
            except Exception:
                pass
