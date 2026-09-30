"""Keyboard/mouse input injection, behind an interface.

The real backend talks to Windows directly with SendInput (no third-party input
library — the popular one pulls in GPL-licensed dependencies we don't need), and uses
the clipboard for arbitrary text, which is far more reliable than per-key typing and
works for any language or symbol. It is injectable so the executor's logic can be
unit-tested headlessly WITHOUT firing real keystrokes or clicks at whatever window
happens to be focused — important both for test safety and CI.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Protocol


class InputBackend(Protocol):
    def type_text(self, text: str) -> None: ...
    def press(self, key: str) -> None: ...
    def hotkey(self, *keys: str) -> None: ...
    def click(self, x: int, y: int) -> None: ...


# ---- Win32 SendInput -------------------------------------------------------------
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


VK = {
    "ctrl": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,
    "winleft": 0x5B,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "capslock": 0x14,
    "printscreen": 0x2C,
    "apps": 0x5D,
    "=": 0xBB,
    "+": 0xBB,
    "-": 0xBD,
    ".": 0xBE,
    ",": 0xBC,
    "/": 0xBF,
    ";": 0xBA,
    "playpause": 0xB3,
    "nexttrack": 0xB0,
    "prevtrack": 0xB1,
    "stop": 0xB2,
    "volumemute": 0xAD,
    "volumedown": 0xAE,
    "volumeup": 0xAF,
    "browserback": 0xA6,
    "browserforward": 0xA7,
}
VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})
VK.update({chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)})  # 'a' -> 0x41
VK.update({str(d): 0x30 + d for d in range(10)})
# keys Windows expects with the "extended" flag (arrows, nav cluster, Windows key, media)
_EXTENDED = {
    0x21,
    0x22,
    0x23,
    0x24,
    0x25,
    0x26,
    0x27,
    0x28,
    0x2D,
    0x2E,
    0x5B,
    0x5D,
    0xA6,
    0xA7,
    0xAD,
    0xAE,
    0xAF,
    0xB0,
    0xB1,
    0xB2,
    0xB3,
}


def vk_for(key: str) -> int:
    k = key.lower()
    if k not in VK:
        raise ValueError(f"unknown key {key!r}")
    return VK[k]


def _key_input(vk: int, up: bool) -> INPUT:
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0) if hasattr(ctypes, "windll") else 0
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))


def _send(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = ctypes.windll.user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(
            "Windows blocked the key press (the window in front may be running as administrator)"
        )


class WindowsInputBackend:
    """Real keyboard/mouse input via Win32 SendInput."""

    def type_text(self, text: str) -> None:
        import pyperclip

        try:
            backup = pyperclip.paste()
        except Exception:
            backup = None
        pyperclip.copy(text)
        time.sleep(0.03)
        self.hotkey("ctrl", "v")
        time.sleep(0.05)
        if backup is not None:
            try:
                pyperclip.copy(backup)
            except Exception:
                pass

    def press(self, key: str) -> None:
        vk = vk_for(key)
        _send([_key_input(vk, False), _key_input(vk, True)])

    def hotkey(self, *keys: str) -> None:
        vks = [vk_for(k) for k in keys]
        _send([_key_input(v, False) for v in vks] + [_key_input(v, True) for v in reversed(vks)])

    def click(self, x: int, y: int) -> None:
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        down = INPUT(
            type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0))
        )
        up = INPUT(
            type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0))
        )
        _send([down, up])


# Backwards-compatible name used by earlier code and docs.
PyAutoGuiBackend = WindowsInputBackend


class RecordingBackend:
    """Test backend: records calls instead of touching the OS."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def type_text(self, text: str) -> None:
        self.calls.append(("type_text", text))

    def press(self, key: str) -> None:
        self.calls.append(("press", key))

    def hotkey(self, *keys: str) -> None:
        self.calls.append(("hotkey", keys))

    def click(self, x: int, y: int) -> None:
        self.calls.append(("click", x, y))
