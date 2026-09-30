"""System-wide hotkeys (Win32 RegisterHotKey) — the talk key and the stop keys.

A blind user must be able to reach RELAY from any app without looking: press the talk
key, hear the listening chirp, speak. RegisterHotKey is the documented, hook-free way
to do this (no keyboard logging, no admin rights). Registration and the message loop
run on one dedicated thread, as Windows requires; callbacks are dispatched on short-
lived threads so a slow action never blocks the next key press. If another program
already owns a combination, registration fails and RELAY says so instead of silently
having no talk key.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

from relay.diagnostics import get_logger

log = get_logger("audio.hotkeys")

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

_MODS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
}
_VK = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "pause": 0x13,
    "period": 0xBE,
    "comma": 0xBC,
    "slash": 0xBF,
    "semicolon": 0xBA,
    "quote": 0xDE,
    "minus": 0xBD,
    "equals": 0xBB,
}
_VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})

SPOKEN_KEY = {
    "ctrl": "Control",
    "control": "Control",
    "alt": "Alt",
    "shift": "Shift",
    "win": "Windows",
    "windows": "Windows",
    "esc": "Escape",
    "space": "Space",
    "pageup": "Page Up",
    "pagedown": "Page Down",
}


def parse_combo(combo: str) -> tuple[int, int]:
    """'ctrl+alt+space' -> (modifiers, virtual-key). Raises ValueError if invalid."""
    parts = [p.strip().lower() for p in combo.replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    mods, key = 0, parts[-1]
    for p in parts[:-1]:
        if p not in _MODS:
            raise ValueError(f"unknown modifier {p!r}")
        mods |= _MODS[p]
    if key in _VK:
        vk = _VK[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"unknown key {key!r}")
    return mods, vk


def spoken_combo(combo: str) -> str:
    """'ctrl+alt+space' -> 'Control Alt Space' (how RELAY says it aloud)."""
    parts = [p.strip().lower() for p in combo.replace("-", "+").split("+") if p.strip()]
    return " ".join(SPOKEN_KEY.get(p, p.upper() if len(p) == 1 else p.capitalize()) for p in parts)


class HotkeyManager:
    def __init__(self) -> None:
        self._bindings: dict[int, tuple[str, Callable[[], None]]] = {}
        self._registered: dict[str, bool] = {}
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()

    def add(self, combo: str, callback: Callable[[], None]) -> None:
        if self._thread is not None:
            raise RuntimeError("add hotkeys before start()")
        parse_combo(combo)  # validate early
        self._bindings[len(self._bindings) + 1] = (combo, callback)

    def start(self, timeout: float = 3.0) -> dict[str, bool]:
        """Register all hotkeys; returns {combo: registered_ok}."""
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return dict(self._registered)

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        for hid, (combo, _cb) in self._bindings.items():
            mods, vk = parse_combo(combo)
            ok = bool(user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk))
            self._registered[combo] = ok
            if not ok:
                log.warning("hotkey %s is already in use by another program", combo)
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    binding = self._bindings.get(int(msg.wParam))
                    if binding is not None:
                        threading.Thread(
                            target=self._safe, args=(binding[1],), name="hotkey-action", daemon=True
                        ).start()
        finally:
            for hid in self._bindings:
                user32.UnregisterHotKey(None, hid)

    @staticmethod
    def _safe(cb: Callable[[], None]) -> None:
        try:
            cb()
        except Exception as e:
            log.warning("hotkey action failed: %s", e)

    def stop(self) -> None:
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
