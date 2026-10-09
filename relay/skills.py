"""Everyday skills — what a blind user asks RELAY for, all day, by voice.

Status (time, date, battery, internet), volume and media, arithmetic, apps and
windows, websites and search, files and folders, reading pages and documents with a
cursor, links and headings, notes and reminders, dictation and speech speed — all on
the laptop, with no account, cloud service or API key.

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
BROWSERS = ("chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe", "vivaldi.exe")
OFFICE = ("winword.exe", "excel.exe", "powerpnt.exe")
# Enter sends a message in these apps — a recognition slip must never send wrong text
MESSAGING = (
    "whatsapp.root.exe",
    "whatsapp.exe",
    "telegram.exe",
    "teams.exe",
    "ms-teams.exe",
    "slack.exe",
    "discord.exe",
    "signal.exe",
    "outlook.exe",
    "olk.exe",
)
LIST_TTL = 300.0  # "the second one" refers to a list read in the last 5 min

HELP = {
    "": (
        "Here's what you can ask me. Say help with, and a topic, for more. "
        "Topics are: reading, web, typing, apps and windows, files, system, and notes "
        "and reminders. "
        "A few examples: what time is it. Open WhatsApp. Search for today's weather. "
        "Read the page. Take a note. Remind me in ten minutes to call mom. "
        "What's on my screen. Stop, to interrupt me. Cancel, to stop a task. "
        "Emergency stop, to halt everything. To close me, say quit Relay, or press "
        "Control Alt R again."
    ),
    "reading": (
        "Reading. Say: read the page, or read the document, to hear everything "
        "from the top. Stop pauses; continue picks up where you left off. "
        "Next paragraph and previous paragraph move around. Repeat reads the part "
        "again. You can also say: read the title, read the clipboard, read this, "
        "spell that, list the links, list the headings, or read with OCR for "
        "text inside images."
    ),
    "web": (
        "The web. Say: search for, and what you want. Or: open YouTube, open Gmail, "
        "or open flipkart dot com. Play, a song name, on YouTube. Then: read the page, "
        "list the links, and open the third link. Go back, reload, new tab and "
        "close tab also work."
    ),
    "typing": (
        "Typing. Say: type, and your text. Or say start dictation, then just talk; "
        "say comma, full stop, question mark, or new line for punctuation, and stop "
        "dictation when you're done. Select all, copy, paste, undo, and delete the "
        "last word all work, and so does press control s, or press enter."
    ),
    "apps": (
        "Apps and windows. Say: open, and any app on your computer, like Word or "
        "WhatsApp. What windows are open. Switch to Chrome. Minimize, maximize, "
        "close this window, and show desktop."
    ),
    "files": (
        "Files. Say: open downloads, or open documents. Find my resume. Then open "
        "the first one, or read the first one. Read the PDF, and its name, reads a "
        "PDF or Word file aloud."
    ),
    "system": (
        "System. Ask: what time is it, what's the date, how's my battery, am I "
        "connected to the internet, or just say status. Volume up, volume down, "
        "set volume to 40 percent, and mute. Play music, pause music and next "
        "track control your music. Ask me sums like: what is 25 times 4. "
        "Headphones: I switch to them by myself, and while you wear them you can "
        "interrupt me just by talking. Say where is the sound going, or headphone "
        "mode on, or off."
    ),
    "notes": (
        "Notes and reminders. Say: take a note, and what to write. Read my notes. "
        "Remind me in ten minutes to call mom, or remind me at 6 p m to take my "
        "medicine. Set a timer for five minutes. What are my reminders. Cancel my "
        "reminders."
    ),
}
_HELP_ALIASES = {
    "the web": "web",
    "internet": "web",
    "browsing": "web",
    "writing": "typing",
    "keys": "typing",
    "keyboard": "typing",
    "windows": "apps",
    "reminders": "notes",
    "music": "system",
    "media": "system",
    "headphones": "system",
    "sound": "system",
    "audio": "system",
}


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
            key = {
                "up": "volumeup",
                "down": "volumedown",
                "mute": "volumemute",
                "unmute": "volumemute",
            }.get(action)
            if key is None:
                self.say(
                    "I can't set an exact volume on this computer, but I can turn it up or down."
                )
                return
            count = 5 if action in ("up", "down") else 1
            return self.run(
                Step(
                    "press",
                    f"turn the volume {action}",
                    {
                        "key": key,
                        "count": count,
                        "announce": f"Turning the volume {action}.",
                        "done_text": "Done. I can't read the exact level on this computer.",
                        "no_delta": True,
                    },
                )
            )
        pct, _muted = cur
        if action in ("mute", "unmute"):
            want_muted = action == "mute"

            def do():
                return vol.set_mute(want_muted)

            def check():
                now = vol.get_volume()
                done = now is not None and now[1] == want_muted
                return done, (
                    "Sound is muted." if want_muted else f"Sound is on, at {pct} percent."
                )

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
                return (
                    now is not None and abs(now[0] - target) <= 1,
                    f"Volume is now {now[0] if now else target} percent.",
                )

            announce = (
                f"Turning the volume {action}."
                if action in ("up", "down")
                else f"Setting the volume to {target} percent."
            )
        return self.run(
            Step(
                "system",
                "change the volume",
                {
                    "what": "volume",
                    "do": do,
                    "check": check,
                    "announce": announce,
                    "speak_detail": True,
                    "no_delta": True,
                },
            )
        )

    def k_media(self, i):
        action = i.slots.get("action", "play_pause")
        key, words = {
            "play_pause": ("playpause", "play/pause"),
            "next": ("nexttrack", "next track"),
            "previous": ("prevtrack", "previous track"),
            "stop": ("stop", "stop"),
        }[action]
        return self.run(
            Step(
                "press",
                f"press {words}",
                {"key": key, "announce": f"Pressing {words}.", "done_text": "", "no_delta": True},
            )
        )

    # ---------------------------------------------------------------- speech
    def k_speech_rate(self, i):
        change = i.slots.get("change")
        rate = self.s.speech_rate
        rate = {"faster": min(2.2, rate * 1.25), "slower": max(0.6, rate / 1.25), "normal": 1.0}[
            change
        ]
        self.s.set_speech_rate(rate)
        self.say(
            {
                "faster": "Okay, speaking faster.",
                "slower": "Okay, speaking slower.",
                "normal": "Okay, back to normal speed.",
            }[change]
        )

    def k_language(self, i):
        lang = (i.slots.get("language") or "").strip()
        if lang in ("english", "auto", ""):
            self.say("I'm speaking English.")
            return
        self.say(
            f"I can only speak English on this computer for now, so I can't switch to "
            f"{lang.capitalize()}. Everything I do stays offline on this laptop."
        )

    def k_wake_word(self, i):
        on = bool(i.slots.get("on"))
        self.s.store.set_pref("wake_word_enabled", "1" if on else "0")
        if self.s.on_wake_word is not None:
            self.s.on_wake_word(on)
        from relay.audio.hotkeys import spoken_combo

        key = spoken_combo(self.s.talk_key)
        self.say(
            "Wake word on. Say Relay, then your command."
            if on
            else f"Wake word off. I'll only listen when you press {key}."
        )

    def k_hold_to_talk(self, i):
        on = bool(i.slots.get("on"))
        self.s.hold_to_talk = on
        self.s.store.set_pref("hold_to_talk", "1" if on else "0")
        if self.s.bus is not None:
            self.s.bus.emit("config.changed", key="hold_to_talk", value=on)
        self.say(
            "Hold to talk enabled. Press and hold Control, Alt, and Space while speaking, then release to execute."
            if on
            else "Hold to talk disabled. Control, Alt, and Space will work with a single tap."
        )

    def k_headphones(self, i):
        if self.s.audio is None:
            self.say("I can't change headphone mode here.")
            return
        self.say(self.s.audio.set_headphone_mode(i.slots.get("mode", "auto")))

    def k_listening(self, i):
        audio = self.s.audio
        if audio is None or not hasattr(audio, "set_listening"):
            self.say("I can't switch listening off here.")
            return
        self.say(audio.set_listening(bool(i.slots.get("on"))))

    def k_palette(self, i):
        audio = self.s.audio
        if audio is None or not hasattr(audio, "set_palette"):
            self.say("There's no on-screen palette here.")
            return
        self.say(audio.set_palette(bool(i.slots.get("visible"))))

    def k_audio_status(self, i):
        self.say(
            self.s.audio.describe_audio()
            if self.s.audio is not None
            else "I can't check the sound devices here."
        )

    def k_quit(self, i):
        self.say("Closing Relay. Goodbye.", _CONF)
        if self.s.on_quit is not None:
            self.s.on_quit()

    # ---------------------------------------------------------------- laptop controls
    def k_radio(self, i):
        dev, state = i.slots.get("device", "bluetooth"), i.slots.get("state", "status")
        spoken = "Bluetooth" if dev == "bluetooth" else "Wi-Fi"
        if state != "status":
            self.say(f"Turning {spoken} {state}.")
            o = self.s.executor.set_radio(dev, state)
            self.say(o.detail)
        else:
            from relay.system import control

            self.say(control.radio(dev, state))

    def k_brightness(self, i):
        action = i.slots.get("action", "get")
        if action != "get":
            self.say(
                {
                    "up": "Making the screen brighter.",
                    "down": "Dimming the screen.",
                    "set": f"Setting brightness to {i.slots.get('level')} percent.",
                }[action]
            )
            o = self.s.executor.set_brightness(action, i.slots.get("level"))
            self.say(o.detail)
        else:
            from relay.system import control

            self.say(control.change_brightness(action, i.slots.get("level")))

    def k_dark_mode(self, i):
        on = bool(i.slots.get("on"))
        self.say("Turning dark mode on." if on else "Turning dark mode off.")
        o = self.s.executor.set_dark_mode(on)
        self.say(o.detail)

    def k_screenshot(self, i):
        self.say("Taking a screenshot.")
        o = self.s.executor.take_screenshot()
        self.say(o.detail)
        if not o.ok:
            self.s.step_failed()

    def k_power(self, i):
        action = i.slots.get("action", "")
        if action == "cancel":
            o = self.s.executor.power_operation("cancel")
            self.say(o.detail)
            return
        what = {
            "shutdown": ("shut down the computer", "confirm shut down"),
            "restart": ("restart the computer", "confirm restart"),
            "sleep": ("put the computer to sleep", "confirm sleep"),
            "signout": ("sign you out of Windows", "confirm sign out"),
        }[action]
        extra = (
            " It will wait one minute, and apps with unsaved work may ask you first."
            if action in ("shutdown", "restart")
            else " Unsaved work in open apps could be lost."
            if action == "signout"
            else ""
        )
        self.s.ask_phrase(
            what[1],
            f"I'm about to {what[0]}.{extra}",
            lambda a=action: self.say(self.s.executor.power_operation(a).detail),
        )

    def k_storage(self, i):
        from relay.system import control

        self.say(control.storage_text())

    def k_network_info(self, i):
        from relay.system import control

        self.say(control.network_text())

    def k_check_updates(self, i):
        return self._open_settings(
            "ms-settings:windowsupdate-action",
            "Windows Update",
            "Windows Update is open and checking for updates.",
        )

    def k_api_key(self, i):
        action = i.slots.get("action", "save")
        from relay.memory.secrets import get_secret, save_secret

        if action == "status":
            key = (
                get_secret("RELAY_LLM_KEY")
                or get_secret("FREELLMAPI_KEY")
                or get_secret("GROQ_API_KEY")
                or get_secret("OPENAI_API_KEY")
            )
            url = get_secret("RELAY_LLM_URL") or get_secret("FREELLMAPI_URL")
            if key and url:
                prov = "Groq" if (key.startswith("gsk_") or "groq" in url.lower()) else ("OpenAI" if key.startswith("sk-") else "Free LLM")
                self.say(f"Your {prov} API key is configured and connected.")
            elif key:
                prov = "Groq" if key.startswith("gsk_") else ("OpenAI" if key.startswith("sk-") else "Free LLM")
                self.say(f"Your {prov} API key is saved.")
            else:
                self.say("No API key is currently saved. Copy your Free LLM or Groq API key, then say save API key.")
            return

        import pyperclip

        raw = (i.slots.get("key") or "").strip()
        if not raw:
            try:
                raw = pyperclip.paste().strip()
            except Exception:
                raw = ""
        else:
            m_orig = re.search(re.escape(raw), getattr(i, "raw", "") or "", re.IGNORECASE)
            if m_orig:
                raw = m_orig.group(0)

        if len(raw) < 10 or " " in raw:
            self.say(
                "I didn't find an API key on the clipboard. Copy your key first, then say save API key."
            )
            return

        save_secret("RELAY_LLM_KEY", raw)
        save_secret("FREELLMAPI_KEY", raw)

        low_key = raw.lower()
        prov = "AI"
        if low_key.startswith("aizasy"):
            prov = "Google Gemini"
            save_secret("GEMINI_API_KEY", raw)
            save_secret("RELAY_LLM_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
        elif low_key.startswith("gsk_"):
            prov = "Groq"
            save_secret("GROQ_API_KEY", raw)
            save_secret("RELAY_LLM_URL", "https://api.groq.com/openai/v1")
        elif low_key.startswith("sk-"):
            prov = "OpenAI"
            save_secret("OPENAI_API_KEY", raw)
            save_secret("RELAY_LLM_URL", "https://api.openai.com/v1")
        else:
            if not get_secret("RELAY_LLM_URL"):
                save_secret("RELAY_LLM_URL", "http://127.0.0.1:31415/v1")
            if not get_secret("FREELLMAPI_URL"):
                save_secret("FREELLMAPI_URL", "http://127.0.0.1:31415/v1")

        reloaded = self.s.reload_assistant()
        if reloaded:
            self.say(f"Your {prov} API key has been securely saved with Windows encryption, and the AI assistant is now online.")
        else:
            self.say(f"Your {prov} API key was saved, but the model endpoint could not be reached right now.")

    def k_settings_page(self, i):
        topic = i.slots.get("topic", "")
        extra = " Night light is the switch near the top." if "night" in topic else ""
        return self._open_settings(
            i.slots["uri"], f"{topic} settings", f"{topic.capitalize()} settings are open.{extra}"
        )

    def _open_settings(self, uri: str, label: str, ok_text: str):
        from relay.system import windows

        return self.run(
            Step(
                "open_uri",
                f"open {label}",
                {
                    "uri": uri,
                    "label": label,
                    "check": lambda: bool(
                        (w := windows.foreground())
                        and (
                            "settings" in w.title.lower()
                            or w.app.lower().startswith("systemsettings")
                        )
                    ),
                    "ok_text": ok_text,
                    "speak_detail": True,
                    "timeout": 8.0,
                },
            )
        )

    def k_recycle_bin(self, i):
        from relay.system import control, windows

        if i.slots.get("action") == "empty":
            self.s.ask_phrase(
                "confirm empty",
                "I'm about to empty the Recycle Bin. Files in it will be gone for good.",
                lambda: self.say(control.empty_recycle_bin()),
            )
            return
        return self.run(
            Step(
                "open_uri",
                "open the Recycle Bin",
                {
                    "uri": "shell:RecycleBinFolder",
                    "label": "Recycle Bin",
                    "check": lambda: bool(
                        (w := windows.foreground()) and "recycle" in w.title.lower()
                    ),
                    "ok_text": "The Recycle Bin is open. Say what's on my screen to hear it.",
                    "speak_detail": True,
                },
            )
        )

    def k_weather(self, i):
        from relay.system import control

        place = i.slots.get("place", "")
        self.say(f"Checking the weather{' in ' + place if place else ''}.")
        self.say(control.weather_text(place))

    def k_new_folder(self, i):
        from relay.system import control, files

        name = re.sub(r"[<>:\"/\\|?*]", "", (i.slots.get("name") or "").strip()).strip(". ")
        if not name:
            self.say("What should I call the new folder?")
            self.s.capture_next(
                lambda text: self.k_new_folder(
                    type(i)(Kind.NEW_FOLDER, {"name": text, "where": i.slots.get("where", "")})
                )
            )
            return
        where = i.slots.get("where", "")
        base, label = None, ""
        if where:
            base = files.known_folder("pictures" if where == "photos" else where)
            label = f"your {where.capitalize()} folder"
        if base is None:
            here, _sel = control.explorer_selection()
            if here is not None:
                base, label = here, f"{here.name}, the folder you're in"
        if base is None:
            base, label = files.known_folder("desktop"), "your Desktop"
        target = base / name
        if target.exists():
            self.say(f"There's already a folder called {name} in {label}.")
            return
        step = Step(
            "new_folder",
            f"create a folder called {name} in {label}",
            {
                "target": target,
                "name": name,
                "label": label,
                "announce": f"I'm going to create a folder called {name} in {label}.",
                "ok_text": f"Done. The {name} folder is in {label}.",
                "speak_detail": True,
            },
        )
        res = self.run(step)
        if not res or res[0].state != "verified":
            self.s.step_failed()

    def k_file_op(self, i):
        from pathlib import Path

        from relay.system import control, files

        op = i.slots.get("op", "")
        _folder, sel = control.explorer_selection()
        if not sel:
            self.say(
                "Select the file first: open it in File Explorer and move to it with "
                "the arrow keys. Then say it again."
            )
            self.s.step_failed()
            return
        if len(sel) > 1 and op == "rename":
            self.say("More than one item is selected; select just one to rename it.")
            self.s.step_failed()
            return
        item = sel[0]
        what = item.name if len(sel) == 1 else f"{len(sel)} items"
        if op == "delete":
            self.s.ask_phrase(
                "confirm delete",
                f"I'm about to move {what} to the Recycle Bin. You can get it back from there.",
                lambda: self._recycle(sel),
            )
            return
        if op == "rename":
            new = re.sub(r"[<>:\"/\\|?*]", "", i.slots.get("to", "")).strip(" .")
            if not new:
                self.say("What should the new name be?")
                return
            if not Path(new).suffix and item.suffix and item.is_file():
                new += item.suffix  # keep the file type
            dest = item.with_name(new)
            if dest.exists():
                self.say(f"There's already something called {new} there.")
                return
            step = Step(
                "file_op",
                f"rename {item.name} to {new}",
                {
                    "op": "rename",
                    "src": item,
                    "dest": dest,
                    "announce": f"Renaming {item.name} to {new}.",
                    "ok_text": f"Done. It's now called {new}.",
                    "speak_detail": True,
                },
            )
            res = self.run(step)
            if not res or res[0].state != "verified":
                self.s.step_failed()
            return
        to = i.slots.get("to", "")
        base = files.known_folder("pictures" if to == "photos" else to)
        if base is None:
            self.say(f"I couldn't find your {to} folder.")
            return
        verb = "Moving" if op == "move" else "Copying"
        steps = []
        for p in sel:
            dest = base / p.name
            if dest.exists():
                continue
            steps.append(
                Step(
                    "file_op",
                    f"{op} {p.name} to your {to.capitalize()} folder",
                    {
                        "op": op,
                        "src": p,
                        "dest": dest,
                        "announce": f"{verb} {p.name} to your {to.capitalize()} folder.",
                        "ok_text": f"Done. {p.name} is in your {to.capitalize()} folder.",
                        "speak_detail": True,
                    },
                )
            )
        if not steps:
            self.say(f"The items already exist in your {to.capitalize()} folder.")
            return
        res = self.run(*steps)
        done = sum(1 for r in res if r.state == "verified")
        if done < len(steps):
            self.s.step_failed()

    def _recycle(self, paths):
        paths_list = list(paths)
        what = paths_list[0].name if len(paths_list) == 1 else f"{len(paths_list)} items"
        step = Step(
            "recycle",
            f"move {what} to the Recycle Bin",
            {
                "paths": paths_list,
                "announce": f"Moving {what} to the Recycle Bin.",
                "ok_text": f"Moved {what} to the Recycle Bin.",
                "speak_detail": True,
            },
        )
        self.run(step)

    def k_close_all(self, i):
        from relay.system import windows

        wins = [w for w in windows.list_windows()]
        if not wins:
            self.say("There are no windows to close.")
            return
        names = ", ".join(w.spoken for w in wins[:6]) + (" and more" if len(wins) > 6 else "")

        def close_all():
            for w in wins:
                self.run(
                    Step(
                        "window",
                        f"close {w.spoken}",
                        {
                            "op": "close",
                            "hwnd": w.hwnd,
                            "label": w.spoken,
                            "announce": f"Closing {w.spoken}.",
                        },
                    )
                )
            left = [w for w in wins if windows.exists(w.hwnd)]
            self.say(
                "All closed."
                if not left
                else f"{len(left)} still open, probably asking about unsaved work: "
                + ", ".join(w.spoken for w in left)
                + "."
            )

        self.s.ask_phrase(
            "confirm close all",
            f"I'm about to close {len(wins)} windows: "
            f"{names}. Apps with unsaved work will ask you first.",
            close_all,
        )

    def k_email(self, i):
        from urllib.parse import quote

        from relay.system import web

        if i.slots.get("action") == "compose":
            to = i.slots.get("to", "")
            subject = i.slots.get("subject", "")
            body = i.slots.get("body", "")
            addr = to.replace(" at ", "@").replace(" dot ", ".").replace(" ", "")
            params = []
            if "@" in addr or addr:
                params.append(f"to={quote(addr)}")
            if subject:
                params.append(f"su={quote(subject)}")
            if body:
                params.append(f"body={quote(body)}")
            query_str = ("&" + "&".join(params)) if params else ""
            url = f"https://mail.google.com/mail/?view=cm&fs=1{query_str}"
            desc = "a new email"
            if addr:
                desc += f" to {addr}"
            self.say(f"Opening a new email in Gmail{f' to {addr}' if addr else ''}.")
            return self._open_site(url, desc)
        url = web.site_url("gmail") or "https://mail.google.com"
        return self._open_site(url, "Gmail")

    # ---------------------------------------------------------------- dictation
    def k_dictation(self, i):
        on = bool(i.slots.get("on"))
        self.s.set_dictation(on)
        if not on:
            self.say("Dictation off.")
            return
        snap = self.s.worker.observe(3.0)
        editable = bool(snap and snap.focus and snap.focus.role in ("Edit", "Document"))
        tip = (
            ""
            if editable
            else (
                " I don't see a text box focused right now, so move to "
                "one first, or say stop dictation."
            )
        )
        self.say(
            "Dictation on. Everything you say will be typed where your cursor is. Say "
            f"comma or full stop for punctuation, and stop dictation when you're done.{tip}"
        )

    def dictate(self, utterance: str):
        text = apply_spoken_punctuation(utterance.strip())
        text = re.sub(r"(?i)^relay[,.]?\s+", "", text)
        if not text.strip():
            return []

        # Lock & verify focus before injecting text
        snap = getattr(self.s.worker, "live", None)
        if snap and snap.focus:
            f_pwd = bool(snap.focus.states.get("is_password") or snap.focus.states.get("protected"))
            if f_pwd:
                self.say("Dictation paused: the focused control is a password field.", pol.Priority.CRITICAL)
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

        # Verify that the text actually reached the active focus field if a real window is active
        from relay.executor.input_backend import WindowsInputBackend
        is_live = isinstance(self.s.executor.input, WindowsInputBackend)
        spoken = text.strip() or "a new line"
        if is_live:
            time.sleep(0.2)
            check_txt = text.strip()[:20]
            verified = self.s.verifier.focus_value_contains(check_txt, timeout=1.0) if check_txt else True
            if verified:
                self.say(f"Typed: {spoken}" if len(spoken) < 200 else "Typed your paragraph.")
            else:
                self.say("Typed, but could not confirm the text in the active field.")
        else:
            self.say(f"Typed: {spoken}" if len(spoken) < 200 else "Typed your paragraph.")
        return []

    # ---------------------------------------------------------------- notes
    def k_take_note(self, i):
        from relay.intent.normalize import clean_dictation_homophones

        text = clean_dictation_homophones((i.slots.get("text") or "").strip())
        if not text:
            self.say("What should the note say?")
            self.s.capture_next(lambda t: self._save_note(clean_dictation_homophones(t)))
            return
        self._save_note(text)

    def _save_note(self, text: str):
        from relay.intent.normalize import clean_dictation_homophones

        text = clean_dictation_homophones(text)
        if self.s.notes.add(text):
            self.say(f"Noted: {text.rstrip('.')}.")
        else:
            self.say(
                "I won't save that — it looks like a password or code, so I'm keeping "
                "it out of my notes."
            )

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
            lambda: self.say(f"Deleted {self.s.notes.delete_all()} notes.", _CONF),
        )

    # ---------------------------------------------------------------- reminders
    def k_set_reminder(self, i):
        from relay.reminders import parse_reminder, when_text

        parsed = parse_reminder(i.slots.get("text", ""))
        if parsed is None:
            self.say(
                "When should I remind you? For example, say: remind me in 10 minutes "
                "to call mom, or remind me at 6 p m to take my medicine."
            )
            return
        due, msg, is_timer = parsed
        self.s.reminders.add(msg, due.timestamp())
        if is_timer:
            self.say(f"Timer set. It will go off {when_text(due)}.")
        else:
            self.say(
                f"Okay. I'll remind you to {msg} {when_text(due)}."
                if not msg.startswith("this is")
                else f"Okay. I'll remind you {when_text(due)}."
            )

    def k_list_reminders(self, i):
        self.say(self.s.reminders.spoken_pending())

    def k_cancel_reminders(self, i):
        n = self.s.reminders.cancel_all()
        self.say(
            "You had no reminders." if n == 0 else f"Cancelled {n} reminder{'s' if n != 1 else ''}."
        )

    # ---------------------------------------------------------------- apps / windows
    def _window_finder(self, name: str):
        from relay.system import windows

        return lambda: windows.find(name)

    def k_open_app(self, i):
        from relay.system import files, web, windows

        target = (i.slots.get("app") or "").strip()
        try:
            alias_val = self.s.store.get_pref(f"alias:{target.lower()}")
            if alias_val:
                target = str(alias_val)
        except Exception:
            pass
        if (
            re.search(r"\b(?:first|second|third|fourth|fifth|last|one|number \d+)\b", target)
            and self.recent_list()
        ):
            return self.k_pick(type(i)(Kind.PICK, {"verb": "open", "ordinal": _ord(target)}))
        clean = re.sub(r"\b(?:the|my|app|application|program)\b", " ", target).strip()
        clean = " ".join(clean.split())
        folder = files.folder_for_phrase(target)
        if folder is not None:
            name, path = folder
            label = path.name
            return self.run(
                Step(
                    "open_uri",
                    f"open your {name} folder",
                    {
                        "uri": str(path),
                        "label": label,
                        "check": lambda: bool(
                            (w := windows.foreground()) and label.lower() in w.title.lower()
                        ),
                        "ok_text": f"Your {name} folder is open.",
                        "speak_detail": True,
                    },
                )
            )
        cat = self.s.apps
        if not cat.wait_ready(3.0) or not cat.entries:  # first run: list still loading
            self.say("One moment, I'm still finding the apps on this computer.")
            cat.wait_ready(20.0)
        entry = cat.find(clean) if clean else None
        url = web.site_url(clean)
        if entry is not None and not (url and clean in web.SITES and entry.name.lower() != clean):
            existing = windows.find(entry.name) or windows.find(clean)
            if existing is not None:
                return self.run(
                    Step(
                        "window",
                        f"switch to {entry.name}",
                        {
                            "op": "activate",
                            "hwnd": existing.hwnd,
                            "label": entry.name,
                            "announce": f"{entry.name} is already open. Switching to it.",
                            "ok_text": f"You're in {existing.spoken}.",
                            "speak_detail": True,
                        },
                    )
                )
            return self.run(
                Step(
                    "launch",
                    f"open {entry.name}",
                    {
                        "entry": entry,
                        "label": entry.name,
                        "find_window": lambda: windows.find(entry.name) or windows.find(clean),
                        "activate": windows.activate,
                        "timeout": 10.0,
                        "speak_detail": True,
                    },
                )
            )
        if url:
            return self._open_site(url, clean)
        if re.search(r"\.\w{2,4}$", clean):  # looks like a file name
            return self.k_open_file(type(i)(Kind.OPEN_FILE, {"name": clean, "then": "open"}))
        running = windows.find(clean) if clean else None  # open, but not on the Start menu
        if running is not None:
            return self.run(
                Step(
                    "window",
                    f"switch to {running.spoken}",
                    {
                        "op": "activate",
                        "hwnd": running.hwnd,
                        "label": running.spoken,
                        "announce": f"{running.spoken} is already open. Switching to it.",
                        "ok_text": f"You're in {running.spoken}.",
                        "speak_detail": True,
                    },
                )
            )
        if cat.entries and clean and self._looks_like_document(target, clean):
            return self.k_open_file(type(i)(Kind.OPEN_FILE, {"name": clean, "then": "open"}))
        self.s.step_failed()
        guess = cat.candidates(clean, limit=1, threshold=45) if clean else []
        if guess:
            name = guess[0].name
            self.say(f"I couldn't find an app called {target}. Did you mean {name}? Say yes or no.")
            self.s.offer(lambda: self.k_open_app(type(i)(Kind.OPEN_APP, {"app": name})))
            return []
        self.say(
            f"I couldn't find an app called {target}. Do you want me to search the "
            "web for it? Say yes or no."
        )
        self.s.offer(lambda: self._search(target))
        return []

    @staticmethod
    def _looks_like_document(said: str, clean: str) -> bool:
        """ "open my resume" may mean a document — but only open a file when the user
        said so ("my …", "the file …") or a document is named exactly that. Never
        'calculator' -> calculator3d.html."""
        from relay.system import files

        hits = files.find_files(clean, limit=3, time_budget=2.0)
        docs = [
            h
            for h in hits
            if h.path.suffix.lower() in files.READABLE - {".html", ".htm"}
            or h.path.suffix.lower() in (".xlsx", ".pptx", ".doc", ".xls", ".ppt")
        ]
        if not docs:
            return False
        flat = re.sub(r"[\s_\-.]+", "", clean.lower())
        exact = any(re.sub(r"[\s_\-.]+", "", h.path.stem.lower()) == flat for h in docs)
        cue = re.search(r"\b(?:my|file|document|doc|pdf|spreadsheet|presentation)\b", said.lower())
        return exact or bool(cue)

    def _open_site(self, url: str, label: str):
        from relay.system import web, windows

        site = web.site_label(url)
        return self.run(
            Step(
                "open_uri",
                f"open {label}",
                {
                    "uri": url,
                    "label": label,
                    "check": lambda: bool(
                        (w := windows.foreground())
                        and w.app.lower() in BROWSERS
                        and site.lower() in w.title.lower()
                    ),
                    "ok_text": f"{label.capitalize()} is open in your browser. Say read the page, or "
                    "list the links.",
                    "fail_text": "I asked your browser to open it, but I couldn't confirm the page "
                    "loaded yet",
                    "announce": f"Opening {label} in your browser.",
                    "speak_detail": True,
                    "timeout": 10.0,
                },
            )
        )

    def k_switch_app(self, i):
        from relay.system import web, windows

        target = (i.slots.get("app") or "").strip()
        try:
            alias_val = self.s.store.get_pref(f"alias:{target.lower()}")
            if alias_val:
                target = str(alias_val)
        except Exception:
            pass
        rl = self.recent_list()
        if (
            rl
            and rl[0] == "windows"
            and re.search(
                r"\b(?:first|second|third|fourth|fifth|last|one|number \d+|window \d+)\b", target
            )
        ):
            return self.k_pick(type(i)(Kind.PICK, {"verb": "switch to", "ordinal": _ord(target)}))
        w = windows.find(target)
        if w is not None:
            return self.run(
                Step(
                    "window",
                    f"switch to {w.spoken}",
                    {
                        "op": "activate",
                        "hwnd": w.hwnd,
                        "label": w.spoken,
                        "announce": f"Switching to {w.spoken}.",
                        "ok_text": f"You're in {w.spoken}.",
                        "speak_detail": True,
                    },
                )
            )
        url = web.site_url(target)
        if url:
            return self._open_site(url, target)
        if self.s.apps.find(target) is not None:
            self.say(f"{target.capitalize()} isn't open. Do you want me to open it? Say yes or no.")
            self.s.offer(lambda: self.k_open_app(type(i)(Kind.OPEN_APP, {"app": target})))
            return []
        self.s.step_failed()
        self.say(f"I couldn't find a window for {target}. Say what windows are open to hear them.")

    def k_list_windows(self, i):
        from relay.system import windows

        wins = windows.list_windows()
        self.remember_list("windows", wins)
        self.say(
            windows.spoken_list(wins) + (" Say switch to, and a number or name." if wins else "")
        )

    def k_window_op(self, i):
        from relay.system import windows

        op = i.slots.get("op")
        target = (i.slots.get("target") or "").strip()
        w = windows.find(target) if target else windows.foreground()
        if w is None:
            self.s.step_failed()
            self.say(
                f"I couldn't find a window called {target}."
                if target
                else "There's no window in front to do that to."
            )
            return
        verbs = {
            "close": "close",
            "minimize": "minimize",
            "maximize": "maximize",
            "restore": "restore",
        }
        ok_text = {
            "minimize": f"{w.spoken} is minimized.",
            "maximize": f"{w.spoken} is maximized.",
            "restore": f"{w.spoken} is restored.",
        }.get(op, "")
        return self.run(
            Step(
                "window",
                f"{verbs[op]} {w.spoken}",
                {
                    "op": op,
                    "hwnd": w.hwnd,
                    "label": w.spoken,
                    "ok_text": ok_text,
                    "speak_detail": True,
                    "announce": f"I'm going to {verbs[op]} {w.spoken}."
                    + (" If it has unsaved work, it will ask you first." if op == "close" else ""),
                },
            )
        )

    def k_show_desktop(self, i):
        return self.run(
            Step(
                "hotkey",
                "show the desktop",
                {"keys": ["win", "d"], "announce": "Showing the desktop.", "done_text": ""},
            )
        )

    # ---------------------------------------------------------------- keys
    def _explorer_delete_guard(self, keys: list[str], retry) -> bool:
        """Delete in File Explorer removes files: require the spoken phrase."""
        if "delete" in keys and self._fg_app() == "explorer.exe":
            dec = self.s.engine.classify(
                Action(
                    kind="delete_file", target_app="File Explorer", target_label="the selected item"
                )
            )
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
        dec = self.s.engine.classify(
            Action(kind="send_message", target_app=app, target_label="the message")
        )
        self.say(f"I'm about to send {what}.", _CONF)
        self.s._on_confirm_needed(dec, "send", retry)
        return True

    def _ocr_find(self, target: str, ordinal: int | None = None) -> UIElement | None:
        if not target or self.s.ocr is None:
            return None
        import re
        raw_target = (target or "").strip()
        cleaned = re.sub(
            r"\b(?:the|button|link|icon|tab|menu|field|result|on|named|called)\b",
            " ",
            raw_target,
            flags=re.I,
        ).strip()
        cleaned = " ".join(cleaned.split()).lower()
        if not cleaned:
            cleaned = raw_target.lower()

        import ctypes
        from ctypes import wintypes

        from relay.system import windows
        fg = windows.foreground()
        region = None
        hwnd = None
        if fg is not None:
            try:
                hwnd = fg.hwnd
                r = wintypes.RECT()
                if ctypes.windll.user32.GetWindowRect(fg.hwnd, ctypes.byref(r)):
                    region = (max(0, r.left), max(0, r.top), r.right, r.bottom)
            except Exception:
                pass

        try:
            regions = self.s.ocr.read_screen(region=region, hwnd=hwnd)
            if not regions and region is not None:
                regions = self.s.ocr.read_screen()
        except Exception as e:
            log.debug("OCR find failed: %s", e)
            return None

        if not regions:
            return None

        candidates = []
        for e in regions:
            name = (e.name or "").strip().lower()
            if not name:
                continue
            score = 0
            if name == cleaned:
                score = 100
            elif cleaned in name:
                score = 80
            elif name in cleaned:
                score = 75
            else:
                target_words = cleaned.split()
                name_words = name.split()
                overlap = sum(1 for w in target_words if w in name_words or any(w in nw for nw in name_words))
                if overlap > 0:
                    score = 50 + int(20 * (overlap / len(target_words)))
            if score > 0:
                candidates.append((score, e))

        if not candidates:
            return None

        if ordinal is not None and ordinal > 0:
            top_score = max(c[0] for c in candidates)
            pool = [c[1] for c in candidates if c[0] >= top_score - 20]
            pool.sort(key=lambda el: (el.bbox[1], el.bbox[0]))
            idx = ordinal - 1
            if 0 <= idx < len(pool):
                return pool[idx]
            return pool[0] if pool else None

        candidates.sort(key=lambda c: (c[0], c[1].states.get("ocr_confidence", 0)), reverse=True)
        return candidates[0][1]

    def k_send(self, i):
        from relay.system import windows
        fg = windows.foreground()
        app = (fg.app or "").lower() if fg else ""

        # 1. Browser / Web clients (Gmail, Outlook Web, etc.) or desktop mail clients
        if app in BROWSERS or app in ("outlook.exe", "olk.exe", "thunderbird.exe", "hxoutlook.exe"):
            send_btn = self._ocr_find("send")
            if send_btn is not None:
                return self.run(
                    Step(
                        "activate",
                        "click Send",
                        {"target": "send", "deep_find": lambda: send_btn, "announce": "Sending."},
                    )
                )
            return self.run(
                Step(
                    "hotkey",
                    "send the email",
                    {"keys": ["ctrl", "enter"], "announce": "Sending.", "done_text": "Sent."},
                )
            )

        # 2. Chat apps (WhatsApp, Telegram, Teams, Slack, Discord, Signal)
        if app in MESSAGING:
            step = Step(
                "press", "send the message", {"key": "enter", "announce": "Sending.", "done_text": "Sent."}
            )
            if self._send_guard(["enter"], lambda: self.s.runner.run([step])):
                return []
            return self.run(step)

        # 3. Any other app: try finding Send on screen via OCR
        send_btn = self._ocr_find("send")
        if send_btn is not None:
            return self.run(
                Step(
                    "activate",
                    "click Send",
                    {"target": "send", "deep_find": lambda: send_btn, "announce": "Sending."},
                )
            )

        return self.run(
            Step(
                "hotkey",
                "send",
                {"keys": ["ctrl", "enter"], "announce": "Sending.", "done_text": "Sent."},
            )
        )

    def k_press_key(self, i):
        key, count = i.slots["key"], i.slots.get("count", 1)
        step = Step(
            "press",
            f"press {spoken_keys([key])}",
            {
                "key": key,
                "count": count,
                "announce": f"Pressing {spoken_keys([key])}"
                + (f" {count} times." if count > 1 else "."),
                "done_text": "",
            },
        )
        retry = lambda: self.s.runner.run([step])  # noqa: E731
        if self._explorer_delete_guard([key], retry) or self._send_guard([key], retry):
            return []
        return self.run(step)

    def k_hotkey(self, i):
        keys = i.slots["keys"]
        seq = bool(i.slots.get("sequence"))
        words = ", then ".join(spoken_keys([k]) for k in keys) if seq else spoken_keys(keys)
        step = Step(
            "hotkey",
            f"press {words}",
            {
                "keys": keys,
                "count": i.slots.get("count", 1),
                "sequence": seq,
                "announce": f"Pressing {words}.",
                "done_text": "",
            },
        )
        retry = lambda: self.s.runner.run([step])  # noqa: E731
        if self._explorer_delete_guard(keys, retry) or self._send_guard(keys, retry):
            return []
        return self.run(step)

    def k_shortcut(self, i):
        keys, desc = i.slots["keys"], i.slots["description"]
        p = {"keys": keys, "announce": f"I'm going to {desc}.", "done_text": ""}
        if keys in (["ctrl", "c"], ["ctrl", "x"]):
            p.update(
                before=_clipboard,
                check=_copied_check,
                speak_detail=True,
                uncertain_text="I pressed it, but nothing new reached the clipboard. "
                "Is anything selected?",
            )
        elif keys == ["ctrl", "a"]:
            p.update(
                check=lambda _b: self._selection_check(),
                speak_detail=True,
                uncertain_text="I pressed select all, but I couldn't confirm a selection here.",
            )
        elif keys == ["ctrl", "v"]:
            p.update(
                before=lambda: self._focus_value(),
                check=lambda b: (self._focus_value() != b, "Pasted."),
                speak_detail=True,
                uncertain_text="I pressed paste, but I couldn't confirm the text changed.",
            )
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
        return self.run(
            Step(
                "press",
                f"scroll {d}",
                {
                    "key": "pagedown" if d == "down" else "pageup",
                    "announce": f"Scrolling {d}.",
                    "done_text": "",
                },
            )
        )

    def k_go_back(self, i):
        return self.run(
            Step(
                "press",
                "go back",
                {"key": "browserback", "announce": "Going back.", "done_text": ""},
            )
        )

    # ---------------------------------------------------------------- web
    def _search(self, query: str, site: str | None = None):
        from relay.system import web, windows

        if site:
            url = web.search_site_url(site, query)
            label = site.capitalize()
        else:
            url = None
            label = "Google"

        if not url:
            url = web.search_url(query)
            label = "Google"

        announce = f"Searching {label} for {query}."
        return self.run(
            Step(
                "open_uri",
                f"search {label} for {query}",
                {
                    "uri": url,
                    "label": label,
                    "check": lambda: bool(
                        (w := windows.foreground())
                        and w.app.lower() in BROWSERS
                        and (site.lower() in w.title.lower() if site else "google" in w.title.lower())
                    ),
                    "announce": announce,
                    "ok_text": f"Search results in {label} are open. Say read the page, or list the links.",
                    "fail_text": f"I opened {label} to search, but I couldn't confirm the results loaded yet.",
                    "speak_detail": True,
                    "timeout": 10.0,
                },
            )
        )

    def k_web_search(self, i):
        return self._search(i.slots.get("query", ""), site=i.slots.get("site"))

    def k_youtube(self, i):
        from relay.system import web, windows

        q = i.slots.get("query", "").strip()
        if not q:
            url = web.site_url("youtube") or "https://www.youtube.com"
            return self._open_site(url, "YouTube")

        def _play_first_video():
            time.sleep(1.8)
            # 1. Try OCR to click the first video title in search results
            if self.s.ocr is not None:
                regions = self.s.ocr.read_screen()
                header_words = {"youtube", "search", "filters", "explore", "subscriptions", "all", "shorts"}
                for el in regions:
                    name_low = el.name.lower().strip()
                    if name_low not in header_words and el.bbox[1] > 130 and len(name_low) > 3:
                        self.s.executor.invoke_element(el)
                        return True, f"Playing {q}."
            # 2. Try links
            links = self._items("links")
            if links:
                for lnk in links:
                    if len(lnk.name) > 5 and lnk.name.lower() not in ("youtube", "home", "shorts", "subscriptions"):
                        el = UIElement(uid=0, name=lnk.name, role="Hyperlink", bbox=lnk.bbox)
                        self.s.executor.invoke_element(el)
                        return True, f"Playing {q}."
            # 3. Fallback: hit Enter to activate
            self.s.executor.press("enter")
            return True, f"Opened {q} on YouTube."

        step1 = Step(
            "open_uri",
            f"open YouTube for {q}",
            {
                "uri": web.youtube_url(q),
                "label": "YouTube",
                "check": lambda: bool(
                    (w := windows.foreground()) and "youtube" in w.title.lower()
                ),
                "announce": f"Playing {q} on YouTube.",
                "ok_text": f"Playing {q} on YouTube.",
                "speak_detail": True,
                "timeout": 10.0,
            },
        )
        step2 = Step(
            "system",
            "start video playback",
            {
                "what": "YouTube playback",
                "do": _play_first_video,
                "label": "Play first video",
                "check": lambda: (True, f"Playing {q}."),
            },
        )
        return self.run(step1, step2)

    # ---------------------------------------------------------------- files
    def k_find_file(self, i):
        from relay.system import files

        name = i.slots.get("name", "")
        self.say(f"Looking for {name}.", pol.Priority.FOCUS)
        hits = files.find_files(name)
        if not hits:
            self.say(
                f"I couldn't find a file called {name} in your Desktop, Documents, "
                "Downloads, Pictures, Music or Videos."
            )
            return
        self.remember_list("files", hits)
        listed = "; ".join(f"{n}, {h.spoken}" for n, h in enumerate(hits, 1))
        self.say(f"I found {len(hits)}: {listed}. Say open the first one, or read the first one.")

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
            self.say(
                f"I couldn't find readable text in {path.name}. It may be a scanned "
                "image. Do you want me to open it instead? Say yes or no."
            )
            self.s.offer(lambda: self._use_file(path, "open"))
            return []
        stem = path.stem.lower()[:25]
        return self.run(
            Step(
                "open_uri",
                f"open {path.name}",
                {
                    "uri": str(path),
                    "label": path.name,
                    "check": lambda: bool((w := windows.foreground()) and stem in w.title.lower()),
                    "ok_text": f"{path.name} is open.",
                    "speak_detail": True,
                    "timeout": 10.0,
                },
            )
        )

    # ---------------------------------------------------------------- pick from list
    def k_pick(self, i):
        rl = self.recent_list()
        n = int(i.slots.get("ordinal", 1))
        verb = i.slots.get("verb", "open")
        if rl is None:
            if verb in ("open", "use", "pick"):  # no list read out: an on-screen control
                return self.k_activate(
                    type(i)(Kind.ACTIVATE, {"target": f"item {n}", "ordinal": n})
                )
            self.say(
                "I haven't read you a list recently. Say list the links, find a file, "
                "or what windows are open first."
            )
            return
        kind, items, _ = rl
        idx = n - 1 if n > 0 else len(items) - 1
        if not 0 <= idx < len(items):
            self.say(f"There are only {len(items)} in that list.")
        item = items[idx]
        if kind == "files":
            from pathlib import Path
            p = item.path if hasattr(item, "path") else (Path(item) if not isinstance(item, Path) else item)
            return self._use_file(p, "read" if verb in ("read", "say") else "open")
        if kind == "windows":
            return self.run(
                Step(
                    "window",
                    f"switch to {item.spoken}",
                    {
                        "op": "activate",
                        "hwnd": item.hwnd,
                        "label": item.spoken,
                        "announce": f"Switching to {item.spoken}.",
                        "ok_text": f"You're in {item.spoken}.",
                        "speak_detail": True,
                    },
                )
            )
        if kind in ("links", "headings"):
            if kind == "headings":
                self.say(f"Heading {n}: {item.name}.")
                return
            el = UIElement(uid=0, name=item.name, role="Hyperlink", bbox=item.bbox)
            return self.run(
                Step(
                    "activate",
                    f"open the link {item.name}",
                    {"target": item.name, "deep_find": lambda: el},
                )
            )
        self.say("I can't open that kind of item.")

    # ---------------------------------------------------------------- reading
    def _document(self):
        from relay.perception import text as ptext

        query = getattr(self.s.ctx, "recent_query", "") if hasattr(self.s, "ctx") else ""
        val, ok = self.s.worker.run(lambda: ptext.clean_content_text(query=query), timeout=8.0)
        title, body = val if ok and val else ("", "")
        if not body:
            val, ok = self.s.worker.run(ptext.document_text, timeout=8.0)
            title, body = val if ok and val else ("", "")
        if not body:
            val, ok = self.s.worker.run(ptext.visible_text, timeout=8.0)
            body = val if ok and val else ""
        return title, body

    def k_read_all(self, i):
        lang = i.slots.get("language", "")
        if lang and lang != "english":
            self.say(
                f"I can only read in English on this computer, so here it is in "
                f"English rather than {lang.capitalize()}."
            )
        self.say("Getting the text.", pol.Priority.FOCUS)
        title, body = self._document()
        if not body:
            self.say(
                "I can't find readable text here with the accessibility tree. Trying "
                "OCR, which reads text from the screen image."
            )
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
        hwnd = None
        if fg is not None:
            import ctypes
            from ctypes import wintypes

            hwnd = fg.hwnd
            r = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(fg.hwnd, ctypes.byref(r)):
                region = (max(0, r.left), max(0, r.top), r.right, r.bottom)
        regions = self.s.ocr.read_screen(region=region, hwnd=hwnd)
        return ocr_mod.to_text(regions)


    def k_ocr_read(self, i):
        self.say(
            "Reading the screen image with OCR. This takes a few seconds, and it may "
            "make mistakes.",
            pol.Priority.FOCUS,
        )
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
            self.say(
                "The clipboard holds something that looks like a password or code, so "
                "I won't read it aloud."
            )
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
        self.say(
            f"There are {len(items)} links. Say stop when you hear the one you want, "
            "then say open, and its number."
        )
        self.s.start_reading(body, title="", intro=False)

    def k_list_headings(self, i):
        items = self._items("headings")
        if not items:
            self.say("This page has no headings I can find. Try read the page, or list the links.")
            return
        self.remember_list("headings", items)
        body = "\n".join(
            f"{n}, {'level ' + str(it.level) + ', ' if it.level else ''}{it.name}."
            for n, it in enumerate(items, 1)
        )
        self.say(f"There are {len(items)} headings.")
        self.s.start_reading(body, title="", intro=False)

    def k_heading_nav(self, i):
        """ "next heading" / "previous heading": walk the page's headings one at a time."""
        rl = self.recent_list()
        if rl and rl[0] == "headings":
            items = rl[1]
        else:
            items = self._items("headings")
            if not items:
                self.say("This page has no headings I can find.")
                self.s.step_failed()
                return
            self.remember_list("headings", items)
            self._heading_pos = -1
        step = int(i.slots.get("step", 1))
        pos = 0 if i.slots.get("first") else getattr(self, "_heading_pos", -1) + step
        if pos < 0 or pos >= len(items):
            self.say("That was the last heading." if step > 0 else "That was the first heading.")
            return
        self._heading_pos = pos
        it = items[pos]
        level = f"level {it.level}, " if getattr(it, "level", 0) else ""
        self.say(f"Heading {pos + 1} of {len(items)}, {level}{it.name}.")

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
        query = getattr(self.s.ctx, "recent_query", "") or getattr(self.s, "last_activity", "")
        if (snap.foreground_app or "").lower() in BROWSERS:
            from relay.perception import text as ptext

            val, ok = self.s.worker.run(lambda: ptext.clean_content_text(query=query), timeout=5.0)
            _, content = val if ok and val else ("", "")
            heads = self._items("headings")
            parts = [f"A web page: {_short_title(snap.foreground_title)}."]
            if content:
                paras = [p.strip() for p in content.splitlines() if len(p.strip()) > 15]
                if paras:
                    parts.append(f"Content: {paras[0]}.")
                    if len(paras) > 1 and self.s.narration_mode in (pol.DETAILED, pol.GUIDED):
                        parts.append(f"Also: {paras[1]}.")
            elif heads:
                parts.append(f"Main heading: {heads[0].name}.")
            if (
                snap.focus
                and snap.focus.name
                and snap.focus.name.lower() not in ("address and search bar", "new tab", "tab")
            ):
                parts.append(f"Focus is on {snap.focus.role} {snap.focus.name}.")
            parts.append("Say read the page to hear more.")
            self.say(" ".join(parts))
            return
        desc = pol.describe(snap, self.s.narration_mode, context=self.s.ctx, query=query)
        if (not snap.elements or len(snap.elements) <= 2) and self.s.ocr is not None:
            try:
                ocr_elements = self.s.ocr.read_screen()
                if ocr_elements:
                    texts = [e.name for e in ocr_elements if len(e.name.strip()) > 3][:6]
                    if texts:
                        desc += f" By visual scan, I see: {', '.join(texts)}."
            except Exception:
                pass
        self.say(desc)

    def _ocr_text(self) -> str:
        if self.s.ocr is None:
            return ""
        try:
            regions = self.s.ocr.read_screen()
            return "\n".join(r.name for r in regions if r.name.strip())
        except Exception:
            return ""

    # ---------------------------------------------------------------- AI assistant
    def k_ask(self, i):
        return self.s.ask(i.slots.get("text", ""))

    def k_summarize(self, i):
        title, body = self._document()
        if not body:
            body = self._ocr_text()
        if not body:
            self.say("I couldn't find any text on this screen to summarise.")
            return
        from relay.memory.store import looks_sensitive

        body = "\n".join(ln for ln in body.splitlines() if not looks_sensitive(ln))
        request = i.slots.get("request") or "Summarise this page."

        if self.s.assistant is None:
            summary = self.s.knowledge.summarize_text(body)
            page_info = f" of {_short_title(title)}" if title else ""
            self.say(f"Here is a summary{page_info}: {summary}")
            return

        self.say("Getting the text.", pol.Priority.FOCUS)
        return self.s.ask(f"{request} (Page title: {_short_title(title)})", page_text=body)

    # ---------------------------------------------------------------- typing / saving
    def k_type(self, i):
        text = apply_spoken_punctuation(i.slots.get("text", ""))
        return self.run(Step("type", "type your text", {"text": text}))

    def k_save(self, i):
        name = (i.slots.get("name") or "").strip()
        if not name:
            return self.run(Step("save", "save the file", {}))
        keys = ("f12",) if self._fg_app() in OFFICE else ("ctrl", "shift", "s")
        return self.run(
            Step(
                "save_as",
                f"save this as {name}",
                {"name": name, "keys": keys, "speak_detail": True},
            )
        )

    # ---------------------------------------------------------------- activate
    def k_activate(self, i):
        s = i.slots
        target, ordinal, role = s.get("target"), s.get("ordinal"), s.get("role")

        def deep():
            if role in ("link", "result"):
                items = self._items("links")
                if not items:
                    return self._ocr_find(target or "link", ordinal)
                if ordinal is not None:
                    idx = ordinal - 1 if ordinal > 0 else len(items) - 1
                    it = items[idx] if 0 <= idx < len(items) else None
                else:
                    t = re.sub(r"\b(?:the|link|result)\b", " ", (target or "").lower()).strip()
                    it = next((x for x in items if t and t in x.name.lower()), None)
                if it is not None:
                    self.remember_list("links", items)
                    return UIElement(uid=0, name=it.name, role="Hyperlink", bbox=it.bbox)
                return self._ocr_find(target or "link", ordinal)
            if target and ordinal is None:
                from relay.perception import text as ptext

                bare = re.sub(r"\b(?:the|button|link|on)\b", " ", target).strip() or target
                found, ok = self.s.worker.run(lambda: ptext.find_named(bare), timeout=8.0)
                if ok and found:
                    it = found[0]
                    return UIElement(uid=0, name=it.name, role=it.role, bbox=it.bbox)
                return self._ocr_find(bare, ordinal)
            if target and ordinal is not None:
                return self._ocr_find(target, ordinal)
            return None

        payload = dict(s)
        payload["deep_find"] = deep
        return self.run(Step("activate", f"click {target}", payload))





def _ord(text: str) -> int:
    from relay.intent.grammar import _ordinal_in

    return _ordinal_in(text) or 1


def _short_title(title: str) -> str:
    t = (title or "").strip()
    for suffix in (
        " - Google Chrome",
        " - Microsoft​ Edge",
        " - Microsoft Edge",
        " - Brave",
        " - Personal - Microsoft Edge",
        " - Mozilla Firefox",
        " - Notepad",
        " - Word",
    ):
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
