"""Deterministic planner — turn one Intent into observable Steps.

No LLM. Most commands are a single step; the point of a Step is that it carries a
human description used to ANNOUNCE the action before it runs (transparency) and a
kind the runner knows how to execute and verify. Compound goals and richer
decomposition come later; Essential mode stays simple and predictable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from relay.intent.grammar import Intent, Kind


@dataclass
class Step:
    kind: str            # answer | open | switch | activate | type | save | press | scroll
    description: str     # spoken as "I'm going to <description>"
    payload: dict = field(default_factory=dict)


def plan(intent: Intent) -> tuple[list[Step], str | None]:
    """Return (steps, clarification). If clarification is not None, RELAY should ask
    it instead of acting."""
    k, s = intent.kind, intent.slots
    if k in (Kind.DESCRIBE_SCREEN, Kind.WHERE_AM_I, Kind.WHAT_CHANGED,
             Kind.LIST_OPTIONS, Kind.READ_FOCUS, Kind.HELP):
        return [Step("answer", k, {"answer_kind": k})], None
    if k == Kind.OPEN_APP:
        app = s["app"]
        return [Step("open", f"open {app}", {"app": app})], None
    if k == Kind.SWITCH_APP:
        app = s["app"]
        return [Step("switch", f"switch to {app}", {"app": app})], None
    if k == Kind.ACTIVATE:
        tgt = s.get("target", "that")
        return [Step("activate", f"activate {tgt}", s)], None
    if k == Kind.TYPE:
        return [Step("type", "type your text", {"text": s["text"]})], None
    if k == Kind.SAVE:
        return [Step("save", "save the file", {})], None
    if k == Kind.PRESS_KEY:
        return [Step("press", f"press {s['key']}", {"key": s["key"]})], None
    if k == Kind.GO_BACK:
        return [Step("press", "go back", {"key": "browserback"})], None
    if k == Kind.SCROLL:
        key = "pagedown" if s.get("direction") == "down" else "pageup"
        return [Step("scroll", f"scroll {s.get('direction', 'down')}", {"key": key})], None
    if k == Kind.CONTROL:
        return [], None  # control commands are handled by the session, not planned
    return [], (f"I didn't understand \"{intent.raw}\". You can say things like "
                "'open Notepad', 'what's on my screen', or 'click the second option'.")
