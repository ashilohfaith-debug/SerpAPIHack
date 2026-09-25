"""Free-form request -> one fixed RELAY command (Connected mode only).

The offline grammar understands a fixed set of phrasings. When it can't parse a
request ("can you get me the latest cricket score"), the Sarvam chat model is asked
to rewrite it as ONE command from RELAY's command list. Its answer is treated as
untrusted text: it must parse to a known, non-sensitive intent with the offline
grammar, it can never be a confirmation phrase, and it still passes through the same
permission engine and spoken confirmation as anything the user said directly. RELAY
tells the user how it understood the request before acting.
"""

from __future__ import annotations

import re

from relay.diagnostics import get_logger
from relay.intent.grammar import Kind, parse

log = get_logger("connected.nlu")

SYSTEM_PROMPT = """You turn a blind user's spoken request into exactly ONE command for \
RELAY, a Windows voice assistant. The request may be in English or translated from an \
Indian language. Reply with ONE line containing only the command, or UNKNOWN if nothing \
fits. Never add explanations.

Commands (fill in the parts in angle brackets):
open <app, website or folder>
switch to <app>
search the web for <query>
search youtube for <query>
what time is it
what's the date
battery status
am i connected to the internet
volume up | volume down | mute | unmute | set volume to <number> percent
play music | pause music | next track | previous track
what is <arithmetic, e.g. 25 times 4>
read the page | read the clipboard | list links | list headings
what's on my screen | where am i | what changed | read the title
take a note <text>
read my notes
remind me in <number> minutes to <text>
remind me at <time> to <text>
list reminders
type <text>
press <keys, e.g. control s>
select all | copy | paste | undo | save | save as <name>
click <button or link name>
click the <first|second|third> link
close this window | minimize this window | maximize this window
list windows | show desktop
find file <name>
open file <name>
speak faster | speak slower
help"""

_BLOCK = re.compile(r"^\s*(confirm|emergency|quit|exit|turn (on|off) connected|enable "
                    r"connected|go offline|delete my notes|clear my notes)\b", re.I)
_NEVER = {Kind.UNKNOWN, Kind.CONTROL, Kind.QUIT, Kind.CONNECTED, Kind.DELETE_NOTES,
          Kind.CLEAR_HISTORY, Kind.FORGET}


def validate(line: str) -> str | None:
    """Accept the model's line only if it is a single known, allowed command."""
    line = (line or "").strip().splitlines()[0].strip() if (line or "").strip() else ""
    line = line.strip("`\"' .")
    line = re.sub(r"^(?:command\s*:\s*)", "", line, flags=re.I)
    if not line or line.upper().startswith("UNKNOWN") or _BLOCK.match(line):
        return None
    intent = parse(line)
    if intent.kind in _NEVER:
        return None
    return line


def interpret(client, utterance: str, model: str = "sarvam-105b") -> str | None:
    try:
        out = client.chat([{"role": "system", "content": SYSTEM_PROMPT},
                           {"role": "user", "content": utterance}], model=model,
                          max_tokens=80, temperature=0.0)
    except Exception as e:
        log.warning("NLU fallback unavailable: %s", e)
        return None
    return validate(out)
