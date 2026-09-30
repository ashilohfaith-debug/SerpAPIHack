"""Normalise a recognised utterance before grammar matching.

Speech recognisers return text the way people talk: capitalised, punctuated, with
fillers and politeness ("Um, can you open Chrome for me, please?"). The grammar
matches on a canonical form ("open chrome") so natural phrasing works without an
LLM. Dictated payloads (text to type, notes) are extracted from the RAW utterance so
their capitalisation and words are preserved.
"""

from __future__ import annotations

import re

_FILLER = r"(?:um+|uh+|er+|erm|hmm+|ah+|oh|so|well|okay|ok|hey|hi|hello|yo|now|just|please|kindly)"
_VERBS = (r"open|switch|type|read|find|search|write|close|play|go|click|save|set|take|"
          r"remind|turn|check|start|launch|show|tell|select|copy|paste|press|minimize|"
          r"maximize|mute|unmute|increase|decrease|call|send|look")
_ASK = (r"(?:can|could|would|will|won't) (?:you|u)(?: please)?|"
        r"i (?:want|need|would like|'d like|wanna) (?:you )?(?:to )?|"
        rf"i'd like (?:you )?to|help me(?: to)?(?= (?:{_VERBS})\b)|let's|lets|go ahead and|"
        r"try to|please")
_LEADING = re.compile(rf"^(?:(?:{_FILLER})\b[\s,]*|(?:{_ASK})\b[\s,]*)+", re.IGNORECASE)
_TRAILING = re.compile(r"(?:[\s,]+(?:please|for me|right now|now|thanks|thank you|okay|ok|"
                       r"quickly|real quick))+$", re.IGNORECASE)
_EDGE_PUNCT = re.compile(r"^[\s\"'“”‘’.,!?;:()-]+|[\s\"'“”‘’.,!?;:()]+$")


def normalize(text: str, strip_trailing: bool = True) -> str:
    """Lower-case canonical form for matching. Keeps characters that carry meaning
    for commands: digits, decimal points, %, arithmetic signs, and dots in domains.
    ``strip_trailing=False`` keeps trailing words ("type thank you" must keep them)."""
    t = (text or "").strip()
    if not t:
        return ""
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.lower()
    t = _EDGE_PUNCT.sub("", t)
    # commas / semicolons inside the sentence are pauses, not meaning — except a
    # thousands separator between digits ("1,200")
    t = re.sub(r"\s*(?:(?<!\d),|,(?!\d)|;)\s*", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    prev = None
    while prev != t:            # strip stacked fillers: "um so can you please ..."
        prev = t
        t = _LEADING.sub("", t).strip()
        if strip_trailing:
            t = _TRAILING.sub("", t).strip()
        t = _EDGE_PUNCT.sub("", t)
    return t


def payload_after(raw: str, verbs: str) -> str | None:
    """Return the raw text after the first command verb (case preserved). Only the
    recogniser's trailing full stop is removed — dictated words are kept verbatim.
    ``verbs`` is a regex alternation."""
    m = re.search(rf"\b(?:{verbs})\b[\s:,]*(.+)$", raw.strip(), re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    out = m.group(1).strip()
    out = re.sub(r"[.]+$", "", out).strip()
    return out or None


_SPOKEN_PUNCT = [
    (r"\s*\bnew paragraph\b\s*", "\n\n"),
    (r"\s*\b(?:new line|next line|line break)\b\s*", "\n"),
    (r"\s*\b(?:full stop|period)\b", "."),
    (r"\s*\bcomma\b", ","),
    (r"\s*\bquestion mark\b", "?"),
    (r"\s*\b(?:exclamation mark|exclamation point)\b", "!"),
    (r"\s*\bcolon\b", ":"),
    (r"\s*\bsemicolon\b", ";"),
    (r"\s*\b(?:open bracket|open parenthesis)\b\s*", " ("),
    (r"\s*\b(?:close bracket|close parenthesis)\b", ")"),
    (r"\s*\bhyphen\b\s*", "-"),
    (r"\bat the rate\b", "@"),
]


def apply_spoken_punctuation(text: str) -> str:
    """Turn dictated punctuation words into symbols: 'hello comma how are you
    question mark' -> 'hello, how are you?'."""
    out = text
    for pat, rep in _SPOKEN_PUNCT:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    out = re.sub(r"[ \t]+([,.?!:;)])", r"\1", out)
    return out


def clean_dictation_homophones(text: str) -> str:
    """Correct common homophone recognition slips in notes and dictated tasks.
    E.g., 'by milk' -> 'buy milk', 'By Milk' -> 'buy milk'."""
    if not text:
        return ""
    t = text
    # Fix "by/bye <grocery/item>" -> "buy <item>"
    t = re.sub(
        r"\b(?:by|bye)\s+(milk|eggs?|bread|groceries|food|coffee|tea|fruits?|butter|cheese|water)\b",
        r"buy \1",
        t,
        flags=re.IGNORECASE,
    )
    # If the note starts with "by/bye" followed by a word, convert to "buy"
    t = re.sub(r"^(?:by|bye)\s+([a-zA-Z]+)", r"buy \1", t, flags=re.IGNORECASE)
    # Lowercase capitalized common items when preceded by buy
    t = re.sub(r"\bbuy\s+([A-Z][a-z]+)\b", lambda m: f"buy {m.group(1).lower()}", t)
    return t
