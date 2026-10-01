"""Comprehensive Text Editing Engine for voice-controlled navigation and document editing.

Implements Points 30–37:
- Spoken selection by word, line, paragraph, document, or range.
- Cursor navigation by character, word, sentence, line, paragraph, and document bounds.
- Text transformations: replace, correct, delete, duplicate, capitalize, uppercase, lowercase.
- Document structure: headings, lists, indent, outdent, links.
- Inspection: read around cursor, word count, reading changes.
"""

from __future__ import annotations

import time
from typing import Any


class TextEditor:
    """Provides high-level voice-driven text editing and cursor control primitives."""

    def __init__(self, executor: Any, worker: Any = None) -> None:
        self.executor = executor
        self.worker = worker

    def select(self, unit: str, count: int = 1, direction: str = "next") -> tuple[bool, str]:
        """Select text by structural unit."""
        unit = unit.lower().strip()
        count = max(1, min(count, 50))
        if unit in ("all", "everything", "document", "entire document"):
            self.executor.hotkey("ctrl", "a")
            return True, "Selected all text."

        if unit == "word":
            if direction in ("prev", "previous", "back", "left"):
                for _ in range(count):
                    self.executor.hotkey("ctrl", "shift", "left")
                return True, f"Selected previous {count} word{'s' if count > 1 else ''}."
            else:
                for _ in range(count):
                    self.executor.hotkey("ctrl", "shift", "right")
                return True, f"Selected next {count} word{'s' if count > 1 else ''}."

        if unit == "line":
            self.executor.press("home")
            self.executor.hotkey("shift", "end")
            return True, "Selected current line."

        if unit == "paragraph":
            if direction in ("prev", "previous", "back", "up"):
                for _ in range(count):
                    self.executor.hotkey("ctrl", "shift", "up")
                return True, f"Selected previous {count} paragraph{'s' if count > 1 else ''}."
            else:
                for _ in range(count):
                    self.executor.hotkey("ctrl", "shift", "down")
                return True, f"Selected next {count} paragraph{'s' if count > 1 else ''}."

        if unit in ("to start of line", "to beginning of line"):
            self.executor.hotkey("shift", "home")
            return True, "Selected to beginning of line."

        if unit == "to end of line":
            self.executor.hotkey("shift", "end")
            return True, "Selected to end of line."

        if unit in ("to top", "to beginning of document"):
            self.executor.hotkey("ctrl", "shift", "home")
            return True, "Selected to top of document."

        if unit in ("to bottom", "to end of document"):
            self.executor.hotkey("ctrl", "shift", "end")
            return True, "Selected to end of document."

        return False, f"Unknown selection unit: {unit}."

    def move_cursor(self, unit: str, count: int = 1, direction: str = "forward") -> tuple[bool, str]:
        """Navigate cursor by character, word, line, paragraph, or boundary."""
        unit = unit.lower().strip()
        count = max(1, min(count, 50))
        is_back = direction in ("back", "prev", "previous", "left", "up")

        if unit in ("character", "char", "letter"):
            key = "left" if is_back else "right"
            self.executor.press(key, count=count)
            return True, f"Moved {count} character{'s' if count > 1 else ''} {'left' if is_back else 'right'}."

        if unit == "word":
            key = "left" if is_back else "right"
            for _ in range(count):
                self.executor.hotkey("ctrl", key)
            return True, f"Moved {count} word{'s' if count > 1 else ''} {'back' if is_back else 'forward'}."

        if unit == "line":
            key = "up" if is_back else "down"
            self.executor.press(key, count=count)
            return True, f"Moved {count} line{'s' if count > 1 else ''} {'up' if is_back else 'down'}."

        if unit == "paragraph":
            key = "up" if is_back else "down"
            for _ in range(count):
                self.executor.hotkey("ctrl", key)
            return True, f"Moved {count} paragraph{'s' if count > 1 else ''} {'up' if is_back else 'down'}."

        if unit in ("start of line", "beginning of line"):
            self.executor.press("home")
            return True, "Moved to start of line."

        if unit in ("end of line",):
            self.executor.press("end")
            return True, "Moved to end of line."

        if unit in ("top", "start of document", "top of document", "beginning of document"):
            self.executor.hotkey("ctrl", "home")
            return True, "Moved to top of document."

        if unit in ("bottom", "end of document", "bottom of document"):
            self.executor.hotkey("ctrl", "end")
            return True, "Moved to end of document."

        if unit in ("page",):
            key = "pageup" if is_back else "pagedown"
            self.executor.press(key, count=count)
            return True, f"Page {'up' if is_back else 'down'}."

        return False, f"Unknown navigation unit: {unit}."

    def delete_unit(self, unit: str, count: int = 1) -> tuple[bool, str]:
        """Delete word, line, or character."""
        unit = unit.lower().strip()
        count = max(1, min(count, 20))
        if unit in ("word", "previous word", "last word"):
            for _ in range(count):
                self.executor.hotkey("ctrl", "backspace")
            return True, f"Deleted {count} word{'s' if count > 1 else ''}."

        if unit in ("next word",):
            for _ in range(count):
                self.executor.hotkey("ctrl", "delete")
            return True, f"Deleted next {count} word{'s' if count > 1 else ''}."

        if unit in ("line", "current line"):
            self.executor.press("home")
            self.executor.hotkey("shift", "end")
            self.executor.press("backspace")
            self.executor.press("delete")
            return True, "Deleted current line."

        if unit in ("char", "character", "letter"):
            self.executor.press("backspace", count=count)
            return True, f"Deleted {count} character{'s' if count > 1 else ''}."

        return False, f"Unknown delete unit: {unit}."

    def duplicate_line(self) -> tuple[bool, str]:
        """Duplicate current line."""
        self.executor.press("home")
        self.executor.hotkey("shift", "end")
        self.executor.hotkey("ctrl", "c")
        self.executor.press("end")
        self.executor.press("enter")
        self.executor.hotkey("ctrl", "v")
        return True, "Duplicated current line."

    def change_case(self, mode: str) -> tuple[bool, str]:
        """Change case of selected text or word before cursor."""
        # Try copying selection
        import pyperclip

        old_clip = pyperclip.paste()
        self.executor.hotkey("ctrl", "c")
        time.sleep(0.1)
        sel = pyperclip.paste()
        if not sel or sel == old_clip:
            # If nothing selected, select the previous word
            self.executor.hotkey("ctrl", "shift", "left")
            time.sleep(0.05)
            self.executor.hotkey("ctrl", "c")
            time.sleep(0.1)
            sel = pyperclip.paste()

        if not sel or sel == old_clip:
            return False, "No text selected to change case."

        if mode == "capitalize":
            new_text = sel.capitalize()
        elif mode == "uppercase":
            new_text = sel.upper()
        elif mode == "lowercase":
            new_text = sel.lower()
        else:
            return False, f"Unknown case mode: {mode}."

        pyperclip.copy(new_text)
        self.executor.hotkey("ctrl", "v")
        return True, f"Converted to {mode}."

    def format_structure(self, style: str) -> tuple[bool, str]:
        """Apply structural formatting (headings, lists, indents, links)."""
        style = style.lower().strip()
        if style in ("heading 1", "h1"):
            self.executor.hotkey("ctrl", "alt", "1")
            return True, "Applied Heading 1."
        if style in ("heading 2", "h2"):
            self.executor.hotkey("ctrl", "alt", "2")
            return True, "Applied Heading 2."
        if style in ("heading 3", "h3"):
            self.executor.hotkey("ctrl", "alt", "3")
            return True, "Applied Heading 3."
        if style in ("bullet list", "bullet", "bullets"):
            self.executor.hotkey("ctrl", "shift", "l")
            return True, "Toggled bullet list."
        if style in ("indent", "increase indent"):
            self.executor.press("tab")
            return True, "Indented."
        if style in ("outdent", "decrease indent"):
            self.executor.hotkey("shift", "tab")
            return True, "Decreased indent."
        if style in ("link", "insert link"):
            self.executor.hotkey("ctrl", "k")
            return True, "Opened insert link dialog."
        return False, f"Unknown structural style: {style}."

    def word_count(self) -> str:
        """Count words in selection or document."""
        import pyperclip

        old = pyperclip.paste()
        # Try copying selection first
        self.executor.hotkey("ctrl", "c")
        time.sleep(0.1)
        text = pyperclip.paste()
        if text and text != old:
            words = len(text.split())
            chars = len(text)
            return f"Selection: {words} words, {chars} characters."

        # Select all and copy to count whole document, then restore
        self.executor.hotkey("ctrl", "a")
        time.sleep(0.1)
        self.executor.hotkey("ctrl", "c")
        time.sleep(0.1)
        text = pyperclip.paste()
        self.executor.press("right")  # deselect
        if text:
            words = len(text.split())
            chars = len(text)
            lines = len(text.splitlines())
            return f"Document: {words} words, {chars} characters across {lines} lines."
        return "Could not determine word count."

    def read_around_cursor(self) -> str:
        """Read the line around the current cursor."""
        import pyperclip

        old = pyperclip.paste()
        self.executor.press("home")
        self.executor.hotkey("shift", "end")
        time.sleep(0.1)
        self.executor.hotkey("ctrl", "c")
        time.sleep(0.1)
        line = pyperclip.paste()
        self.executor.press("end")  # restore cursor to end of line
        if line and line != old:
            return f"Current line: {line.strip()}."
        return "No text on current line."
