"""Native WinEvent observation for event-driven screen perception.

Subscribes to native Win32/UIA WinEvents (foreground window change, focus change,
dialog start/end, and state/name changes) with event storm debouncing, eliminating
polling. Falls back gracefully if WinEvent registration is unavailable.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

from relay.diagnostics import get_logger

log = get_logger("perception.events")

# Standard WinEvent IDs
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_ALERT = 0x0002
EVENT_SYSTEM_DIALOGSTART = 0x0010
EVENT_SYSTEM_DIALOGEND = 0x0011
EVENT_OBJECT_FOCUS = 0x8005
EVENT_OBJECT_STATECHANGE = 0x800A
EVENT_OBJECT_NAMECHANGE = 0x800C
EVENT_OBJECT_VALUECHANGE = 0x800E

WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

WinEventProc = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,  # hWinEventHook
    wintypes.DWORD,  # event
    wintypes.HWND,  # hwnd
    wintypes.LONG,  # idObject
    wintypes.LONG,  # idChild
    wintypes.DWORD,  # idEventThread
    wintypes.DWORD,  # dwmsEventTime
)


class WinEventMonitor:
    """Event-driven screen observation monitor with debouncing."""

    def __init__(self, on_change: Callable[[], None], debounce_s: float = 0.15) -> None:
        self._on_change = on_change
        self._debounce_s = debounce_s
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._debounce_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._hook = None
        self._hook_proc = None  # prevent GC of callback pointer
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="winevent-monitor", daemon=True)
        self._thread.start()
        # Wait up to 2 seconds for hook initialization
        time.sleep(0.1)
        return self._active

    def _trigger_debounced(self) -> None:
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self._debounce_s, self._fire_change)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _fire_change(self) -> None:
        if self._stop_event.is_set():
            return
        try:
            self._on_change()
        except Exception as e:
            log.warning("error in change observer: %s", e)

    def _run(self) -> None:
        try:
            from relay.perception.ocr import attach_thread_to_active_desktop

            attach_thread_to_active_desktop()
        except Exception:
            pass

        user32 = getattr(ctypes, "windll", None) and getattr(ctypes.windll, "user32", None)
        if user32 is None or not hasattr(user32, "SetWinEventHook"):
            log.info("WinEventHook not supported on this platform")
            return

        def _callback(h_hook, event, hwnd, id_obj, id_child, id_thread, dw_time):
            watched = {
                EVENT_SYSTEM_FOREGROUND,
                EVENT_SYSTEM_DIALOGSTART,
                EVENT_SYSTEM_DIALOGEND,
                EVENT_OBJECT_FOCUS,
                EVENT_OBJECT_STATECHANGE,
                EVENT_OBJECT_NAMECHANGE,
                EVENT_OBJECT_VALUECHANGE,
            }
            if event in watched and id_obj in (0, -4):  # OBJID_WINDOW, OBJID_CLIENT
                self._trigger_debounced()

        self._hook_proc = WinEventProc(_callback)
        flags = WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS

        # Register for events from FOREGROUND (0x0003) to OBJECT_VALUECHANGE (0x800E)
        self._hook = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_OBJECT_VALUECHANGE,
            None,
            self._hook_proc,
            0,
            0,
            flags,
        )
        if not self._hook:
            log.warning("SetWinEventHook failed; will use polling fallback")
            return

        self._active = True
        log.info("WinEvent observation hook active (foreground, focus, dialogs, names)")
        msg = wintypes.MSG()
        try:
            while not self._stop_event.is_set():
                # PeekMessage to allow non-blocking exit
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                    if msg.message == 0x0012:  # WM_QUIT
                        break
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.05)
        finally:
            self._active = False
            if self._hook:
                try:
                    user32.UnhookWinEvent(self._hook)
                except Exception:
                    pass
                self._hook = None

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None
