"""The conversational assistant — ChatGPT-style answers, spoken as they stream.

Used when the offline grammar can't handle a request ("what's a good name for a cat",
"explain what an index fund is", "summarise this page"). One streamed LLM call either
answers (spoken sentence by sentence while the model is still writing, so the first
words play within a fraction of a second) or, for something RELAY can DO, returns a
single line ``DO: <command>``. That command is untrusted text: it must parse with the
offline grammar to an allowed intent, can never be a confirmation phrase, is announced
("I understood that as …") and still passes the permission gate.

Privacy: only what the request needs is sent — the words the user said, a few recent
turns, and page text only when the user asks about the page. Protected fields and
anything that looks like a password are never sent.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from typing import Callable

from relay.diagnostics import get_logger
from relay.intent.grammar import Kind, parse
from relay.llm.router import NoRoute, Router
from relay.memory.store import looks_sensitive

log = get_logger("llm.assistant")

SYSTEM = """You are Relay, a voice assistant for a blind person using a Windows computer. \
Everything you write is spoken aloud by a speech synthesiser.

Rules for every answer:
- Answer in one to three short, natural sentences. Most important information first.
- Plain spoken English only: no markdown, lists, bullet points, headings, emojis, \
URLs, code, tables or special symbols. Say numbers and units the way a person would.
- Be warm and direct. Never say you are an AI model; never describe what you would do.
- If you don't know or can't check something (live news, prices, weather), say so briefly.

If the user wants something DONE on the computer, reply ONLY with command lines, one \
per step, in order, each starting with "DO: " (at most 8 lines). Use only these commands:
open <app, website, folder or file> | open <topic> settings | switch to <app> | \
close <app> | close this window | minimize this window | maximize this window | \
what windows are open | search the web for <query> | play <song or video> on youtube | \
open the <first/second/third> result | read the page | list links | list headings | \
click <name of a button, link or item> | type <text> | press <keys> | select all | copy | \
paste | undo | save | save as <name> | new tab | close tab | go back | scroll down | \
scroll up | what's on my screen | read the clipboard | find file <name> | \
read the file <name> | create a new folder called <name> on the desktop | \
rename this to <name> | move this to <desktop/documents/downloads> | take a note <text> | \
read my notes | remind me in <n> minutes to <text> | remind me at <time> to <text> | \
set an alarm for <time> | what time is it | what's the date | battery status | \
how much storage is left | what's my ip address | what's the weather in <city> | \
volume up | volume down | set volume to <n> percent | mute | unmute | play music | \
pause music | next track | turn on bluetooth | turn off bluetooth | turn on wifi | \
set brightness to <n> percent | turn on dark mode | turn off dark mode | \
take a screenshot | check for updates | speak faster | speak slower
Example — "open notepad and write a shopping list with milk and eggs":
DO: open notepad
DO: type Shopping list: milk, eggs.
Write any text to type in full, ready to use. Never output confirmation phrases, \
passwords, or commands that are not in this list."""

_BLOCK = re.compile(r"^\s*(confirm|emergency|quit|exit|delete my notes|clear my notes|"
                    r"clear (my )?(task )?history|forget)\b", re.I)
_NEVER = {Kind.UNKNOWN, Kind.CONTROL, Kind.QUIT, Kind.DELETE_NOTES, Kind.CLEAR_HISTORY,
          Kind.FORGET}
# a sentence is finished only once the NEXT character arrives and is a space: while
# streaming, "It costs 3." may still become "It costs 3.5 lakh."
_SENTENCE_END = re.compile(r"[.!?।…]+[\"')\]]*\s")
_MIN_CHUNK = 12          # merge a very short opener ("Sure.") into the next sentence
_MAX_STEPS = 8           # longest plan the assistant may propose


def validate_command(line: str) -> str | None:
    """Accept a model-suggested command only if it's one allowed, parseable command."""
    line = (line or "").strip().splitlines()[0].strip() if (line or "").strip() else ""
    line = re.sub(r"^\s*DO\s*:\s*", "", line, flags=re.I).strip("`\"' ")
    if not re.match(r"(?i)(?:type|write|take a note|note|remind me)\b", line):
        line = line.rstrip(". ")                    # "DO: open notepad." -> "open notepad"
    if not line or _BLOCK.match(line) or looks_sensitive(line):
        return None
    return line if parse(line).kind not in _NEVER else None


