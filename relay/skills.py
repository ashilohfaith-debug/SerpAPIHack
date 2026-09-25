"""Everyday skills — what a blind user asks RELAY for, all day, by voice.

Status (time, date, battery, internet), volume and media, arithmetic, apps and
windows, websites and search, files and folders, reading pages and documents with a
cursor, links and headings, notes and reminders, dictation, speech speed, language
and Connected mode.

Every skill that changes the machine is expressed as a runner Step, so it inherits
the transparency contract: announced before it happens, done through the gated
executor, verified by observation, and narrated after with every change. Skills that
only answer (time, battery, reading) speak directly. Lists RELAY reads out (files,
windows, links, headings) are remembered briefly so "open the second one" works.
"""

from __future__ import annotations

import re
import time

from relay.diagnostics import get_logger
from relay.intent.grammar import Kind
from relay.intent.normalize import apply_spoken_punctuation
from relay.narration import policy as pol
from relay.perception.semantic import UIElement
from relay.planner.planner import Step
from relay.planner.runner import spoken_keys
from relay.safety import Action

log = get_logger("skills")

_REQ = pol.Priority.REQUESTED
_CONF = pol.Priority.CONFIRMATION
BROWSERS = ("chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe",
            "vivaldi.exe")
OFFICE = ("winword.exe", "excel.exe", "powerpnt.exe")
# Enter sends a message in these apps — a recognition slip must never send wrong text
MESSAGING = ("whatsapp.root.exe", "whatsapp.exe", "telegram.exe", "teams.exe",
             "ms-teams.exe", "slack.exe", "discord.exe", "signal.exe", "outlook.exe",
             "olk.exe")
LIST_TTL = 300.0          # "the second one" refers to a list read in the last 5 min

HELP = {
    "": ("Here's what you can ask me. Say help with, and a topic, for more. "
         "Topics are: reading, web, typing, apps and windows, files, system, notes and "
         "reminders, and languages. "
         "A few examples: what time is it. Open WhatsApp. Search for today's weather. "
         "Read the page. Take a note. Remind me in ten minutes to call mom. "
         "What's on my screen. Stop, to interrupt me. Cancel, to stop a task. "
         "Emergency stop, to halt everything."),
    "reading": ("Reading. Say: read the page, or read the document, to hear everything "
                "from the top. Stop pauses; continue picks up where you left off. "
                "Next paragraph and previous paragraph move around. Repeat reads the part "
                "again. You can also say: read the title, read the clipboard, read this, "
                "spell that, list the links, list the headings, or read with OCR for "
                "text inside images."),
    "web": ("The web. Say: search for, and what you want. Or: open YouTube, open Gmail, "
            "or open flipkart dot com. Play, a song name, on YouTube. Then: read the page, "
            "list the links, and open the third link. Go back, reload, new tab and "
            "close tab also work."),
    "typing": ("Typing. Say: type, and your text. Or say start dictation, then just talk; "
               "say comma, full stop, question mark, or new line for punctuation, and stop "
               "dictation when you're done. Select all, copy, paste, undo, and delete the "
               "last word all work, and so does press control s, or press enter."),
    "apps": ("Apps and windows. Say: open, and any app on your computer, like Word or "
             "WhatsApp. What windows are open. Switch to Chrome. Minimize, maximize, "
             "close this window, and show desktop."),
    "files": ("Files. Say: open downloads, or open documents. Find my resume. Then open "
              "the first one, or read the first one. Read the PDF, and its name, reads a "
              "PDF or Word file aloud."),
    "system": ("System. Ask: what time is it, what's the date, how's my battery, am I "
               "connected to the internet, or just say status. Volume up, volume down, "
               "set volume to 40 percent, and mute. Play music, pause music and next "
               "track control your music. Ask me sums like: what is 25 times 4."),
    "notes": ("Notes and reminders. Say: take a note, and what to write. Read my notes. "
              "Remind me in ten minutes to call mom, or remind me at 6 p m to take my "
              "medicine. Set a timer for five minutes. What are my reminders. Cancel my "
              "reminders."),
    "languages": ("Languages. With Connected mode you can talk to me and hear me in Hindi, "
                  "Telugu, Tamil and other Indian languages, through Sarvam A I. Say: turn "
                  "on connected mode. Then: speak in Hindi, or read this page in Telugu. "
                  "Say turn off connected mode to keep everything on this computer."),
}
_HELP_ALIASES = {"the web": "web", "internet": "web", "browsing": "web", "writing": "typing",
                 "keys": "typing", "keyboard": "typing", "windows": "apps",
                 "reminders": "notes", "language": "languages", "music": "system",
                 "media": "system"}


