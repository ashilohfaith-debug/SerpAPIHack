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


def onboarding_script(
    wake_word: str = "relay", first_run: bool = True, talk_key: str = "Control Alt Space"
) -> list[str]:
    """The lines RELAY speaks to introduce itself. Kept short and concrete: a first
    run explains everything once; later starts are a one-line 'ready'."""
    running, name = screen_reader_running()
    if not first_run:
        lines = [f"Relay is ready. Press {talk_key}, or say {wake_word}, to talk to me."]
        if running:
            lines.append(f"{name} is running too; I'll stay out of its way.")
        return lines
    lines = [
        "Hello, I'm Relay. I help you use this computer by voice.",
        f"To talk to me, press {talk_key} from anywhere — you'll hear a short chirp — "
        f"then speak. Or just say {wake_word}, then your request.",
        "You can ask me things like: what time is it, open WhatsApp, search for today's "
        "news, read the page, take a note, or what's on my screen. I'll tell you before I "
        "do anything, and tell you what changed.",
        "Say stop to interrupt me, cancel to stop a task, or emergency stop to halt "
        "everything at once. Say help at any time to hear more.",
        "To close me, say quit Relay, or press Control Alt R again. If you wear "
        "headphones, I'll use them, and you can interrupt me just by talking.",
    ]
    if running:
        lines.append(coexistence_advice(name))
    lines.append("What would you like to do?")
    return lines
