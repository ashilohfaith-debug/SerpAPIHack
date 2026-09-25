"""Top-level window management — list, switch to, minimise, maximise, close.

Plain Win32 (EnumWindows / ShowWindow / WM_CLOSE) so it is fast and safe to call from
any thread. "Close" posts WM_CLOSE — the same as clicking the window's X — so an app
with unsaved work shows its own "Save changes?" prompt; RELAY never force-kills a
process. Switching uses the documented foreground rules with the standard fallbacks,
and the caller verifies the result instead of assuming it worked.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
WM_CLOSE = 0x0010
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_CLOAKED = 14

_SKIP_TITLES = {"program manager", "windows input experience", "settings", "",
                "microsoft text input application", "nvidia geforce overlay"}
_SKIP_CLASSES = {"Shell_TrayWnd", "Progman", "WorkerW", "Windows.UI.Core.CoreWindow"}


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    app: str          # process name, e.g. "notepad.exe"
    minimized: bool = False

    @property
    def spoken(self) -> str:
        app = _friendly_app(self.app)
        t = self.title
        if not t or t.lower() == app.lower():
            return app
        known = (self.app or "").lower() in _FRIENDLY
        if known and app.lower() not in t.lower():
            return f"{t}, in {app}"
        return t


_FRIENDLY = {"winword.exe": "Word", "excel.exe": "Excel", "powerpnt.exe": "PowerPoint",
             "chrome.exe": "Chrome", "msedge.exe": "Edge", "brave.exe": "Brave",
             "firefox.exe": "Firefox", "notepad.exe": "Notepad", "explorer.exe": "File Explorer",
             "whatsapp.root.exe": "WhatsApp", "whatsapp.exe": "WhatsApp",
             "spotify.exe": "Spotify", "calculatorapp.exe": "Calculator"}


def _friendly_app(exe: str) -> str:
    e = (exe or "").lower()
    return _FRIENDLY.get(e, e.replace(".exe", "").capitalize() or "App")


def _proc_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil
        return psutil.Process(pid.value).name()
    except Exception:
        return ""


def _cloaked(hwnd: int) -> bool:
    try:
        val = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val),
                                                   ctypes.sizeof(val))
        return val.value != 0
    except Exception:
        return False


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value.strip()


def _class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def list_windows() -> list[WindowInfo]:
    """Visible, user-facing top-level windows in Alt+Tab order (most recent first)."""
    out: list[WindowInfo] = []
    if user32 is None:
        return out
    own_pid = ctypes.windll.kernel32.GetCurrentProcessId()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # owned
                return True
            if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            title = _title(hwnd)
            if title.lower() in _SKIP_TITLES or _class(hwnd) in _SKIP_CLASSES:
                return True
            if _cloaked(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == own_pid:
                return True
            out.append(WindowInfo(int(hwnd), title, _proc_name(hwnd),
                                  bool(user32.IsIconic(hwnd))))
        except Exception:
            pass
        return True

    user32.EnumWindows(cb, 0)
    return out


def foreground() -> WindowInfo | None:
    if user32 is None:
        return None
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    return WindowInfo(int(hwnd), _title(hwnd), _proc_name(hwnd), bool(user32.IsIconic(hwnd)))


def find(query: str, windows: list[WindowInfo] | None = None) -> WindowInfo | None:
    """Best window for 'chrome' / 'notepad' / 'my document' (app or title match)."""
    q = (query or "").lower().replace(".exe", "").strip()
    for w in ("the ", "my ", "window", "app"):
        q = q.replace(w, " ")
    q = " ".join(q.split())
    if not q:
        return None
    wins = windows if windows is not None else list_windows()
    for w in wins:                                   # app name first (exact-ish)
        app = _friendly_app(w.app).lower()
        if q == app or q == w.app.lower().replace(".exe", ""):
            return w
    for w in wins:
        if q in _friendly_app(w.app).lower() or q in w.app.lower():
            return w
    for w in wins:
        if q in w.title.lower():
            return w
    toks = set(q.split())
    for w in wins:
        if toks and toks <= set(w.title.lower().split()):
            return w
    return None


def activate(hwnd: int) -> bool:
    """Bring a window to the foreground. Windows may refuse a background process;
    the standard fallbacks are tried, then the caller verifies."""
    if user32 is None:
        return False
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        if user32.SetForegroundWindow(hwnd) and user32.GetForegroundWindow() == hwnd:
            return True
        fg = user32.GetForegroundWindow()
        cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(fg_tid) and bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
        if user32.GetForegroundWindow() != hwnd:
            user32.SwitchToThisWindow(hwnd, True)
        time.sleep(0.15)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def minimize(hwnd: int) -> bool:
    user32.ShowWindow(hwnd, SW_MINIMIZE)
    time.sleep(0.2)
    return bool(user32.IsIconic(hwnd))


def maximize(hwnd: int) -> bool:
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    time.sleep(0.2)
    return bool(user32.IsZoomed(hwnd))


def restore(hwnd: int) -> bool:
    user32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.2)
    return not user32.IsIconic(hwnd)


def request_close(hwnd: int) -> bool:
    """Ask the window to close, exactly like its X button (never a force-kill)."""
    return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def exists(hwnd: int) -> bool:
    return bool(user32 and user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd))


def spoken_list(windows: list[WindowInfo], limit: int = 10) -> str:
    if not windows:
        return "No windows are open."
    names = [w.spoken + (" (minimized)" if w.minimized else "") for w in windows[:limit]]
    more = f", and {len(windows) - limit} more" if len(windows) > limit else ""
    n = len(windows)
    return (f"{n} window{'s are' if n != 1 else ' is'} open: "
            + "; ".join(f"{i}, {nm}" for i, nm in enumerate(names, 1)) + more + ".")
