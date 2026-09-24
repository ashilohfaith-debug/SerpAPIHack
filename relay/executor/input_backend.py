"""Keyboard/mouse input injection, behind an interface.

The real backend uses pyautogui (and the clipboard for arbitrary text, which is far
more reliable than per-key typing). It is injectable so the executor's logic can be
unit-tested headlessly WITHOUT firing real keystrokes or clicks at whatever window
happens to be focused — important both for test safety and CI.
"""

from __future__ import annotations

import time
from typing import Protocol


class InputBackend(Protocol):
    def type_text(self, text: str) -> None: ...
    def press(self, key: str) -> None: ...
    def hotkey(self, *keys: str) -> None: ...
    def click(self, x: int, y: int) -> None: ...


class PyAutoGuiBackend:
    def type_text(self, text: str) -> None:
        import pyautogui
        import pyperclip
        try:
            backup = pyperclip.paste()
        except Exception:
            backup = None
        pyperclip.copy(text)
        time.sleep(0.03)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.05)
        if backup is not None:
            try:
                pyperclip.copy(backup)
            except Exception:
                pass

    def press(self, key: str) -> None:
        import pyautogui
        pyautogui.press(key)

    def hotkey(self, *keys: str) -> None:
        import pyautogui
        pyautogui.hotkey(*keys)

    def click(self, x: int, y: int) -> None:
        import pyautogui
        pyautogui.click(x, y)


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
