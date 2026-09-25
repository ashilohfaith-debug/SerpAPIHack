"""Wake-word detection and voice command semantics.

Wake word is "relay". Detection runs on the STT transcript of a short VAD segment
(a dedicated audio wake model is a later optimisation); push-to-talk is always
available as a fallback and never depends on recognition working. Common mis-hears
of "relay" are matched so the wake word is forgiving without being trigger-happy.

Also defines the fixed control-command semantics (spec §9): stop talking / pause /
continue / cancel task / emergency stop — matched deterministically so they work
with no LLM.
"""

from __future__ import annotations

import re

WAKE_WORD = "relay"
_WAKE_VARIANTS = (
    "relay", "relai", "relee", "rely", "re lay", "re-lay", "raley", "rilay",
    "hey relay", "ok relay", "hi relay",
)

_LEAD = re.compile(r"^(?:(?:hey|ok|okay|hi|yo|um+|uh+|so|oh)[\s,.!]+)+", re.IGNORECASE)
_WAKE_RE = re.compile(
    r"^(?:" + "|".join(re.escape(v) for v in sorted(_WAKE_VARIANTS, key=len, reverse=True))
    + r")(?=$|[\s,.!?:;])[\s,.!?:;]*", re.IGNORECASE)


def detect_wake(text: str) -> tuple[bool, str]:
    """Return (detected, remaining_command). The wake word must START the utterance
    (after an optional 'hey'/'ok'), so 'hey relay, open notepad' -> (True, 'open
    notepad') but ambient talk that merely mentions relay mid-sentence is ignored."""
    t = (text or "").strip().replace("’", "'")
    t = re.sub(r"^[\"'“”.,!?\s-]+", "", t)
    t = _LEAD.sub("", t)
    m = _WAKE_RE.match(t)
    if not m:
        return False, ""
    rest = t[m.end():].strip()
    rest = re.sub(r"^[,.!?:;\s]+", "", rest).strip()
    return True, rest


_NEAR_MISS_RE = re.compile(r"^(?:really|rally|relays|realy|reli|rilly)(?=$|[\s,.!?:;])"
                           r"[\s,.!?:;]*", re.IGNORECASE)


def detect_wake_near_miss(text: str) -> tuple[bool, str]:
    """Common mis-hearings of "Relay" ("Really, what time is it?"). Callers must only
    accept these when the rest is a recognised command, so "Really? That's great" said
    to someone else is still ignored."""
    t = (text or "").strip().replace("’", "'")
    t = _LEAD.sub("", re.sub(r"^[\"'“”.,!?\s-]+", "", t))
    m = _NEAR_MISS_RE.match(t)
    if not m:
        return False, ""
    return True, re.sub(r"^[,.!?:;\s]+", "", t[m.end():]).strip()


# Control commands -> canonical action. Order matters (emergency first).
class Command:
    EMERGENCY_STOP = "emergency_stop"
    STOP_TALKING = "stop_talking"
    PAUSE = "pause"
    CONTINUE = "continue"
    CANCEL_TASK = "cancel_task"
    REPEAT = "repeat"


_COMMAND_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (Command.EMERGENCY_STOP, ("emergency stop", "emergency", "abort everything", "halt")),
    (Command.CANCEL_TASK, ("cancel task", "cancel that", "cancel", "never mind", "nevermind")),
    (Command.STOP_TALKING, ("stop talking", "be quiet", "quiet", "stop", "shush")),
    (Command.PAUSE, ("pause", "wait", "hold on", "one moment")),
    (Command.CONTINUE, ("continue", "carry on", "go on", "resume", "keep going")),
    (Command.REPEAT, ("repeat that", "repeat", "say that again", "again")),
]


def match_command(text: str) -> str | None:
    """Deterministically match a control command, or None."""
    low = text.lower().strip().strip(".!?")
    padded = f" {low} "
    for canonical, phrases in _COMMAND_PATTERNS:
        for p in phrases:
            if low == p or f" {p} " in padded:
                return canonical
    return None
