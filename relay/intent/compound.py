"""Several commands in one breath: "open Notepad, type hello and save it as notes".

A request is split into steps only where EVERY piece is itself a command RELAY
understands, so ordinary sentences are never cut up:

- "then", "and then", "after that" always separate steps;
- "and" or a comma separate steps when the next piece is a command — except after a
  command that takes free text (type, search, note, remind…): there only a clear
  follow-up ("save it as …", "press enter", "send it", "read the first result")
  splits, so "type salt and pepper" or "search for rock and roll" stay whole, and a
  sentence being typed can never turn into "close the window";
- "open Chrome, WhatsApp and Gmail" carries the verb over: three opens;
- a few natural shapes are rewritten: "open YouTube and play X" -> "play X on YouTube",
  "open X and read it" -> "read the file X", "go to downloads" -> "open my downloads".

Returns None when the request isn't a sequence (the normal path handles it).
"""

from __future__ import annotations

import re

from relay.intent.grammar import Kind, parse

_FREE_TEXT = {
    Kind.TYPE,
    Kind.WEB_SEARCH,
    Kind.YOUTUBE,
    Kind.SET_REMINDER,
    Kind.TAKE_NOTE,
    Kind.REMEMBER,
    Kind.ASK,
    Kind.SUMMARIZE,
    Kind.CALCULATE,
    Kind.EMAIL,
}
_STRONG = re.compile(
    r"\s*(?:,\s*)?\b(?:and then|then|after that|and after that|next)\b"
    r"\s*,?\s*",
    re.I,
)
_WEAK = re.compile(r"\s*,\s*(?:and\s+)?|\s+and\s+", re.I)
_FOLLOW_UP = re.compile(
    r"^(?:(?:type|write|enter|dictate|insert)\s+.+|save(?: it| the file| this| the document)?(?: as .+)?|press .+|hit enter|"
    r"send(?: (?:the|this|my)?\s*(?:email|mail|message|reply|text|it))?|"
    r"read (?:it|the page|the screen|the document|the text|all|this)(?: out| aloud| back| to me)?|"
    r"select all|copy(?: it| that| all)?|paste(?: it)?|"
    r"(?:open|click|read|play|go to) the (?:first|second|third|fourth|fifth|last|top) .+|"
    r"(?:go to|goto|open|click|tap|press)\s+(?:on\s+)?(?:the\s+)?[a-z0-9 _-]+|"
    r"play\s+.+)$",
    re.I,
)
_CARRY = re.compile(r"^(open|close|switch to|launch|start)\s", re.I)
# a piece that starts with a verb is its own (unknown) request, not another app name
_VERBISH = {
    "send",
    "play",
    "type",
    "write",
    "call",
    "search",
    "read",
    "find",
    "set",
    "turn",
    "make",
    "take",
    "remind",
    "go",
    "click",
    "press",
    "save",
    "copy",
    "paste",
    "delete",
    "move",
    "rename",
    "tell",
    "what",
    "how",
    "is",
    "are",
    "can",
    "please",
    "reply",
    "message",
    "text",
    "ask",
    "show",
    "check",
    "book",
    "buy",
    "order",
}
_READ_RESULT = re.compile(
    r"^read the (first|second|third|fourth|fifth|top|last) "
    r"(?:result|link|one|article)$",
    re.I,
)
_FOLDERS = (
    r"(?:my\s+|the\s+)?(desktop|documents|downloads|pictures|photos|music|videos)"
    r"(?:\s+folder)?"
)


def _kind(text: str) -> Kind:
    return parse(text).kind


def _rewrite(piece: str) -> str:
    p = piece.strip().strip(",.").strip()
    m = re.fullmatch(rf"(?:go to|goto|open up)\s+{_FOLDERS}", p, re.I)
    if m:
        return f"open my {m.group(1).lower()}"
    m = re.fullmatch(
        r"open(?:\s+up)?(?:\s+the)?(?:\s+a\s+new)?\s+(word|notepad|excel|calculator|chrome|edge)"
        r"(?:\s+(?:for\s+it|for\s+this|document|doc|window|file))?",
        p,
        re.I,
    )
    if m:
        return f"open {m.group(1).lower()}"
    m = re.fullmatch(
        r"(?:go to|goto|open|click)\s+(?:the\s+)?(?:youtube\s+)?shorts(?:\s+(?:in|on)\s+(?:yt|youtube))?",
        p,
        re.I,
    )
    if m:
        return "open youtube shorts"
    return p


def split_steps(text: str) -> list[str] | None:
    raw = (text or "").strip().rstrip(".!?")
    if not raw or not re.search(r"\band\b|,|\bthen\b|\bafter that\b", raw, re.I):
        return None
    # natural two-step shapes: open yt and go to shorts -> open youtube, open youtube shorts
    m = re.fullmatch(
        r"(?:open|go to)\s+(?:yt|youtube)\s*,?\s+and\s+(?:go to|open|click|watch)\s+(?:the\s+)?(?:youtube\s+)?shorts(?:\s+(?:in|on)\s+(?:yt|youtube))?",
        raw,
        re.I,
    )
    if m:
        return ["open youtube", "open youtube shorts"]
    # natural two-step shapes that are really one command
    m = re.fullmatch(
        r"(?:open|go to)\s+youtube\s*,?\s+and\s+(?:play|search for|search|find)"
        r"\s+(.+)",
        raw,
        re.I,
    )
    if m:
        return [f"play {m.group(1)} on youtube"]
    m = re.fullmatch(
        r"(?:open|find)\s+(?:my\s+|the\s+)?(.+?)\s*,?\s+and\s+read\s+it"
        r"(?:\s+(?:out|aloud|to me|out loud))?",
        raw,
        re.I,
    )
    if m and _kind("open " + m.group(1)) == Kind.OPEN_APP:
        return [f"read the file {m.group(1)}"]
    steps: list[str] = []
    for chunk in _STRONG.split(raw):
        chunk = chunk.strip(" ,")
        if not chunk:
            continue
        pieces = [x for x in _WEAK.split(chunk) if x and x.strip()]
        current = pieces[0]
        for nxt in pieces[1:]:
            ck = _kind(_rewrite(current))
            if ck in _FREE_TEXT:
                split = bool(_FOLLOW_UP.match(nxt.strip()))
            else:
                split = _kind(_rewrite(nxt)) != Kind.UNKNOWN
                if not split:  # "open Chrome, WhatsApp and Gmail"
                    verb = _CARRY.match(current)
                    first = (nxt.split() or [""])[0].lower()
                    if (
                        verb
                        and first not in _VERBISH
                        and len(nxt.split()) <= 4
                        and _kind(f"{verb.group(1)} {nxt}") != Kind.UNKNOWN
                    ):
                        nxt = f"{verb.group(1)} {nxt}"
                        split = True
            if split:
                steps.append(current)
                current = nxt
            else:
                current = f"{current} and {nxt}"
        steps.append(current)
    out: list[str] = []
    for s in (_rewrite(s) for s in steps if s.strip()):
        m = _READ_RESULT.match(s)  # "read the first result" = open + read
        out += [f"open the {m.group(1).lower()} result", "read the page"] if m else [s]
    steps = out
    if len(steps) < 2:
        return None
    if any(_kind(s) == Kind.UNKNOWN for s in steps):
        return None  # not all commands: not a sequence
    return steps
