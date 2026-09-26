"""Session orchestrator — one utterance in, transparent narrated action out.

Parses the utterance, handles control words (stop/pause/continue/cancel/emergency),
memory and accessibility commands directly, routes everyday skills (status, apps,
windows, web, files, reading, notes, reminders, dictation) to
``relay.skills``, and runs anything that changes the screen through the
TransparentRunner. RELAY acts only in response to a command and narrates every step;
it never loops on its own.

Turn-taking the user can rely on:
  * a pending high-risk confirmation only accepts its exact phrase (or cancel);
  * a yes/no offer ("Do you want me to search the web instead?") takes yes or no —
    anything else is treated as a new command;
  * a follow-up question ("What should the note say?") takes the next utterance;
  * in dictation, speech is typed, except control words and "stop dictation".
Everything runs on the laptop: no cloud service, account or API key is used.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable

from relay.accessibility import (
    PendingConfirmation,
    confirmation_phrase,
    is_cancel,
    is_first_run,
    mark_onboarded,
    onboarding_script,
)
from relay.audio.wake import Command
from relay.core import EmergencyStop, new_task_id
from relay.diagnostics import get_logger
from relay.executor import Executor
from relay.intent import Kind, parse
from relay.intent.normalize import normalize
from relay.memory.db import connect
from relay.memory.journal import ActionJournal
from relay.memory.notes import NotesStore
from relay.memory.reconcile import latest_task_id, reconcile
from relay.memory.store import MemoryStore
from relay.memory.task_context import TaskContext
from relay.narration import policy as pol
from relay.perception import UIAWorker
from relay.perception.ocr import OCR
from relay.planner import TransparentRunner, plan
from relay.reading import Reader
from relay.reminders import ReminderScheduler
from relay.safety import ConfirmationStrength, PermissionEngine
from relay.skills import Skills
from relay.verifier import Verifier

_MEMORY_KINDS = {
    Kind.REMEMBER, Kind.WHAT_REMEMBER, Kind.WHY_REMEMBER, Kind.FORGET,
    Kind.CLEAR_HISTORY, Kind.EXPORT_PREFS, Kind.WHAT_DOING,
}
_ACCESS_KINDS = {
    Kind.SET_MODE, Kind.READ_DIALOG, Kind.NEXT_ELEMENT, Kind.PREV_ELEMENT, Kind.SPELL,
    Kind.CAPABILITIES,
}
log = get_logger("session")
_REQ = pol.Priority.REQUESTED
_CONF = pol.Priority.CONFIRMATION
_YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|please do|do it|go ahead|haan|ha|"
                  r"yes please|of course|alright|all right)\b", re.I)
_NO = re.compile(r"^(?:no|nope|nah|don't|do not|not now|cancel|never mind|nahi)\b", re.I)


class Session:
    def __init__(self, speak=None, bus=None, db_path: str = ":memory:", speech=None,
                 apps=None, on_quit: Callable[[], None] | None = None,
                 on_wake_word: Callable[[bool], None] | None = None,
                 talk_key: str = "ctrl+alt+space", assistant=None, audio=None) -> None:
        self.emergency = EmergencyStop()
        self.cancel = threading.Event()
        self._speak = speak
        self.bus = bus
        self.speech = speech                # SpeechQueue (live app) or None (tests/CLI)
        self.on_quit = on_quit
        self.on_wake_word = on_wake_word
        self.assistant = assistant          # optional conversational AI (relay.llm)
        self.audio = audio                  # headphone mode / audio devices (the live app)
        self._step_failed = False           # a skill couldn't do its part (multi-step runs)
        self._in_steps = False
        self._answer_cancel = threading.Event()
        self._from_assistant = False
        self.talk_key = talk_key
        self.worker = UIAWorker(bus=bus)
        self.worker.start()
        self.engine = PermissionEngine()
        self.conn = connect(db_path)
        self.journal = ActionJournal(self.conn)
        self.store = MemoryStore(self.conn)
        self.notes = NotesStore(self.conn)
        self.reminders = ReminderScheduler(self.conn, on_due=self._on_reminder)
        self.task_id = new_task_id()
        self.ctx = TaskContext(self.task_id)
        self._last_pref: tuple[str, str] | None = None
        self._pending: PendingConfirmation | None = None
        self._offer: Callable[[], object] | None = None
        self._capture: Callable[[str], object] | None = None
        self._nav_index = -1
        self.dictation = False
        self.last_activity = ""
        if apps is None:
            from relay.system.apps import AppCatalog
            apps = AppCatalog(entries=[])
        self.apps = apps
        self.ocr = OCR()
        self.executor = Executor(self.engine, self.worker, self.journal, self.task_id,
                                 emergency=self.emergency, confirm=lambda d: False)
        self.verifier = Verifier(self.worker, self.journal)
        self.narration_mode = self.store.get_pref("narration_mode", default="quick")
        self.runner = TransparentRunner(
            self.executor, self.worker, self.verifier, self.ctx, speak=speak,
            emergency=self.emergency, bus=bus, engine=self.engine,
            on_confirm_needed=self._on_confirm_needed, mode=self.narration_mode)
        self.reader = Reader(speak_part=self._speak_part, say=lambda t: self.say(t, _REQ),
                             interrupt=self._interrupt_speech, on_event=self._emit)
        from relay.accessibility.coexist import ScreenReaderWatch
        self.screen_reader = ScreenReaderWatch()
        self.skills = Skills(self)
        self.speech_rate = 1.0
        try:
            self.set_speech_rate(float(self.store.get_pref("speech_rate", default="1.0")),
                                 persist=False)
        except ValueError:
            pass

    # ---- narration ----
    def say(self, text: str, priority: int = pol.Priority.TASK) -> None:
        self.runner.say(text, priority)

    def _emit(self, kind: str, data: dict) -> None:
        if self.bus is not None:
            self.bus.emit(kind, **data)

    def _speak_part(self, text: str, on_done) -> None:
        """One part of a document being read (bypasses narration filtering — the user
        asked for it)."""
        if self.bus is not None:
            self.bus.emit("narration.say", text=text)
        if self.speech is not None:
            self.speech.say(text, on_done=on_done)
            return
        if self._speak is not None:
            try:
                self._speak(text)
            except Exception:
                pass
        if on_done is not None:
            on_done(True)

    def _interrupt_speech(self) -> None:
        if self.speech is not None:
            self.speech.interrupt()

    def start_reading(self, text: str, title: str = "", intro: bool = True) -> None:
        self.reader.load(text, title=title)
        self.last_activity = "reading"
        self.reader.read_all(intro=intro)

    def set_speech_rate(self, rate: float, persist: bool = True) -> None:
        self.speech_rate = max(0.6, min(2.2, rate))
        eng = self.speech.tts if self.speech is not None else None
        if eng is not None and hasattr(eng, "set_rate"):
            eng.set_rate(self.speech_rate)
        if persist:
            self.store.set_pref("speech_rate", f"{self.speech_rate:.2f}")

    def onboard(self) -> None:
        wake = self.store.get_pref("wake_word", default="relay")
        from relay.audio.hotkeys import spoken_combo
        for line in onboarding_script(wake_word=wake, first_run=is_first_run(),
                                      talk_key=spoken_combo(self.talk_key)):
            self.say(line, _REQ)
        mark_onboarded()

    # ---- turn-taking helpers used by skills ----
    def offer(self, action: Callable[[], object]) -> None:
        """A yes/no follow-up: 'yes' runs ``action``; 'no' drops it."""
        self._offer = action

    def capture_next(self, consumer: Callable[[str], object]) -> None:
        """The next utterance is free text for a question RELAY just asked."""
        self._capture = consumer

    def ask_phrase(self, phrase: str, summary: str, retry: Callable[[], object]) -> None:
        self.say(summary, _CONF)
        self._pending = PendingConfirmation(phrase=phrase, summary=summary, retry=retry)
        self.say(f"To confirm, say: {phrase}. Or say cancel.", _CONF)

    def set_dictation(self, on: bool) -> None:
        self.dictation = on

    _EDITORS = ("notepad", "wordpad", "winword", "word", "notepad++", "code", "writer",
                "soffice")
    _BLANK = re.compile(r"^\*?\s*(?:untitled|document\s*\d*|new \d+|new tab|word)\b", re.I)

    def _fresh_document(self) -> bool:
        """'open Notepad and type …': Notepad (and Word) reopen your previous documents,
        so what's in front may be someone's unsaved work. Type into a NEW blank page.
        Returns False if no blank page could be made (then nothing is typed)."""
        from relay.planner.planner import Step
        from relay.system import windows
        w = windows.foreground()
        if w is None:
            return True
        app = (w.app or "").lower().removesuffix(".exe")
        if app not in self._EDITORS or self._BLANK.match(w.title or ""):
            return True
        self.say("That opened an existing document, so I'm starting a new blank page to "
                 "keep it safe.", _REQ)
        self.runner.run([Step("hotkey", "open a new blank page", {
            "keys": ["ctrl", "n"], "announce": "", "done_text": ""})])
        time.sleep(0.8)
        now = windows.foreground()
        if now is None or not self._BLANK.match(now.title or ""):
            self.say("I couldn't get a blank page, so I won't type there.", _REQ)
            return False                        # never type into the old document
        return True

    def _open_then_unknown(self, utterance: str) -> tuple[str, str] | None:
        """'open <an app I can find> and <something I can't do>' -> (open part, rest)."""
        m = re.match(r"^\s*(?:please\s+)?(open|launch|start)\s+(.+?)\s*,?\s+and\s+(.+?)[.!?]*$",
                     utterance, re.I)
        if not m:
            return None
        target = m.group(2)
        from relay.system import files, web
        if (self.apps.find(target) is None and web.site_url(target) is None
                and files.folder_for_phrase(target) is None):
            return None
        return f"{m.group(1)} {target}", m.group(3)

    def step_failed(self) -> None:
        """A skill reports it couldn't do what was asked (stops a multi-step run)."""
        self._step_failed = True

    # ---- several steps in one request ----
    _STOP_STATES = ("failed", "cancelled", "awaiting_confirmation")

    def run_steps(self, steps: list[str]):
        """Do each step in order, announcing the plan first; stop at the first step that
        fails (never type into the wrong window because an app didn't open), on
        cancel / emergency stop, or when a step needs a spoken confirmation."""
        n = len(steps)
        self.say(f"{n} steps: " + "; then ".join(steps) + ".", _REQ)
        results: list = []
        self._in_steps = True
        try:
            for k, step in enumerate(steps, 1):
                if self.emergency.is_engaged or self.cancel.is_set() or \
                        self._answer_cancel.is_set():
                    self.say(f"Stopped before step {k}.", _REQ)
                    break
                self._step_failed = False
                out = self.handle(step) or []
                results.extend(out)
                states = [getattr(r, "state", "") for r in out]
                opening = re.match(r"^(?:open|launch|start|switch to|go to)\b", step, re.I)
                bad = self._step_failed or any(s in self._STOP_STATES for s in states) or (
                    opening and "uncertain" in states)
                waiting = self._pending is not None or self._offer is not None
                if bad and (self._step_failed or not waiting):
                    rest = steps[k:]            # a failure is always reported first
                    self.say(f"I stopped at step {k}, {step}, because it didn't work."
                             + (" I didn't do: " + "; ".join(rest) + "." if rest else ""), _REQ)
                    break
                if waiting:                     # a yes/no or a confirmation phrase is due
                    if k < n:
                        self.say("When that's done, say the rest again: "
                                 + "; then ".join(steps[k:]) + ".", _REQ)
                    break
                if k < n:
                    time.sleep(0.4)             # let the screen settle before the next step
                    if opening and parse(steps[k]).kind in (Kind.TYPE, Kind.DICTATION) \
                            and not self._fresh_document():
                        self.say("I stopped before typing. I didn't do: "
                                 + "; ".join(steps[k:]) + ".", _REQ)
                        break
            else:
                if n > 1:
                    self.say(f"All {n} steps done.", _REQ)
        finally:
            self._in_steps = False
        return results

    # ---- dispatch ----
    def handle(self, utterance: str):
        if self._pending is not None:
            return self._resolve_pending(utterance)
        low = normalize(utterance)
        raw_low = utterance.lower().strip().strip(".!?")
        if self._offer is not None:
            action, self._offer = self._offer, None
            if _YES.match(raw_low):
                return action() or []
            if _NO.match(raw_low):
                self.say("Okay.", _REQ)
                return []
        if self._capture is not None:
            consumer, self._capture = self._capture, None
            if is_cancel(low) and len(low.split()) <= 3:
                self.say("Okay, cancelled.", _REQ)
                return []
            return consumer(utterance.strip()) or []
        if not self.dictation and not self._in_steps:
            from relay.intent.compound import split_steps
            steps = split_steps(utterance)          # "open Notepad and type hello"
            if steps is not None:
                if len(steps) == 1:
                    return self.handle(steps[0])
                log.info("command: %d steps", len(steps))
                return self.run_steps(steps)
            part = self._open_then_unknown(utterance)
            if part is not None:                    # "open WhatsApp and send hi to Mom"
                if self.assistant is not None and not self._from_assistant:
                    return self.ask(utterance)      # the AI plans the whole thing
                self._step_failed = False
                opened = self.handle(part[0])
                if not self._step_failed:
                    self.say(f"I've done the first part. I can't do \"{part[1]}\" by "
                             "myself yet; tell me the next step, like click, type, or press.",
                             _REQ)
                return opened
        intent = parse(utterance)
        # the command TYPE only — never the words, which may be private (dictation, notes)
        log.info("command: %s (%d words)%s", intent.kind, len(utterance.split()),
                 " [dictation]" if self.dictation else "")
        self.runner.screen_reader = self.screen_reader.current()[0]
        if self.dictation and intent.kind not in (Kind.CONTROL, Kind.DICTATION, Kind.QUIT,
                                                  Kind.SHORTCUT, Kind.PRESS_KEY, Kind.HOTKEY):
            return self.skills.dictate(utterance)
        if intent.kind == Kind.CONTROL:
            return self._handle_control(intent.slots.get("command"))
        if intent.kind in _MEMORY_KINDS:
            return self._handle_memory(intent)
        if intent.kind in _ACCESS_KINDS:
            return self._handle_access(intent)
        self.cancel.clear()
        handled = self.skills.handle(intent)
        if handled is not None:
            if intent.kind not in (Kind.READ_ALL, Kind.READ_NOTES, Kind.LIST_LINKS,
                                   Kind.LIST_HEADINGS, Kind.HELP, Kind.READ_NEXT,
                                   Kind.READ_PREV, Kind.OCR_READ, Kind.READ_CLIPBOARD):
                self.last_activity = intent.kind
            return handled
        steps, clarification = plan(intent)
        if clarification:
            from relay.intent.fuzzy import closest
            near = closest(utterance)
            if near is not None:
                phrase, safe, _score = near
                if safe:                       # read-only: do it, and say how we heard it
                    self.say(f"I think you meant: {phrase}.", _REQ)
                    return self.handle(phrase)
                self.say(f"Did you mean: {phrase}? Say yes or no.", _REQ)
                self.offer(lambda: self.handle(phrase))
                return []
            if self.assistant is not None and not self._from_assistant:
                return self.ask(utterance)
            self.step_failed()
            self.say(f"Sorry, I didn't understand \"{utterance.strip()}\". "
                     "Say help to hear what I can do.", _REQ)
            return []
        self.last_activity = intent.kind
        return self.runner.run(steps, cancel=self.cancel)

    # ---- conversational assistant ----
    def ask(self, question: str, page_text: str = ""):
        """Stream an AI answer, speaking each sentence the moment it's complete. A
        suggested command is announced and then run through the normal safety gate."""
        if self.assistant is None:
            self.say("The AI assistant isn't set up on this computer, so I can only do "
                     "my built-in commands. Say help to hear them.", _REQ)
            return []
        self._answer_cancel.clear()
        first = threading.Event()

        def speak(sentence: str) -> None:
            if self._answer_cancel.is_set():
                return
            first.set()
            self._speak_part(sentence, None)

        done = threading.Event()

        def thinking_cue() -> None:            # soft ticks while the answer is slow to start
            from relay.audio.earcons import earcon
            wait = 1.2
            while not done.wait(wait) and not first.is_set():
                if self.speech is not None:
                    self.speech.play(*earcon("heard"))
                self._emit("assistant.thinking", {})
                wait = 2.5
        threading.Thread(target=thinking_cue, name="thinking-cue", daemon=True).start()
        try:
            kind, payload = self.assistant.respond(
                question, speak, context=self._assistant_context(), page_text=page_text,
                cancel=self._answer_cancel)
        finally:
            done.set()
        if kind == "command" and payload:
            self.say(f"I understood that as: {payload}.", _REQ)
            self._from_assistant = True
            try:
                return self.handle(payload)
            finally:
                self._from_assistant = False
        if kind == "plan" and payload:                 # several steps, each a safe command
            self._from_assistant = True
            try:
                return self.run_steps(list(payload))
            finally:
                self._from_assistant = False
        if kind == "offline":
            self.say("I can't reach the AI assistant right now, so I can only do my "
                     "built-in commands. Say help to hear them.", _REQ)
        elif payload:
            self.runner.last_said = payload     # so "repeat" repeats the answer
        self.last_activity = "answer"
        return []

    @staticmethod
    def _assistant_context() -> str:
        try:
            from relay.system.windows import _friendly_app, foreground
            fg = foreground()
            return f"The user is currently in {_friendly_app(fg.app)}." if fg else ""
        except Exception:
            return ""

    # ---- confirmation flow ----
    def _on_confirm_needed(self, decision, target_label, retry) -> None:
        self.say(decision.spoken_summary, _CONF)
        if decision.confirmation is ConfirmationStrength.KEYBOARD:
            self.say("This one is especially sensitive. Please confirm with your keyboard "
                     "or Windows sign-in — I won't do it by voice alone.", _CONF)
            return  # not voice-confirmable
        phrase = confirmation_phrase(target_label, decision.risk.value)
        self._pending = PendingConfirmation(phrase=phrase, summary=decision.spoken_summary,
                                            retry=retry)
        self.say(f"To confirm, say: {phrase}. Or say cancel.", _CONF)

    @staticmethod
    def _says_phrase(utterance: str, phrase: str) -> bool:
        """Every word of the phrase must be spoken (word stems allowed, so the way
        people actually answer — 'I confirm sending' — matches 'confirm send'). A casual
        'yeah', or 'send' alone, never matches."""
        tokens = re.findall(r"[a-z]+", normalize(utterance))
        return all(any(t.startswith(w) for t in tokens) for w in phrase.split())

    def _resolve_pending(self, utterance: str):
        p = self._pending
        low = utterance.lower().strip()
        norm = normalize(utterance)
        if p.phrase in low or norm == p.phrase or self._says_phrase(utterance, p.phrase):
            self._pending = None
            self.say("Confirmed.", _CONF)
            return [p.retry()]
        if is_cancel(low):
            self._pending = None
            self.say("Cancelled — I won't do it.", _CONF)
            return []
        if "emergency" in low:
            self._pending = None
            return self._handle_control(Command.EMERGENCY_STOP)
        p.reprompts += 1
        if p.reprompts > 2:
            self._pending = None
            self.say("Okay, cancelling that.", _CONF)
            return []
        self.say(f"To confirm, say {p.phrase}, or say cancel.", _CONF)
        return []

    # ---- reminders ----
    def _on_reminder(self, text: str, late_seconds: float) -> None:
        was_reading = self.reader.stop()
        if self.bus is not None:
            self.bus.emit("reminder.due", text=text)
        if self.speech is not None:
            from relay.audio.earcons import earcon
            audio, sr = earcon("alert")
            self.speech.play(audio, sr)
        when = ""
        if late_seconds > 120:
            due = time.localtime(time.time() - late_seconds)
            when = f" This was due at {time.strftime('%I:%M %p', due).lstrip('0')}."
        self.say(f"Reminder: {text.rstrip('.')}.{when}", pol.Priority.CRITICAL)
        if was_reading:
            self.say("Say continue to keep reading.", _REQ)

    # ---- accessibility read / navigate / spell / mode ----
    def _handle_access(self, intent):
        k, s = intent.kind, intent.slots
        if k == Kind.CAPABILITIES:
            from relay.workflows import spoken_summary
            self.say(spoken_summary(), _REQ)
        elif k == Kind.SET_MODE:
            mode = s["mode"]
            self.narration_mode = mode
            self.runner.mode = mode
            self.store.set_pref("narration_mode", mode)
            self.say(f"Okay, {mode} narration.", _REQ)
        elif k == Kind.READ_DIALOG:
            snap = self.worker.observe(3.0)
            if snap and snap.dialogs:
                d = snap.dialogs[0]
                btns = f" Buttons: {', '.join(d.buttons)}." if d.buttons else ""
                self.say(f"Dialog: {d.title}.{btns}", _REQ)
            else:
                self.say("There's no dialog open.", _REQ)
        elif k in (Kind.NEXT_ELEMENT, Kind.PREV_ELEMENT):
            if self.last_activity == "reading" and self.reader.has_content:
                self.reader.step(+1 if k == Kind.NEXT_ELEMENT else -1)
                return []
            snap = self.worker.observe(3.0)
            from relay.memory.task_context import reading_order
            els = reading_order([e for e in (snap.elements if snap else []) if e.name])
            if not els:
                self.say("There's nothing to move through here.", _REQ)
                return []
            self._nav_index += 1 if k == Kind.NEXT_ELEMENT else -1
            self._nav_index = max(0, min(self._nav_index, len(els) - 1))
            e = els[self._nav_index]
            self.ctx.remember("last", e, snap.observation_version)
            self.say(f"{e.role}: {e.name}." + (f" {e.value}" if e.value else ""), _REQ)
        elif k == Kind.SPELL:
            snap = self.worker.observe(3.0)
            text = ""
            if snap and snap.selection:
                text = snap.selection
            elif snap and snap.focus:
                text = snap.focus.value or snap.focus.name
            text = text or self.runner.last_said
            self.say(pol.spell(text), _REQ)
        return []

    # ---- memory ----
    def _handle_memory(self, intent):
        k, s = intent.kind, intent.slots
        if k == Kind.REMEMBER:
            if "mode" in s:
                scope = self._app_key(s.get("app", ""))
                self.store.set_pref("narration_mode", s["mode"], scope=scope)
                self._last_pref = (scope, "narration_mode")
                where = f" in {s['app']}" if s.get("app") else ""
                if not s.get("app"):
                    self.narration_mode = s["mode"]
                    self.runner.mode = s["mode"]
                self.say(f"Got it — I'll use {s['mode']} narration{where}.")
            else:
                fact = s.get("fact", "")
                ok = self.store.set_pref(f"note:{fact[:40]}", fact)
                if ok:
                    self.notes.add(fact)
                self._last_pref = ("", f"note:{fact[:40]}") if ok else None
                self.say("I've noted that." if ok else
                         "I won't store that — it looks sensitive, so I'm keeping it out.")
        elif k == Kind.WHAT_REMEMBER:
            summary = self.store.remember_summary()
            n = self.notes.count()
            if n:
                summary += f" You also have {n} note{'s' if n != 1 else ''}; say read my notes."
            self.say(summary)
        elif k == Kind.WHY_REMEMBER:
            if self._last_pref:
                why = self.store.why(self._last_pref[1], self._last_pref[0])
                self.say(f"I remember that because you told me — provenance: {why}." if why
                         else "I'm not sure which memory you mean.")
            else:
                self.say("I'm not sure which memory you mean.")
        elif k == Kind.FORGET:
            if self._last_pref and self.store.delete_pref(self._last_pref[1], self._last_pref[0]):
                self.say("Forgotten.")
                self._last_pref = None
            else:
                self.say("There's nothing recent for me to forget.")
        elif k == Kind.CLEAR_HISTORY:
            self.store.clear_task_history()
            self.say("I've cleared your task history and saved summaries.")
        elif k == Kind.EXPORT_PREFS:
            data = self.store.export_prefs()
            self.say(f"You have {len(data['preferences'])} saved preference(s). "
                     "I can write them to a file you choose.")
        elif k == Kind.WHAT_DOING:
            tid = latest_task_id(self.conn)
            self.say(reconcile(self.journal, tid).spoken if tid
                     else "I don't have a record of a task in progress.")
        return []

    @staticmethod
    def _app_key(app: str) -> str:
        from relay.planner.runner import _APP_EXE
        a = app.lower().strip()
        return _APP_EXE.get(a, a if a.endswith(".exe") else (f"{a}.exe" if a else ""))

    # ---- control words ----
    def stop_speaking(self) -> None:
        """Silence RELAY, pause any reading and stop a streaming answer
        (talk-key / stop-key / 'stop')."""
        self._answer_cancel.set()
        self.reader.stop()
        self._interrupt_speech()

    def emergency_stop(self) -> None:
        self._handle_control(Command.EMERGENCY_STOP)

    def _handle_control(self, command: str | None):
        if command == Command.EMERGENCY_STOP:
            self.emergency.engage("user")
            self.cancel.set()
            self._answer_cancel.set()
            self._pending = None
            self.reader.stop()
            self.set_dictation(False)
            self.say("Emergency stop. I've stopped everything. Say continue when you want me "
                     "to work again.", pol.Priority.CRITICAL)
        elif command == Command.CANCEL_TASK:
            self.cancel.set()
            self._answer_cancel.set()
            self._pending = None
            self._offer = None
            self._capture = None
            self.reader.stop()
            self.say("Cancelling.", _CONF)
        elif command == Command.STOP_TALKING:
            self.stop_speaking()
        elif command == Command.PAUSE:
            self.cancel.set()
            was = self.reader.stop()
            self.say("Paused. Say continue when you're ready." if not was else
                     "Paused. Say continue to keep reading.", _CONF)
        elif command == Command.CONTINUE:
            if self.emergency.is_engaged:
                self.emergency.reset()
                self.cancel.clear()
                self.say("Emergency stop cleared. I'm ready.", _CONF)
            elif self.reader.has_content and not self.reader.reading \
                    and self.last_activity == "reading":
                self.reader.resume()
            else:
                self.cancel.clear()
                self.say("Okay.", _CONF)
        elif command == Command.REPEAT:
            if self.last_activity == "reading" and self.reader.has_content:
                self.reader.repeat()
            else:
                self.say(self.runner.last_said or "I haven't said anything yet.", _REQ)
        return []

    def close(self) -> None:
        self.reminders.stop()
        self.worker.stop()
        try:
            self.conn.close()
        except Exception:
            pass
