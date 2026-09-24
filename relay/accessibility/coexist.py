"""Screen-reader coexistence (NVDA / JAWS / Narrator).

RELAY is a standalone assistant, but many blind users already run a screen reader.
When one is active, RELAY must not fight it: it keeps its own command answers and
task narration (which the screen reader won't provide) but avoids re-reading raw
focus changes the reader already announces, and it never disables the reader or
steals its reserved shortcuts.

NOTE: this detection is built but UNVERIFIED — no screen reader is installed on the
development machine. Coexistence behaviour must be tested with NVDA before any
accessibility claim.
"""

from __future__ import annotations

_READERS = {
    "nvda.exe": "NVDA",
    "jfw.exe": "JAWS",
    "narrator.exe": "Narrator",
}


def screen_reader_running() -> tuple[bool, str]:
    """Return (running, name). Empty name when none detected."""
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            name = (p.info.get("name") or "").lower()
            if name in _READERS:
                return True, _READERS[name]
    except Exception:
        pass
    return False, ""


def coexistence_advice(reader_name: str) -> str:
    if not reader_name:
        return ""
    return (f"I can tell {reader_name} is running. I'll stay out of its way — "
            "I won't repeat what it already reads, and I won't take its shortcuts. "
            "Just talk to me for anything you want me to do or explain.")