def _preview(text: str, words: int = 12) -> str:
    w = text.split()
    return " ".join(w[:words]) + (" ..." if len(w) > words else "")


class Skills:
    def __init__(self, session) -> None:
        self.s = session
        self._last_list: tuple[str, list, float] | None = None

    # ---------------------------------------------------------------- helpers
    def say(self, text: str, priority: int = _REQ) -> None:
        self.s.say(text, priority)

    def run(self, *steps):
        return self.s.runner.run(list(steps), cancel=self.s.cancel)

    def remember_list(self, kind: str, items: list) -> None:
        self._last_list = (kind, items, time.monotonic())

    def recent_list(self):
        if self._last_list and time.monotonic() - self._last_list[2] < LIST_TTL:
            return self._last_list
        return None

    def _fg_app(self) -> str:
        from relay.system import windows
        fg = windows.foreground()
        return (fg.app or "").lower() if fg else ""

    def handle(self, intent):
        fn = getattr(self, f"k_{intent.kind}", None)
        if fn is None:
            return None
        out = fn(intent)
        return out if out is not None else []

    # ---------------------------------------------------------------- status
    def k_time(self, i):
        from relay.system import status
        self.say(status.time_text())

    def k_date(self, i):
        from relay.system import status
        self.say(status.date_text())

    def k_battery(self, i):
        from relay.system import status
        self.say(status.battery_text())

    def k_internet(self, i):
        from relay.system import status
        self.say(status.internet_text())

    def k_status(self, i):
        from relay.system import status
        self.say(status.status_text())

    def k_calculate(self, i):
        from relay.system import calc
        ans = calc.answer(i.slots.get("text", ""))
        self.say(ans or "I couldn't work that out. Try saying it like: what is 25 times 4.")

    # ---------------------------------------------------------------- help
    def k_help(self, i):
        topic = (i.slots.get("topic") or "").strip()
        topic = _HELP_ALIASES.get(topic, topic)
        text = HELP.get(topic, HELP[""])
        self.s.reader.load(text, title="")
        self.s.reader.read_all(intro=False)
        self.s.last_activity = "reading"

    # ---------------------------------------------------------------- volume/media
    def k_volume(self, i):
        from relay.system import volume as vol
        action = i.slots.get("action")
        cur = vol.get_volume()
        if action == "get":
            self.say(vol.describe(cur))
            return
        if cur is None:
            key = {"up": "volumeup", "down": "volumedown", "mute": "volumemute",
                   "unmute": "volumemute"}.get(action)
            if key is None:
                self.say("I can't set an exact volume on this computer, but I can turn it "
                         "up or down.")
                return
            count = 5 if action in ("up", "down") else 1
            return self.run(Step("press", f"turn the volume {action}", {
                "key": key, "count": count, "announce": f"Turning the volume {action}.",
                "done_text": "Done. I can't read the exact level on this computer.",
                "no_delta": True}))
        pct, _muted = cur
        if action in ("mute", "unmute"):
            want_muted = action == "mute"

            def do():
                return vol.set_mute(want_muted)

            def check():
                now = vol.get_volume()
                done = now is not None and now[1] == want_muted
                return done, ("Sound is muted." if want_muted
                              else f"Sound is on, at {pct} percent.")
            announce = "Muting the sound." if want_muted else "Unmuting the sound."
        else:
            if action == "up":
                target = min(100, pct + 10)
            elif action == "down":
                target = max(0, pct - 10)
            else:
                target = max(0, min(100, int(i.slots.get("level", pct))))

            def do():
                return vol.set_volume(target)

            def check():
                now = vol.get_volume()
                return (now is not None and abs(now[0] - target) <= 1,
                        f"Volume is now {now[0] if now else target} percent.")
            announce = (f"Turning the volume {action}." if action in ("up", "down")
                        else f"Setting the volume to {target} percent.")
        return self.run(Step("system", "change the volume", {
            "what": "volume", "do": do, "check": check, "announce": announce,
            "speak_detail": True, "no_delta": True}))

    def k_media(self, i):
        action = i.slots.get("action", "play_pause")
        key, words = {"play_pause": ("playpause", "play/pause"),
                      "next": ("nexttrack", "next track"),
                      "previous": ("prevtrack", "previous track"),
                      "stop": ("stop", "stop")}[action]
        return self.run(Step("press", f"press {words}", {
            "key": key, "announce": f"Pressing {words}.", "done_text": "", "no_delta": True}))

    # ---------------------------------------------------------------- speech
    def k_speech_rate(self, i):
        change = i.slots.get("change")
        rate = self.s.speech_rate
        rate = {"faster": min(2.2, rate * 1.25), "slower": max(0.6, rate / 1.25),
                "normal": 1.0}[change]
        self.s.set_speech_rate(rate)
        self.say({"faster": "Okay, speaking faster.", "slower": "Okay, speaking slower.",
                  "normal": "Okay, back to normal speed."}[change])

    def k_language(self, i):
        from relay.connected import LANG_NAMES, LANGS
        lang = i.slots.get("language", "")
        if lang == "auto":
            code = "auto"
        else:
            code = LANGS.get(lang, "")
        if not code:
            self.say("I don't know that language yet.")
            return
        cv = self.s.connected
        if code in ("en-IN",) and cv is None:
            self.say("I'm speaking English.")
            return
        if cv is None:
            name = LANG_NAMES.get(code, lang.capitalize())
            self.say(f"To speak {name}, I need Connected mode, which uses Sarvam A I. "
                     "Say: turn on connected mode.")
            return
        cv.output_language = code
        self.s.store.set_pref("output_language", code)
        name = "the language you speak to me in" if code == "auto" else LANG_NAMES[code]
        self.say(f"Okay, I'll speak {name} from now on.")

    def k_wake_word(self, i):
        on = bool(i.slots.get("on"))
        self.s.store.set_pref("wake_word_enabled", "1" if on else "0")
        if self.s.on_wake_word is not None:
            self.s.on_wake_word(on)
        from relay.audio.hotkeys import spoken_combo
        key = spoken_combo(self.s.talk_key)
        self.say("Wake word on. Say Relay, then your command." if on else
                 f"Wake word off. I'll only listen when you press {key}.")

    def k_connected(self, i):
        self.s.set_connected(bool(i.slots.get("on")))

    def k_quit(self, i):
        self.say("Closing Relay. Goodbye.", _CONF)
        if self.s.on_quit is not None:
            self.s.on_quit()

    # ---------------------------------------------------------------- dictation
    def k_dictation(self, i):
        on = bool(i.slots.get("on"))
        self.s.set_dictation(on)
        if not on:
            self.say("Dictation off.")
            return
        snap = self.s.worker.observe(3.0)
        editable = bool(snap and snap.focus and snap.focus.role in ("Edit", "Document"))
        tip = "" if editable else (" I don't see a text box focused right now, so move to "
                                   "one first, or say stop dictation.")
        self.say("Dictation on. Everything you say will be typed where your cursor is. Say "
                 f"comma or full stop for punctuation, and stop dictation when you're done.{tip}")

    def dictate(self, utterance: str):
        text = apply_spoken_punctuation(utterance.strip())
        text = re.sub(r"(?i)^relay[,.]?\s+", "", text)
        if not text.strip():
            return []
        if text.endswith(("\n",)):
            payload = text
        else:
            payload = text + " "
        o = self.s.executor.type_text(payload)
        from relay.memory.journal import ExecState
        if o.state != ExecState.EXECUTED:
            self.say(f"I couldn't type that: {o.detail}.", pol.Priority.CRITICAL)
            return []
        spoken = text.strip() or "a new line"
        self.say(f"Typed: {spoken}" if len(spoken) < 200 else "Typed your paragraph.")
        return []

    # ---------------------------------------------------------------- notes
    def k_take_note(self, i):
        text = (i.slots.get("text") or "").strip()
        if not text:
            self.say("What should the note say?")
            self.s.capture_next(lambda t: self._save_note(t))
            return
        self._save_note(text)

    def _save_note(self, text: str):
        if self.s.notes.add(text):
            self.say(f"Noted: {text.rstrip('.')}.")
        else:
            self.say("I won't save that — it looks like a password or code, so I'm keeping "
                     "it out of my notes.")

    def k_read_notes(self, i):
        text = self.s.notes.spoken(limit=50)
        self.s.reader.load(text, title="")
        self.s.reader.read_all(intro=False)
        self.s.last_activity = "reading"

    def k_delete_notes(self, i):
        n = self.s.notes.count()
        if n == 0:
            self.say("You don't have any notes.")
            return
        self.s.ask_phrase(
            "confirm delete",
            f"This will delete all {n} of your notes. It can't be undone.",
            lambda: self.say(f"Deleted {self.s.notes.delete_all()} notes.", _CONF))

    # ---------------------------------------------------------------- reminders
    def k_set_reminder(self, i):
        from relay.reminders import parse_reminder, when_text
        parsed = parse_reminder(i.slots.get("text", ""))
        if parsed is None:
            self.say("When should I remind you? For example, say: remind me in 10 minutes "
                     "to call mom, or remind me at 6 p m to take my medicine.")
            return
        due, msg, is_timer = parsed
        self.s.reminders.add(msg, due.timestamp())
        if is_timer:
            self.say(f"Timer set. It will go off {when_text(due)}.")
        else:
            self.say(f"Okay. I'll remind you to {msg} {when_text(due)}."
                     if not msg.startswith("this is") else
                     f"Okay. I'll remind you {when_text(due)}.")

    def k_list_reminders(self, i):
        self.say(self.s.reminders.spoken_pending())

    def k_cancel_reminders(self, i):
        n = self.s.reminders.cancel_all()
        self.say("You had no reminders." if n == 0 else
                 f"Cancelled {n} reminder{'s' if n != 1 else ''}.")

    # ---------------------------------------------------------------- apps / windows
    def _window_finder(self, name: str):
        from relay.system import windows
        return lambda: windows.find(name)

    def k_open_app(self, i):
        from relay.system import files, web, windows
        target = (i.slots.get("app") or "").strip()
        if re.search(r"\b(?:first|second|third|fourth|fifth|last|one|number \d+)\b", target) \
                and self.recent_list():
            return self.k_pick(type(i)(Kind.PICK, {"verb": "open", "ordinal": _ord(target)}))
        clean = re.sub(r"\b(?:the|my|app|application|program)\b", " ", target).strip()
        clean = " ".join(clean.split())
        folder = files.folder_for_phrase(target)
        if folder is not None:
            name, path = folder
            label = path.name
            return self.run(Step("open_uri", f"open your {name} folder", {
                "uri": str(path), "label": label,
                "check": lambda: bool((w := windows.foreground()) and label.lower() in
                                      w.title.lower()),
                "ok_text": f"Your {name} folder is open.", "speak_detail": True}))
        cat = self.s.apps
        cat.wait_ready(3.0)
        entry = cat.find(clean) if clean else None
        url = web.site_url(clean)
        if entry is not None and not (url and clean in web.SITES and
                                      entry.name.lower() != clean):
            existing = windows.find(entry.name) or windows.find(clean)
            if existing is not None:
                return self.run(Step("window", f"switch to {entry.name}", {
                    "op": "activate", "hwnd": existing.hwnd, "label": entry.name,
                    "announce": f"{entry.name} is already open. Switching to it.",
                    "ok_text": f"You're in {existing.spoken}.", "speak_detail": True}))
            return self.run(Step("launch", f"open {entry.name}", {
                "entry": entry, "label": entry.name,
                "find_window": lambda: windows.find(entry.name) or windows.find(clean),
                "activate": windows.activate, "timeout": 10.0,
                "speak_detail": True}))
        if url:
            return self._open_site(url, clean)
        if re.search(r"\.\w{2,4}$", clean):                 # looks like a file name
            return self.k_open_file(type(i)(Kind.OPEN_FILE, {"name": clean, "then": "open"}))
        self.say(f"I couldn't find an app called {target}. Do you want me to search the "
                 "web for it? Say yes or no.")
        self.s.offer(lambda: self._search(target))
        return []

    def _open_site(self, url: str, label: str):
        from relay.system import web, windows
        site = web.site_label(url)
        return self.run(Step("open_uri", f"open {label}", {
            "uri": url, "label": label,
            "check": lambda: bool((w := windows.foreground()) and w.app.lower() in BROWSERS
                                  and site.lower() in w.title.lower()),
            "ok_text": f"{label.capitalize()} is open in your browser. Say read the page, or "
                       "list the links.",
            "fail_text": "I asked your browser to open it, but I couldn't confirm the page "
                         "loaded yet",
            "announce": f"Opening {label} in your browser.", "speak_detail": True,
            "timeout": 10.0}))

    def k_switch_app(self, i):
        from relay.system import web, windows
        target = (i.slots.get("app") or "").strip()
        rl = self.recent_list()
        if rl and rl[0] == "windows" and re.search(
                r"\b(?:first|second|third|fourth|fifth|last|one|number \d+|window \d+)\b",
                target):
            return self.k_pick(type(i)(Kind.PICK, {"verb": "switch to", "ordinal": _ord(target)}))
        w = windows.find(target)
        if w is not None:
            return self.run(Step("window", f"switch to {w.spoken}", {
                "op": "activate", "hwnd": w.hwnd, "label": w.spoken,
                "announce": f"Switching to {w.spoken}.",
                "ok_text": f"You're in {w.spoken}.", "speak_detail": True}))
        url = web.site_url(target)
        if url:
            return self._open_site(url, target)
        if self.s.apps.find(target) is not None:
            self.say(f"{target.capitalize()} isn't open. Do you want me to open it? "
                     "Say yes or no.")
            self.s.offer(lambda: self.k_open_app(type(i)(Kind.OPEN_APP, {"app": target})))
            return []
        self.say(f"I couldn't find a window for {target}. Say what windows are open to "
                 "hear them.")

    def k_list_windows(self, i):
        from relay.system import windows
        wins = windows.list_windows()
        self.remember_list("windows", wins)
        self.say(windows.spoken_list(wins) + (" Say switch to, and a number or name."
                                              if wins else ""))

    def k_window_op(self, i):
        from relay.system import windows
        op = i.slots.get("op")
        target = (i.slots.get("target") or "").strip()
        w = windows.find(target) if target else windows.foreground()
        if w is None:
            self.say(f"I couldn't find a window called {target}." if target else
                     "There's no window in front to do that to.")
            return
        verbs = {"close": "close", "minimize": "minimize", "maximize": "maximize",
                 "restore": "restore"}
        ok_text = {"minimize": f"{w.spoken} is minimized.",
                   "maximize": f"{w.spoken} is maximized.",
                   "restore": f"{w.spoken} is restored."}.get(op, "")
        return self.run(Step("window", f"{verbs[op]} {w.spoken}", {
            "op": op, "hwnd": w.hwnd, "label": w.spoken, "ok_text": ok_text,
            "speak_detail": True,
            "announce": f"I'm going to {verbs[op]} {w.spoken}." + (
                " If it has unsaved work, it will ask you first." if op == "close" else "")}))

    def k_show_desktop(self, i):
        return self.run(Step("hotkey", "show the desktop", {
            "keys": ["win", "d"], "announce": "Showing the desktop.", "done_text": ""}))

    # ---------------------------------------------------------------- keys
    def _explorer_delete_guard(self, keys: list[str], retry) -> bool:
        """Delete in File Explorer removes files: require the spoken phrase."""
        if "delete" in keys and self._fg_app() == "explorer.exe":
            dec = self.s.engine.classify(Action(kind="delete_file", target_app="File Explorer",
                                                target_label="the selected item"))
            self.s._on_confirm_needed(dec, "delete", retry)
            return True
        return False

    def _send_guard(self, keys: list[str], retry) -> bool:
        """Enter in a chat app SENDS: read the message back and require 'confirm send'."""
        app = self._fg_app()
        if app not in MESSAGING or keys[-1:] != ["enter"]:
            return False
        draft = self._focus_value().strip()
        what = f"this message: {draft}" if draft and len(draft) < 400 else "your message"
        dec = self.s.engine.classify(Action(kind="send_message", target_app=app,
                                            target_label="the message"))
        self.say(f"I'm about to send {what}.", _CONF)
        self.s._on_confirm_needed(dec, "send", retry)
        return True

    def k_send(self, i):
        step = Step("press", "send the message", {
            "key": "enter", "announce": "Sending.", "done_text": ""})
        if self._send_guard(["enter"], lambda: self.s.runner.run([step])):
            return []
        self.say("There's no message app in front. Open WhatsApp or another chat app "
                 "first.")

    def k_press_key(self, i):
        key, count = i.slots["key"], i.slots.get("count", 1)
        step = Step("press", f"press {spoken_keys([key])}", {
            "key": key, "count": count,
            "announce": f"Pressing {spoken_keys([key])}" + (f" {count} times." if count > 1
                                                             else "."),
            "done_text": ""})
        retry = lambda: self.s.runner.run([step])  # noqa: E731
        if self._explorer_delete_guard([key], retry) or self._send_guard([key], retry):
            return []
        return self.run(step)

    def k_hotkey(self, i):
        keys = i.slots["keys"]
        seq = bool(i.slots.get("sequence"))
        words = ", then ".join(spoken_keys([k]) for k in keys) if seq else spoken_keys(keys)
        step = Step("hotkey", f"press {words}", {
            "keys": keys, "count": i.slots.get("count", 1), "sequence": seq,
            "announce": f"Pressing {words}.", "done_text": ""})
        retry = lambda: self.s.runner.run([step])  # noqa: E731
        if self._explorer_delete_guard(keys, retry) or self._send_guard(keys, retry):
            return []
        return self.run(step)

    def k_shortcut(self, i):
        keys, desc = i.slots["keys"], i.slots["description"]
        p = {"keys": keys, "announce": f"I'm going to {desc}.", "done_text": ""}
        if keys in (["ctrl", "c"], ["ctrl", "x"]):
            p.update(before=_clipboard, check=_copied_check, speak_detail=True,
                     uncertain_text="I pressed it, but nothing new reached the clipboard. "
                                    "Is anything selected?")
        elif keys == ["ctrl", "a"]:
            p.update(check=lambda _b: self._selection_check(), speak_detail=True,
                     uncertain_text="I pressed select all, but I couldn't confirm a "
                                    "selection here.")
        elif keys == ["ctrl", "v"]:
            p.update(before=lambda: self._focus_value(),
                     check=lambda b: (self._focus_value() != b, "Pasted."),
                     speak_detail=True,
                     uncertain_text="I pressed paste, but I couldn't confirm the text "
                                    "changed.")
        return self.run(Step("hotkey", desc, p))

    def _selection_check(self):
        snap = self.s.worker.observe(3.0)
        sel = (snap.selection if snap else "") or ""
        return bool(sel.strip()), ("Selected all the text." if sel.strip() else "")

    def _focus_value(self) -> str:
        snap = self.s.worker.observe(3.0)
        return (snap.focus.value if snap and snap.focus else "") or ""

    def k_scroll(self, i):
        d = i.slots.get("direction", "down")
        return self.run(Step("press", f"scroll {d}", {
            "key": "pagedown" if d == "down" else "pageup",
            "announce": f"Scrolling {d}.", "done_text": ""}))

    def k_go_back(self, i):
        return self.run(Step("press", "go back", {
            "key": "browserback", "announce": "Going back.", "done_text": ""}))

    # ---------------------------------------------------------------- web
    def _search(self, query: str):
        from relay.system import web, windows
        url = web.search_url(query)
        return self.run(Step("open_uri", f"search the web for {query}", {
            "uri": url, "label": "Google",
            "check": lambda: bool((w := windows.foreground()) and w.app.lower() in BROWSERS
                                  and "google" in w.title.lower()),
            "announce": f"Searching the web for {query}.",
            "ok_text": "The search results are open. Say read the page, or list the links.",
            "fail_text": "I asked your browser to search, but I couldn't confirm the results "
                         "loaded yet",
            "speak_detail": True, "timeout": 10.0}))

    def k_web_search(self, i):
        return self._search(i.slots.get("query", ""))

    def k_youtube(self, i):
        from relay.system import web, windows
        q = i.slots.get("query", "")
        return self.run(Step("open_uri", f"search YouTube for {q}", {
            "uri": web.youtube_url(q), "label": "YouTube",
            "check": lambda: bool((w := windows.foreground()) and "youtube" in w.title.lower()),
            "announce": f"Searching YouTube for {q}.",
            "ok_text": "YouTube results are open. Say list the links, then open the first "
                       "link to play one.",
            "speak_detail": True, "timeout": 10.0}))

    # ---------------------------------------------------------------- files
    def k_find_file(self, i):
        from relay.system import files
        name = i.slots.get("name", "")
        self.say(f"Looking for {name}.", pol.Priority.FOCUS)
        hits = files.find_files(name)
        if not hits:
            self.say(f"I couldn't find a file called {name} in your Desktop, Documents, "
                     "Downloads, Pictures, Music or Videos.")
            return
        self.remember_list("files", hits)
        listed = "; ".join(f"{n}, {h.spoken}" for n, h in enumerate(hits, 1))
        self.say(f"I found {len(hits)}: {listed}. Say open the first one, or read the "
                 "first one.")

    def k_open_file(self, i):
        from relay.system import files
        name = i.slots.get("name", "")
        hits = files.find_files(name, limit=3)
        if not hits:
            self.say(f"I couldn't find a file called {name}.")
            return
        return self._use_file(hits[0].path, i.slots.get("then", "open"))

    def _use_file(self, path, verb: str):
        from relay.system import files, windows
        if verb == "read":
            text = files.read_file_text(path)
            if text:
                self.s.start_reading(text, title=path.stem)
                return []
            self.say(f"I couldn't find readable text in {path.name}. It may be a scanned "
                     "image. Do you want me to open it instead? Say yes or no.")
            self.s.offer(lambda: self._use_file(path, "open"))
            return []
        stem = path.stem.lower()[:25]
        return self.run(Step("open_uri", f"open {path.name}", {
            "uri": str(path), "label": path.name,
            "check": lambda: bool((w := windows.foreground()) and stem in w.title.lower()),
            "ok_text": f"{path.name} is open.", "speak_detail": True, "timeout": 10.0}))

    # ---------------------------------------------------------------- pick from list
    def k_pick(self, i):
        rl = self.recent_list()
        n = int(i.slots.get("ordinal", 1))
        verb = i.slots.get("verb", "open")
        if rl is None:
            if verb in ("open", "use", "pick"):     # no list read out: an on-screen control
                return self.k_activate(type(i)(Kind.ACTIVATE, {
                    "target": f"item {n}", "ordinal": n}))
            self.say("I haven't read you a list recently. Say list the links, find a file, "
                     "or what windows are open first.")
            return
        kind, items, _ = rl
        idx = n - 1 if n > 0 else len(items) - 1
        if not 0 <= idx < len(items):
            self.say(f"There are only {len(items)} in that list.")
            return
        item = items[idx]
        if kind == "files":
            return self._use_file(item.path, "read" if verb == "read" else "open")
        if kind == "windows":
            return self.run(Step("window", f"switch to {item.spoken}", {
                "op": "activate", "hwnd": item.hwnd, "label": item.spoken,
                "announce": f"Switching to {item.spoken}.",
                "ok_text": f"You're in {item.spoken}.", "speak_detail": True}))
        if kind in ("links", "headings"):
            if kind == "headings":
                self.say(f"Heading {n}: {item.name}.")
                return
            el = UIElement(uid=0, name=item.name, role="Hyperlink", bbox=item.bbox)
            return self.run(Step("activate", f"open the link {item.name}", {
                "target": item.name, "deep_find": lambda: el}))
        self.say("I can't open that kind of item.")

    # ---------------------------------------------------------------- reading
    def _document(self):
        from relay.perception import text as ptext
        val, ok = self.s.worker.run(ptext.document_text, timeout=8.0)
        title, body = val if ok and val else ("", "")
        if not body:
            val, ok = self.s.worker.run(ptext.visible_text, timeout=8.0)
            body = val if ok and val else ""
        return title, body

    def k_read_all(self, i):
        lang = i.slots.get("language", "")
        if lang and lang != "english":
            from relay.connected import LANGS
            if self.s.connected is None:
                self.say(f"Reading in {lang.capitalize()} needs Connected mode. Say turn on "
                         "connected mode. For now, I'll read it in English.")
            else:
                self.s.connected.output_language = LANGS.get(lang, "auto")
        self.say("Getting the text.", pol.Priority.FOCUS)
        title, body = self._document()
        if not body:
            self.say("I can't find readable text here with the accessibility tree. Trying "
                     "OCR, which reads text from the screen image.")
            body = self._ocr_text()
        if not body:
            self.say("I couldn't find any text to read on this screen.")
            return
        self.s.start_reading(body, title=_short_title(title))

    def _ocr_text(self) -> str:
        from relay.perception import ocr as ocr_mod
        from relay.system import windows
        fg = windows.foreground()
        region = None
        if fg is not None:
            import ctypes
            from ctypes import wintypes
            r = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(fg.hwnd, ctypes.byref(r)):
                region = (max(0, r.left), max(0, r.top), r.right, r.bottom)
        regions = self.s.ocr.read_screen(region=region)
        return ocr_mod.to_text(regions)

    def k_ocr_read(self, i):
        self.say("Reading the screen image with OCR. This takes a few seconds, and it may "
                 "make mistakes.", pol.Priority.FOCUS)
        text = self._ocr_text()
        if not text:
            self.say("I couldn't find any text in the screen image.")
            return
        self.s.start_reading(text, title="the screen text")

    def k_read_next(self, i):
        if not self.s.reader.has_content:
            self.say("Nothing is being read. Say read the page first.")
            return
        self.s.reader.step(+1)

    def k_read_prev(self, i):
        if not self.s.reader.has_content:
            self.say("Nothing is being read. Say read the page first.")
            return
        self.s.reader.step(-1)

    def k_read_title(self, i):
        from relay.system import windows
        fg = windows.foreground()
        self.say(f"This is {fg.spoken}." if fg else "I can't tell which window is in front.")

    def k_read_clipboard(self, i):
        from relay.memory.store import looks_sensitive
        text = _clipboard()
        if not text.strip():
            self.say("The clipboard is empty.")
        elif looks_sensitive(text):
            self.say("The clipboard holds something that looks like a password or code, so "
                     "I won't read it aloud.")
        elif len(text) > 400:
            self.s.start_reading(text, title="the clipboard")
        else:
            self.say(f"The clipboard says: {text}")

    def _items(self, fn_name: str):
        from relay.perception import text as ptext
        val, ok = self.s.worker.run(getattr(ptext, fn_name), timeout=8.0)
        return val if ok and val else []

    def k_list_links(self, i):
        items = self._items("links")
        if not items:
            self.say("I don't see any links here.")
            return
        self.remember_list("links", items)
        body = "\n".join(f"{n}, {it.name}." for n, it in enumerate(items, 1))
        self.say(f"There are {len(items)} links. Say stop when you hear the one you want, "
                 "then say open, and its number.")
        self.s.start_reading(body, title="", intro=False)

    def k_list_headings(self, i):
        items = self._items("headings")
        if not items:
            self.say("This page has no headings I can find. Try read the page, or list the "
                     "links.")
            return
        self.remember_list("headings", items)
        body = "\n".join(f"{n}, {'level ' + str(it.level) + ', ' if it.level else ''}"
                         f"{it.name}." for n, it in enumerate(items, 1))
        self.say(f"There are {len(items)} headings.")
        self.s.start_reading(body, title="", intro=False)

    def k_read_focus(self, i):
        snap = self.s.worker.observe(3.0)
        if snap and snap.selection:
            sel = snap.selection
            if len(sel) > 400:
                self.s.start_reading(sel, title="the selection")
            else:
                self.say(f"Selected text: {sel}")
            return
        f = snap.focus if snap else None
        if f and f.role in ("Document", "Edit") and len(f.value or "") >= 190:
            return self.k_read_all(i)
        if f and (f.value or f.name):
            self.say(f"{f.role}: {f.value or f.name}")
            return
        self.say("Nothing is focused right now. Say read the page to hear everything.")

    def k_describe_screen(self, i):
        snap = self.s.worker.observe(3.0)
        if snap is None:
            self.say("I can't read the screen right now.")
            return
        self.s.ctx.last_narrated = snap
        if (snap.foreground_app or "").lower() in BROWSERS:
            links = self._items("links")
            heads = self._items("headings")
            parts = [f"A web page: {_short_title(snap.foreground_title)}."]
            if heads:
                parts.append(f"It has {len(heads)} heading{'s' if len(heads) != 1 else ''}; "
                             f"the first is {heads[0].name}.")
            parts.append(f"{len(links)} link{'s' if len(links) != 1 else ''}.")
            if snap.focus and snap.focus.name:
                parts.append(f"Focus is on {snap.focus.role} {snap.focus.name}.")
            parts.append("Say read the page, list the headings, or list the links.")
            self.say(" ".join(parts))
            return
        self.say(pol.describe(snap, self.s.narration_mode))

    # ---------------------------------------------------------------- typing / saving
    def k_type(self, i):
        text = apply_spoken_punctuation(i.slots.get("text", ""))
        return self.run(Step("type", "type your text", {"text": text}))

    def k_save(self, i):
        name = (i.slots.get("name") or "").strip()
        if not name:
            return self.run(Step("save", "save the file", {}))
        keys = ("f12",) if self._fg_app() in OFFICE else ("ctrl", "shift", "s")
        return self.run(Step("save_as", f"save this as {name}", {
            "name": name, "keys": keys, "speak_detail": True}))

    # ---------------------------------------------------------------- activate
    def k_activate(self, i):
        s = i.slots
        target, ordinal, role = s.get("target"), s.get("ordinal"), s.get("role")

        def deep():
            if role in ("link", "result"):
                items = self._items("links")
                if not items:
                    return None
                if ordinal is not None:
                    idx = ordinal - 1 if ordinal > 0 else len(items) - 1
                    it = items[idx] if 0 <= idx < len(items) else None
                else:
                    t = re.sub(r"\b(?:the|link|result)\b", " ", (target or "").lower()).strip()
                    it = next((x for x in items if t and t in x.name.lower()), None)
                if it is not None:
                    self.remember_list("links", items)
                    return UIElement(uid=0, name=it.name, role="Hyperlink", bbox=it.bbox)
                return None
            if target and ordinal is None:
                from relay.perception import text as ptext
                bare = re.sub(r"\b(?:the|button|link|on)\b", " ", target).strip() or target
                found, ok = self.s.worker.run(lambda: ptext.find_named(bare), timeout=8.0)
                if ok and found:
                    it = found[0]
                    return UIElement(uid=0, name=it.name, role=it.role, bbox=it.bbox)
            return None

        payload = dict(s)
        payload["deep_find"] = deep
        return self.run(Step("activate", f"click {target}", payload))


def _ord(text: str) -> int:
    from relay.intent.grammar import _ordinal_in
    return _ordinal_in(text) or 1


def _short_title(title: str) -> str:
    t = (title or "").strip()
    for suffix in (" - Google Chrome", " - Microsoft​ Edge", " - Microsoft Edge", " - Brave",
                   " - Personal - Microsoft Edge", " - Mozilla Firefox", " - Notepad",
                   " - Word"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    return t[:120]


def _clipboard() -> str:
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception:
        return ""


def _copied_check(before: str):
    from relay.memory.store import looks_sensitive
    now = _clipboard()
    if now and now != before:
        if looks_sensitive(now):
            return True, "Copied."
        return True, f"Copied: {_preview(now)}"
    return False, ""
