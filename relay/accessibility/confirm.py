"""Accessible spoken confirmation for high-risk actions.

A bare "yes" is never enough for a high-risk action (spec §8). RELAY announces the
exact action, target and consequence, then requires an ACTION-SPECIFIC spoken phrase
(e.g. "confirm delete") — so an accidental "yeah" while chatting can't trigger a
destructive action. The most sensitive actions (purchase / install / security
settings) require a keyboard or Windows-auth confirmation instead of voice; RELAY
declines those by voice and explains why. A spoken confirmation phrase is used once
and never stored as a reusable credential.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class PendingConfirmation:
    phrase: str
    summary: str
    retry: Callable[[], object]
    keyboard_only: bool = False
    reprompts: int = 0


def confirmation_phrase(target_label: str = "", kind: str = "") -> str:
    """A short, action-specific phrase the user must say to confirm. Deterministic
    so RELAY can prompt it and match it exactly."""
    source = target_label or kind or "proceed"
    word = re.sub(r"[^a-z0-9 ]", "", source.lower()).strip().split()
    key = word[0] if word else "proceed"
    return f"confirm {key}"


_CANCEL = re.compile(r"\b(no|nope|cancel|stop|don'?t|never\s?mind|abort|forget it)\b", re.I)


def is_cancel(text: str) -> bool:
    return bool(_CANCEL.search(text or ""))
