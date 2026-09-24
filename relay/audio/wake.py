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

_LEAD = re.compile(r"^(hey|ok|okay|hi|yo)\s+", re.IGNORECASE)


def detect_wake(text: str) -> tuple[bool, str]:
    """Return (detected, remaining_command). Strips the wake word + a leading
    'hey/ok' so 'hey relay, open notepad' -> (True, 'open notepad')."""
    low = " " + text.lower().strip() + " "
    for v in _WAKE_VARIANTS:
        idx = low.find(" " + v + " ")
        if idx == -1 and low.strip() == v:
            return True, ""
        if idx != -1:
            after = low[idx + len(v) + 1:].strip()
            return True, after.lstrip(",. ").strip()
    # also catch the bare word possibly with trailing punctuation
    stripped = _LEAD.sub("", text.strip().lower())
    if stripped.split(" ", 1)[0].strip(",.!?") == WAKE_WORD:
        rest = stripped.split(" ", 1)[1].strip() if " " in stripped else ""
        return True, rest
    return False, ""


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
