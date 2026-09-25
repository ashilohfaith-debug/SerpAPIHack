"""Forgiving understanding for speech-recognition slips — still no LLM, still offline.

A small on-device recogniser mishears short words: "read my notes" comes back as
"Read by notes.", "what's the time" as "what's the tie". When the grammar can't parse
an utterance, it is compared with RELAY's fixed command phrases. A close match to a
read-only command (time, notes, reading) is used directly and RELAY says what it
understood; a close match to anything that changes the screen is only *offered*
("Did you mean close this tab? Say yes or no.") — a guess never acts on its own.
"""

from __future__ import annotations

import difflib
import re

from relay.intent.normalize import normalize

# (canonical phrase, safe_to_run_without_asking)
CANON: list[tuple[str, bool]] = [
    ("what time is it", True), ("what's the time", True), ("what is the time", True),
    ("what's the date", True), ("what day is it", True), ("how's my battery", True),
    ("battery status", True), ("how much battery do i have", True),
    ("am i connected to the internet", True), ("status", True), ("what's the volume", True),
    ("what's on my screen", True), ("where am i", True), ("what changed", True),
    ("what are my options", True), ("read the page", True), ("read this", True),
    ("read the title", True), ("read the clipboard", True), ("read the dialog", True),
    ("list the links", True), ("list the headings", True), ("read my notes", True),
    ("what are my reminders", True), ("what windows are open", True), ("help", True),
    ("what can you do", True), ("next paragraph", True), ("previous paragraph", True),
    ("spell that", True), ("repeat that", True), ("continue reading", True),
    ("speak faster", True), ("speak slower", True), ("what do you remember", True),
    ("show desktop", False), ("volume up", False), ("volume down", False), ("mute", False),
    ("unmute", False), ("play music", False), ("pause music", False), ("next track", False),
    ("previous track", False), ("select all", False), ("copy", False), ("paste", False),
    ("undo", False), ("redo", False), ("new tab", False), ("close tab", False),
    ("save", False), ("go back", False), ("scroll down", False), ("scroll up", False),
    ("start dictation", False), ("stop dictation", False), ("cancel my reminders", False),
    ("close this window", False), ("minimize this window", False),
    ("maximize this window", False), ("quit relay", False),
]
_WORD_FIXES = {"by": "my", "mai": "my", "nodes": "notes", "tie": "time", "tape": "type",
               "tap": "tab", "clothes": "close", "reed": "read", "red": "read",
               "rite": "write", "lynx": "links", "link": "links"}
THRESHOLD = 0.84


def closest(utterance: str) -> tuple[str, bool, float] | None:
    """(canonical phrase, safe, score) for a near miss, or None."""
    low = normalize(utterance)
    if not low or len(low) > 60:
        return None
    fixed = " ".join(_WORD_FIXES.get(w, w) for w in low.split())
    best = None
    for cand in {low, fixed}:
        for phrase, safe in CANON:
            if not 0.6 <= len(cand) / max(1, len(phrase)) <= 1.6:
                continue
            score = difflib.SequenceMatcher(None, cand, phrase).ratio()
            if best is None or score > best[2]:
                best = (phrase, safe, score)
    if best and best[2] >= THRESHOLD and not re.fullmatch(re.escape(best[0]), low):
        return best
    return None