def _clean_for_speech(text: str) -> str:
    text = re.sub(r"[*_`#>|]+", " ", text)                 # stray markdown
    text = re.sub(r"https?://\S+", "a link", text)
    return re.sub(r"\s+", " ", text).strip()


class Assistant:
    def __init__(self, router: Router, max_turns: int = 6) -> None:
        self.router = router
        self.history: deque[dict] = deque(maxlen=max_turns * 2)
        self._lock = threading.Lock()

    def respond(self, utterance: str, speak: Callable[[str], None],
                context: str = "", page_text: str = "", max_tokens: int = 260,
                cancel: threading.Event | None = None) -> tuple[str, str]:
        """Stream a reply. Returns ("command", cmd) | ("answer", text) | ("offline", "").
        Answer sentences are passed to ``speak`` the moment each one is complete."""
        if looks_sensitive(utterance):
            return "answer", self._say_local(speak, "I won't send that — it looks like a "
                                                    "password or a code.")
        user = utterance.strip()
        if page_text:
            user = (f"{user}\n\nThe text on the user's screen (use it to answer):\n"
                    f"{page_text[:6000]}")
        messages = [{"role": "system", "content": SYSTEM + (f"\n\nContext: {context}"
                                                            if context else "")}]
        with self._lock:
            messages += list(self.history)
        messages.append({"role": "user", "content": user})

        full = ""
        pending = ""
        spoken_any = False
        mode = None                          # None until we know: "cmd" or "answer"
        try:
            for delta in self.router.stream(messages, max_tokens=max_tokens, cancel=cancel):
                full += delta
                if mode is None:
                    head = full.lstrip()
                    if len(head) < 3 and "DO:".startswith(head.upper()[:3]):
                        continue                # can't tell yet
                    mode = "cmd" if head.upper().startswith("DO:") else "answer"
                    if mode == "answer":
                        pending = full
                        continue
                if mode == "cmd":
                    if len(re.findall(r"(?im)^\s*DO\s*:", full)) > _MAX_STEPS:
                        break                   # enough steps; ignore the rest
                    continue
                pending += delta
                while True:                     # speak each finished sentence at once
                    m = _SENTENCE_END.search(pending, _MIN_CHUNK - 1)
                    if not m:
                        break
                    sentence, pending = pending[:m.end()], pending[m.end():]
                    out = _clean_for_speech(sentence)
                    if out:
                        speak(out)
                        spoken_any = True
                if len(pending) > 220:          # a very long clause: don't wait for "."
                    cut = pending.rfind(" ", 0, 200)
                    cut = cut if cut > 80 else 200
                    speak(_clean_for_speech(pending[:cut]))
                    spoken_any = True
                    pending = pending[cut:]
        except NoRoute as e:
            log.warning("assistant offline: %s", e)
            if spoken_any:
                return "answer", full
            return "offline", ""
        if mode == "cmd":
            self._remember(utterance, full.strip())
            lines = [ln for ln in full.splitlines() if re.match(r"^\s*DO\s*:", ln, re.I)]
            cmds = [validate_command(ln) for ln in lines[:_MAX_STEPS]]
            if not cmds or any(c is None for c in cmds):
                # all or nothing: never run half of a plan that has an unsafe step
                return "answer", self._say_local(speak, "I'm not able to do that one." if
                                                 len(cmds) <= 1 else "I can't do all of that "
                                                 "safely, so I haven't started.")
            return ("command", cmds[0]) if len(cmds) == 1 else ("plan", cmds)
        tail = _clean_for_speech(pending)
        if tail:
            speak(tail)
        self._remember(utterance, full.strip())
        return "answer", full.strip()

    @staticmethod
    def _say_local(speak, text: str) -> str:
        speak(text)
        return text

    def _remember(self, user: str, reply: str) -> None:
        with self._lock:
            self.history.append({"role": "user", "content": user})
            self.history.append({"role": "assistant", "content": reply[:600]})
