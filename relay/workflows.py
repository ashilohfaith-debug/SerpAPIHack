"""Application capability matrix — what RELAY supports, and how.

RELAY drives apps through Windows UI Automation first, keyboard next, OCR/coords as
a last resort. How well that works depends on the app's accessibility. This matrix
records, honestly, which apps are supported and the technique that works, so RELAY
can tell the user the truth ("I can read this reliably" vs "this app doesn't expose
its controls well") instead of pretending. It is descriptive, not a promise: RELAY
still verifies every action at runtime.

Support levels:
  full      UIA exposes named, invokable controls — RELAY can read and act reliably
  keyboard  controls aren't reliably invokable via UIA; RELAY drives it by keyboard
  read      RELAY can read/describe it well; actions are limited or read-only here
  partial   works, but with known gaps (e.g. deep/dynamic web content)
  unsupported  RELAY cannot reliably operate it and will say so
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    app: str
    level: str
    technique: str
    notes: str


CAPABILITIES: dict[str, Capability] = {
    "notepad": Capability(
        "Notepad", "full", "UIA + keyboard",
        "Read/edit text, Save via Ctrl+S and the file dialog. Verified by file on disk."),
    "explorer": Capability(
        "File Explorer", "full", "UIA",
        "Read the current folder, focus items, open files. Renames/deletes need confirmation."),
    "dialogs": Capability(
        "Windows dialogs (#32770)", "full", "UIA",
        "Save/Open/message boxes are detected and their buttons read; type a filename + Enter."),
    "calculator": Capability(
        "Calculator", "keyboard", "keyboard",
        "UWP app: digits/operators are not invokable UIA buttons, so RELAY types them "
        "on the keyboard and reads the result display."),
    "wordpad": Capability(
        "WordPad", "full", "UIA + keyboard", "Similar to Notepad; richer formatting."),
    "settings": Capability(
        "Windows Settings", "read", "UIA",
        "Readable and navigable; changing security-relevant settings needs confirmation."),
    "chrome": Capability(
        "Chromium browsers (Chrome/Edge/Brave)", "partial", "UIA + keyboard",
        "Address bar, tabs, links and headings are reachable via UIA; deep/dynamic page "
        "content can be partial — RELAY falls back to keyboard nav and says when unsure."),
}


_ALIASES = {"msedge": "chrome", "edge": "chrome", "brave": "chrome",
            "calc": "calculator", "files": "explorer", "file explorer": "explorer",
            "write": "wordpad"}


def capability_for(app_key: str) -> Capability | None:
    a = app_key.lower().replace(".exe", "").strip()
    a = _ALIASES.get(a, a)
    for key, cap in CAPABILITIES.items():
        if key in a or a in key:
            return cap
    return None


def matrix_text() -> str:
    lines = ["RELAY supported applications (honest capability matrix):"]
    for cap in CAPABILITIES.values():
        lines.append(f"  - {cap.app}: {cap.level} ({cap.technique}). {cap.notes}")
    lines.append("Anything not listed: RELAY will read what it can and tell you plainly "
                 "when it cannot operate an app reliably.")
    return "\n".join(lines)


def spoken_summary() -> str:
    apps = [c.app for c in CAPABILITIES.values() if c.level in ("full", "keyboard")]
    return ("I can reliably operate " + ", ".join(apps) + ". "
            "I can read most other applications too, and I'll tell you plainly "
            "whenever I can't control one reliably.")
