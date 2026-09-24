"""Semantic screen model — the data structures for L1 live-screen memory.

A ScreenSnapshot is the task-relevant, in-RAM representation of the current
interface at a point in time: the foreground app/window, the focused element, the
interactive controls with their roles/states/available actions, any dialogs, and
the current selection. It carries an ``observation_version`` so a later action can
check that a referenced element is still from the current observation before acting
(stale references are re-observed, never blindly reused). Pure dataclasses — no UIA
here, so this is unit-testable without Windows.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class UIElement:
    uid: int                    # stable index within THIS snapshot only
    name: str
    role: str                   # UIA ControlTypeName without the "Control" suffix
    bbox: tuple[int, int, int, int]  # (left, top, right, bottom), physical px
    value: str = ""             # ValuePattern/TextPattern value, if any (never a secret)
    actions: tuple[str, ...] = ()    # available high-level actions: invoke/set_value/toggle/…
    states: dict = field(default_factory=dict)  # enabled/offscreen/focused/selected/toggled
    window_title: str = ""
    provenance: str = "uia"     # "uia" | "ocr" (ocr is inferred, lower trust)

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bbox
        return ((left + right) // 2, (top + bottom) // 2)

    def to_dict(self) -> dict:
        return {"uid": self.uid, "name": self.name, "role": self.role,
                "bbox": list(self.bbox), "value": self.value,
                "actions": list(self.actions), "states": self.states,
                "window_title": self.window_title, "provenance": self.provenance}


@dataclass(frozen=True)
class Dialog:
    title: str
    buttons: tuple[str, ...] = ()


@dataclass
class ScreenSnapshot:
    observation_version: int
    foreground_app: str = ""
    foreground_title: str = ""
    focus: UIElement | None = None
    elements: list[UIElement] = field(default_factory=list)
    dialogs: list[Dialog] = field(default_factory=list)
    selection: str = ""
    ts: float = field(default_factory=time.time)
    # True when UIA gave nothing useful (candidate for OCR fallback). Honesty:
    # callers must not claim to "see" an element that was never observed.
    uia_available: bool = True

    def fingerprint(self) -> str:
        """Stable hash of the meaningful structure (element identity + focus +
        foreground), independent of observation_version, for change detection."""
        stable = {
            "fg": self.foreground_title,
            "focus": (self.focus.name, self.focus.role) if self.focus else None,
            "els": sorted((e.name, e.role, e.bbox) for e in self.elements),
            "dlg": sorted(d.title for d in self.dialogs),
        }
        return hashlib.md5(json.dumps(stable, default=str).encode()).hexdigest()

    def by_uid(self, uid: int) -> UIElement | None:
        for e in self.elements:
            if e.uid == uid:
                return e
        return None

    def find(self, text: str) -> list[UIElement]:
        """Case-insensitive name match (exact first, then substring), smallest
        (most specific) first. Used by reference resolution in P6."""
        t = text.strip().lower()
        if not t:
            return []
        exact = [e for e in self.elements if e.name.strip().lower() == t]
        if exact:
            return exact
        subs = [e for e in self.elements if t in e.name.strip().lower()]
        subs.sort(key=lambda e: (e.bbox[2] - e.bbox[0]) * (e.bbox[3] - e.bbox[1]))
        return subs

    def summary(self) -> str:
        """Short human/narration-friendly description (no element dump)."""
        if not self.uia_available:
            app = self.foreground_app or "An application"
            return f"{app} is open, but I can't read its controls."
        parts = [f"{self.foreground_app or 'An application'}"]
        if self.foreground_title and self.foreground_title != self.foreground_app:
            parts.append(f"window '{self.foreground_title}'")
        if self.dialogs:
            parts.append(f"{len(self.dialogs)} dialog(s)")
        if self.focus and self.focus.name:
            parts.append(f"focus on {self.focus.role} '{self.focus.name}'")
        n = len(self.elements)
        parts.append(f"{n} control(s)")
        return ", ".join(parts) + "."
