"""Deterministic intent parsing — no LLM.

Maps a spoken/typed utterance to a structured Intent with slots. This is the
Essential-mode understanding layer: a bounded grammar of the commands a blind user
actually needs, matched by patterns, so RELAY works fully offline. Anything it can't
map returns UNKNOWN, and the assistant asks rather than guessing.

Reference slots ("the second result", "that", "it") are extracted here and resolved
against live state later (references.py), so RELAY binds words to observed elements
rather than acting on a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from relay.audio.wake import match_command  # reuse control-command matcher

ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "last": -1,
}


class Kind:
    DESCRIBE_SCREEN = "describe_screen"
    WHERE_AM_I = "where_am_i"
    WHAT_CHANGED = "what_changed"
    LIST_OPTIONS = "list_options"
    READ_FOCUS = "read_focus"
    OPEN_APP = "open_app"
    ACTIVATE = "activate"
    TYPE = "type"
    PRESS_KEY = "press_key"
    SAVE = "save"
    GO_BACK = "go_back"
    SCROLL = "scroll"
    SWITCH_APP = "switch_app"
    HELP = "help"
    CONTROL = "control"     # stop/pause/continue/cancel/emergency/repeat
    UNKNOWN = "unknown"


@dataclass
class Intent:
    kind: str
    slots: dict = field(default_factory=dict)
    raw: str = ""


def _ordinal_in(text: str) -> int | None:
    for word, n in ORDINALS.items():
        if re.search(rf"\b{word}\b", text):
            return n
    m = re.search(r"\b(\d+)(?:st|nd|rd|th)?\b", text)
    return int(m.group(1)) if m else None


def parse(utterance: str) -> Intent:
    raw = utterance.strip()
    low = raw.lower().strip().strip(".!?")
    if not low:
        return Intent(Kind.UNKNOWN, raw=raw)

    # control commands take priority (stop/pause/continue/cancel/emergency/repeat)
    cmd = match_command(low)
    if cmd is not None:
        return Intent(Kind.CONTROL, {"command": cmd}, raw)

    # information / read intents
    if re.search(r"\b(what('?s| is)? (on|happening)|describe|read the screen)\b", low):
        return Intent(Kind.DESCRIBE_SCREEN, raw=raw)
    if re.search(r"\bwhere am i\b", low):
        return Intent(Kind.WHERE_AM_I, raw=raw)
    if re.search(r"\bwhat('?s| has)? changed|what('?s| is)? different\b", low):
        return Intent(Kind.WHAT_CHANGED, raw=raw)
    if re.search(r"\b(what|which)( are)?( my)? options|what can i (do|say)\b", low):
        return Intent(Kind.LIST_OPTIONS, raw=raw)
    if re.search(r"\b(read (this|it|that|the selection|the focus)|what('?s| is) selected)\b", low):
        return Intent(Kind.READ_FOCUS, raw=raw)
    if low in ("help", "what can you do"):
        return Intent(Kind.HELP, raw=raw)

    # actions
    m = re.match(r"(?:open|launch|start|run)\s+(?:the\s+)?(.+)", low)
    if m and "result" not in m.group(1) and "link" not in m.group(1):
        return Intent(Kind.OPEN_APP, {"app": m.group(1).strip()}, raw)
    m = re.match(r"(?:switch to|go to|focus)\s+(?:the\s+)?(.+)", low)
    if m:
        return Intent(Kind.SWITCH_APP, {"app": m.group(1).strip()}, raw)
    m = re.match(r"(?:type|write|enter|dictate)\s+(.+)", raw, re.IGNORECASE)
    if m:
        return Intent(Kind.TYPE, {"text": m.group(1).strip()}, raw)
    if re.search(r"\bsave\b", low):
        return Intent(Kind.SAVE, raw=raw)
    if re.search(r"\bgo back|back\b", low):
        return Intent(Kind.GO_BACK, raw=raw)
    m = re.search(r"\bscroll (up|down)\b", low)
    if m:
        return Intent(Kind.SCROLL, {"direction": m.group(1)}, raw)
    m = re.match(r"(?:press|hit|push)\s+(?:the\s+)?(\w+)", low)
    if m:
        return Intent(Kind.PRESS_KEY, {"key": m.group(1)}, raw)

    # activate a target (click/select/open the <ordinal>/<name>)
    m = re.match(r"(?:click|select|activate|choose|open|press)\s+(?:on\s+)?(?:the\s+)?(.+)", low)
    if m:
        target = m.group(1).strip()
        ordinal = _ordinal_in(target)
        slots = {"target": target}
        if ordinal is not None:
            slots["ordinal"] = ordinal
        return Intent(Kind.ACTIVATE, slots, raw)

    return Intent(Kind.UNKNOWN, raw=raw)
