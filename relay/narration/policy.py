"""Narration policy — how much to say, and what to prioritise.

Four modes (spec §9):
  quick     essentials only (the default) — actions + task-relevant changes, briefly
  detailed  fuller descriptions, including the available controls
  guided    detailed + a next-step hint, for unfamiliar apps
  quiet     only critical errors, confirmations, and things you explicitly asked for

Announcement priority orders what matters when several things happen: critical
errors first, then required confirmations, then task changes, focus, requested
content, and background last. RELAY's OWN actions are always announced (the
transparency contract); modes tune the surrounding description and whether
background changes are spoken.
"""

from __future__ import annotations

from relay.perception.semantic import ScreenSnapshot

QUICK, DETAILED, GUIDED, QUIET = "quick", "detailed", "guided", "quiet"
MODES = (QUICK, DETAILED, GUIDED, QUIET)


class Priority:
    CRITICAL = 0  # errors that block the user
    CONFIRMATION = 1  # a confirmation is required
    TASK = 2  # a change relevant to the current task
    FOCUS = 3  # focus moved
    REQUESTED = 4  # the user asked for this
    BACKGROUND = 5  # unrelated background activity


def should_speak(priority: int, mode: str) -> bool:
    if mode == QUIET:
        return priority in (Priority.CRITICAL, Priority.CONFIRMATION, Priority.REQUESTED)
    if mode == QUICK:
        return priority <= Priority.REQUESTED  # everything except pure background
    return True  # detailed / guided: say it all


def describe(snap: ScreenSnapshot | None, mode: str) -> str:
    """Describe the screen at the requested verbosity."""
    if snap is None:
        return "I can't read the screen right now."
    if not snap.uia_available:
        return snap.summary()
    text = snap.summary()
    if mode in (DETAILED, GUIDED):
        names = [f"{e.role} {e.name!r}" for e in snap.elements if e.name][:8]
        if names:
            text += " Controls include: " + ", ".join(names) + "."
    if mode == GUIDED and snap.dialogs:
        d = snap.dialogs[0]
        if d.buttons:
            text += f" To respond, you can choose: {', '.join(d.buttons)}."
    return text


def spell(text: str) -> str:
    """Spell out text, letter by letter, for unambiguous reading (names, codes)."""
    if not text:
        return "There's nothing to spell."
    out = []
    for ch in text.strip():
        if ch == " ":
            out.append("space")
        else:
            out.append(ch.upper())
    return ", ".join(out)
