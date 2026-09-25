"""Single-instance guard.

Only one RELAY should drive the desktop at a time. This takes an exclusive OS lock
on a file in the per-user data dir; a second launch fails to acquire it and can exit
cleanly. The lock is released when the process ends (or explicitly), so a crash
doesn't leave RELAY unlaunchable.
"""

from __future__ import annotations

import os

from relay.config import user_data_dir


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
