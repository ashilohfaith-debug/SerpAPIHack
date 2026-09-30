"""Continuous reading with a cursor — the way a blind user reads a page or a PDF.

"Read the page" loads the text, splits it into paragraph-sized parts, and reads them
one after another ("say all"). The user stays in control the whole time:
  stop / pause      -> stops at the current part (position kept)
  continue          -> resumes from there
  next / previous   -> reads the next / previous part
  repeat            -> reads the current part again
Advancing is driven by the speech queue's completion callback, so reading stops
exactly where the user interrupted — nothing is skipped, nothing is read twice.
"""

from __future__ import annotations

import re
import threading
from typing import Callable

MAX_PART = 420  # characters per spoken part
MIN_PART = 60  # merge tiny lines (menus, labels) into readable parts


def split_parts(text: str) -> list[str]:
    """Paragraphs -> readable parts: long paragraphs split at sentence ends, runs of
    tiny lines merged, whitespace tidied."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+", " ", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    parts: list[str] = []
    buf = ""
    for p in paras:
        if len(p) > MAX_PART:
            if buf:
                parts.append(buf)
                buf = ""
            sentences = re.split(r"(?<=[.!?।])\s+", p)
            cur = ""
            for s in sentences:
                while len(s) > MAX_PART:  # a giant "sentence"
                    cut = s.rfind(" ", 0, MAX_PART)
                    cut = cut if cut > MAX_PART // 2 else MAX_PART
                    if cur:
                        parts.append(cur)
                        cur = ""
                    parts.append(s[:cut].strip())
                    s = s[cut:].strip()
                if len(cur) + len(s) + 1 > MAX_PART and cur:
                    parts.append(cur)
                    cur = s
                else:
                    cur = f"{cur} {s}".strip()
            if cur:
                parts.append(cur)
            continue
        if len(p) < MIN_PART:
            sep = ". " if buf and not re.search(r"[.!?:;,।]$", buf) else " "
            buf = f"{buf}{sep}{p}".strip() if buf else p
            if len(buf) >= MIN_PART * 2:
                parts.append(buf)
                buf = ""
            continue
        if buf:
            parts.append(buf)
            buf = ""
        parts.append(p)
    if buf:
        parts.append(buf)
    return [x for x in parts if x.strip()]


class Reader:
    def __init__(
        self,
        speak_part: Callable[[str, Callable[[bool], None] | None], None],
        say: Callable[[str], None],
        interrupt: Callable[[], None] | None = None,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> None:
        """``speak_part(text, on_done)`` queues one part and calls on_done(completed)
        when it finishes; ``say`` is for RELAY's own short announcements."""
        self._speak_part = speak_part
        self._say = say
        self._interrupt = interrupt or (lambda: None)
        self._on_event = on_event or (lambda kind, data: None)
        self.parts: list[str] = []
        self.title = ""
        self.pos = 0  # index of the part being / to be read
        self.reading = False  # say-all in progress
        self._gen = 0
        self._lock = threading.Lock()

    @property
    def has_content(self) -> bool:
        return bool(self.parts)

    def load(self, text: str, title: str = "") -> int:
        with self._lock:
            self._gen += 1
            self.parts = split_parts(text)
            self.title = title
            self.pos = 0
            self.reading = False
        return len(self.parts)

    # ---- say-all ----
    def read_all(self, from_pos: int | None = None, intro: bool = True) -> None:
        if not self.parts:
            self._say("There's nothing to read.")
            return
        with self._lock:
            self._gen += 1
            gen = self._gen
            if from_pos is not None:
                self.pos = max(0, min(from_pos, len(self.parts) - 1))
            self.reading = True
        if intro:
            n = len(self.parts)
            where = f"{self.title}. " if self.title else ""
            self._say(
                f"Reading {where}{n} part{'s' if n != 1 else ''}. Say stop to pause, next to skip."
            )
        self._on_event("reading.start", {"title": self.title, "parts": len(self.parts)})
        self._speak_current(gen)

    def _speak_current(self, gen: int) -> None:
        with self._lock:
            if gen != self._gen or not self.reading:
                return
            if self.pos >= len(self.parts):
                self.reading = False
                done = True
            else:
                done = False
                text = self.parts[self.pos]
                idx = self.pos
        if done:
            if len(self.parts) > 1:
                self._say("End of the text.")
            self._on_event("reading.end", {})
            return
        self._on_event("reading.part", {"index": idx + 1, "of": len(self.parts)})
        self._speak_part(text, lambda completed, g=gen, i=idx: self._after(g, i, completed))

    def _after(self, gen: int, idx: int, completed: bool) -> None:
        with self._lock:
            if gen != self._gen or not self.reading:
                return
            if not completed:  # interrupted: keep the position for "continue"
                self.reading = False
                return
            self.pos = idx + 1
        self._speak_current(gen)

    # ---- controls ----
    def stop(self) -> bool:
        """Pause reading (position kept). Returns True if it was reading."""
        with self._lock:
            was = self.reading
            self.reading = False
            self._gen += 1
        if was:
            self._interrupt()
        return was

    def resume(self) -> bool:
        if not self.parts:
            return False
        if self.pos >= len(self.parts):
            self._say("That was the end. Say read from the top to start again.")
            return True
        self.read_all(intro=False)
        return True

    def step(self, delta: int) -> None:
        """Read the next (+1) / previous (-1) part on its own."""
        if not self.parts:
            self._say("There's nothing to read yet. Say read the page first.")
            return
        with self._lock:
            self._gen += 1  # invalidate any say-all continuation
            new = self.pos + delta
            if new < 0:
                new = 0
                edge = "This is the beginning."
            elif new >= len(self.parts):
                new = len(self.parts) - 1
                edge = "That was the last part."
            else:
                edge = ""
            self.pos = new
            self.reading = False
            text = self.parts[new]
        self._interrupt()
        if edge:
            self._say(edge)
        self._on_event("reading.part", {"index": new + 1, "of": len(self.parts)})
        self._speak_part(text, None)

    def repeat(self) -> None:
        self.step(0)
