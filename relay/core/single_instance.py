"""Single-instance guard.

Only one RELAY should drive the desktop at a time. This takes an exclusive OS lock
on a file in the per-user data dir; a second launch fails to acquire it and can exit
cleanly. The lock is released when the process ends (or explicitly), so a crash
doesn't leave RELAY unlaunchable.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

from relay.config import user_data_dir

QUIT_EVENT = "Local\\RelayQuitRequest"


class SingleInstance:
    def __init__(self, name: str = "relay") -> None:
        self.path = user_data_dir() / f"{name}.lock"
        self._fh = None

    def acquire(self) -> bool:
        """Return True if this process now holds the single-instance lock."""
        try:
            self._fh = open(self.path, "a+")
        except OSError:
            return False
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            try:
                self._fh.close()
            finally:
                self._fh = None
            return False

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                self._fh.close()
            finally:
                self._fh = None

    def __enter__(self) -> "SingleInstance":
        self.acquired = self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateEventW.restype = wintypes.HANDLE
    k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenEventW.restype = wintypes.HANDLE
    k.SetEvent.argtypes = [wintypes.HANDLE]
    k.SetEvent.restype = wintypes.BOOL
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return k


class QuitSignal:
    """The launch key toggles RELAY, like Narrator's Ctrl+Win+Enter: pressed while RELAY
    is running, the new launch asks the running one to close (a named Windows event)
    and exits. RELAY has no window a blind user could close, so this is the keyboard
    way out when speaking isn't possible."""

    def __init__(self, name: str = QUIT_EVENT) -> None:
        self.name = name
        self._handle = None
        self._stop = threading.Event()

    def listen(self, on_quit: Callable[[], None]) -> bool:
        if os.name != "nt":
            return False
        k = _kernel32()
        self._handle = k.CreateEventW(None, False, False, self.name)   # auto-reset
        if not self._handle:
            return False

        handle = self._handle

        def wait() -> None:
            try:
                while not self._stop.is_set():
                    if k.WaitForSingleObject(handle, 500) == 0:       # WAIT_OBJECT_0
                        if not self._stop.is_set():
                            on_quit()
            finally:
                k.CloseHandle(handle)          # closed here, never under a waiting call
        threading.Thread(target=wait, name="quit-signal", daemon=True).start()
        return True

    def stop(self) -> None:
        self._stop.set()                        # the waiting thread closes the handle
        self._handle = None

    @staticmethod
    def request(name: str = QUIT_EVENT) -> bool:
        """Ask a running RELAY to close. False if none is listening."""
        if os.name != "nt":
            return False
        k = _kernel32()
        h = k.OpenEventW(0x0002, False, name)                         # EVENT_MODIFY_STATE
        if not h:
            return False
        try:
            return bool(k.SetEvent(h))
        finally:
            k.CloseHandle(h)
