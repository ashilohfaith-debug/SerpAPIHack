"""Spoken, voice-only onboarding.

A blind user must be able to start RELAY and understand it with no visual step. On
first run RELAY introduces itself, states how to talk to it and stop it, and (if a
screen reader is present) explains how it coexists. The "first run" flag is a small
file in the per-user data dir, so onboarding runs once but can be replayed on
request ("help" / "how do I use you").
"""

from __future__ import annotations

from relay.accessibility.coexist import coexistence_advice, screen_reader_running
from relay.config import user_data_dir


def _flag_path():
    return user_data_dir() / ".onboarded"


def is_first_run() -> bool:
    return not _flag_path().exists()


def mark_onboarded() -> None:
    try:
        _flag_path().write_text("1", encoding="utf-8")
    except OSError:
        pass


def onboarding_script(wake_word: str = "relay", first_run: bool = True) -> list[str]:
    """The lines RELAY speaks to introduce itself. Kept short and concrete."""
    lines = []
    if first_run:
        lines.append("Hello, I'm Relay. I help you use this computer by voice.")
    else:
        lines.append("Relay here.")
    lines.append(f"To get my attention, say {wake_word}, then tell me what you want. "
                 "You can also hold the talk key.")
    lines.append("Ask me things like: what's on my screen, open an app, click something, "
                 "type text, or save. I'll tell you before I do anything, and tell you "
                 "what changed.")
    lines.append("Say stop to interrupt me, cancel to stop a task, "
                 "or emergency stop to halt everything at once.")
    running, name = screen_reader_running()
    if running:
        lines.append(coexistence_advice(name))
    lines.append("What would you like to do?")
    return lines
