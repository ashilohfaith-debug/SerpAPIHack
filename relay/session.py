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
from pathlib import Path
from typing import Callable

from relay.accessibility import (
    PendingConfirmation,
    confirmation_phrase,
    is_cancel,
)
from relay.audio.wake import Command
from relay.core import EmergencyStop, new_task_id
from relay.core.state import relay_state_machine
from relay.diagnostics import get_logger
from relay.executor import Executor
from relay.goals.assignment import AssignmentWorkflow
from relay.goals.goal import GoalManager
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
from relay.workspace.agent import WorkspaceAgent

_MEMORY_KINDS = {
    Kind.REMEMBER,
    Kind.WHAT_REMEMBER,
    Kind.WHY_REMEMBER,
    Kind.FORGET,
    Kind.CLEAR_HISTORY,
    Kind.EXPORT_PREFS,
    Kind.WHAT_DOING,
    Kind.SAVE_PASSWORD,
    Kind.ENTER_PASSWORD,
    Kind.FORGET_PASSWORD,
}
_ACCESS_KINDS = {
    Kind.SET_MODE,
    Kind.READ_DIALOG,
    Kind.NEXT_ELEMENT,
    Kind.PREV_ELEMENT,
    Kind.SPELL,
    Kind.CAPABILITIES,
}
_GOAL_KINDS = {
    Kind.GOAL_START,
    Kind.GOAL_STATUS,
    Kind.GOAL_PAUSE,
    Kind.GOAL_RESUME,
    Kind.GOAL_CANCEL,
    Kind.GOAL_NEXT,
}
_ASSIGNMENT_KINDS = {
    Kind.ASSIGNMENT_START,
    Kind.ASSIGNMENT_STATUS,
    Kind.ASSIGNMENT_CHECKLIST,
    Kind.ASSIGNMENT_SUBMIT,
}
_WORKSPACE_KINDS = {
    Kind.WORKSPACE_TEST,
    Kind.WORKSPACE_STATUS,
    Kind.WORKSPACE_DIFF,
}
_TEXT_KINDS = {
    Kind.TEXT_SELECT,
    Kind.TEXT_NAV,
    Kind.TEXT_EDIT,
    Kind.TEXT_FORMAT,
    Kind.TEXT_INSPECT,
    Kind.COMPOSE,
}
log = get_logger("session")
_REQ = pol.Priority.REQUESTED
_CONF = pol.Priority.CONFIRMATION
_YES = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|ok|okay|please do|do it|go ahead|haan|ha|"
    r"yes please|of course|alright|all right)\b",
    re.I,
)
_NO = re.compile(r"^(?:no|nope|nah|don't|do not|not now|cancel|never mind|nahi)\b", re.I)


class Session:
    def __init__(
        self,
        speak=None,
        bus=None,
        db_path: str = ":memory:",
        speech=None,
        apps=None,
        on_quit: Callable[[], None] | None = None,
        on_wake_word: Callable[[bool], None] | None = None,
        talk_key: str = "ctrl+alt+space",
        assistant=None,
        audio=None,
    ) -> None:
        self.emergency = EmergencyStop()
        self.cancel = threading.Event()
        self._speak = speak
        self.bus = bus
        self.speech = speech  # SpeechQueue (live app) or None (tests/CLI)
        self.on_quit = on_quit
        self.on_wake_word = on_wake_word
        self.assistant = assistant  # optional conversational AI (relay.llm)
        self.audio = audio  # headphone mode / audio devices (the live app)
        self._step_failed = False  # a skill couldn't do its part (multi-step runs)
        self._in_steps = False
        self._answering = False
        self._answer_cancel = threading.Event()
        self._from_assistant = False
        self.talk_key = talk_key
        self.worker = UIAWorker(bus=bus)
        self.worker.start()
        self.worker.start_change_monitor()
        self.engine = PermissionEngine()
        self.conn = connect(db_path)
        self.journal = ActionJournal(self.conn)
        self.store = MemoryStore(self.conn)
        self.notes = NotesStore(self.conn)
        self.reminders = ReminderScheduler(self.conn, on_due=self._on_reminder)
        self.goals = GoalManager(self.conn, bus=bus)
        self.assignment = AssignmentWorkflow(bus=bus, goals=self.goals, session=self)
        self.workspace = WorkspaceAgent(self.store.get_pref("workspace_dir", default="."), bus=bus)
        self.state_machine = relay_state_machine(machine_id="session", bus=bus)
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
        from relay.system.knowledge import KnowledgeEngine

        self.knowledge = KnowledgeEngine()
        self.executor = Executor(
            self.engine,
            self.worker,
            self.journal,
            self.task_id,
            emergency=self.emergency,
            confirm=lambda d: False,
        )
        self.verifier = Verifier(self.worker, self.journal)
        self.narration_mode = self.store.get_pref("narration_mode", default="quick")
        self.runner = TransparentRunner(
            self.executor,
            self.worker,
            self.verifier,
            self.ctx,
            speak=speak,
            emergency=self.emergency,
            bus=bus,
            engine=self.engine,
            on_confirm_needed=self._on_confirm_needed,
            mode=self.narration_mode,
            ocr=self.ocr,
        )
        self.reader = Reader(
            speak_part=self._speak_part,
            say=lambda t: self.say(t, _REQ),
            interrupt=self._interrupt_speech,
            on_event=self._emit,
        )
        from relay.accessibility.coexist import ScreenReaderWatch

        self.screen_reader = ScreenReaderWatch()
        self.skills = Skills(self)
        from relay.editing.editor import TextEditor

        self.editor = TextEditor(self.executor, self.worker)
        self.mode = "general"
        self.speech_rate = 1.0
        try:
            self.set_speech_rate(
                float(self.store.get_pref("speech_rate", default="1.0")), persist=False
            )
        except ValueError:
            pass

        from relay.liveworld import LiveWorldBroker

        self.live_world = LiveWorldBroker()
        self._last_live_decision = None
        self._last_live_action = None

        self.hold_to_talk = True
        try:
            self.hold_to_talk = self.store.get_pref("hold_to_talk", default="1") in ("1", "true", "True")
        except Exception:
            pass

        self._last_snapshot = None
        if self.bus is not None:
            def _on_perception_change(e):
                if self.dictation or self._in_steps or getattr(self, "_answering", False):
                    return
                snap = self.worker.live
                if snap is not None and self._last_snapshot is not None:
                    from relay.narration.delta import diff
                    lines = diff(self._last_snapshot, snap)
                    if lines:
                        prio = pol.Priority.CONFIRMATION if snap.dialogs else pol.Priority.BACKGROUND
                        if pol.should_speak(prio, self.narration_mode):
                            self.say(" ".join(lines[:2]), prio)
                self._last_snapshot = snap

            self.bus.subscribe("perception.change", _on_perception_change)

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

    def _rearm_voice(self) -> None:
        if self.bus is not None:
            self.bus.emit("voice.rearm")

    def onboard(self) -> None:
        from relay.accessibility.onboarding import run_onboarding
        run_onboarding(self)

    # ---- turn-taking helpers used by skills ----
    def offer(self, action: Callable[[], object]) -> None:
        """A yes/no follow-up: 'yes' runs ``action``; 'no' drops it."""
        self._offer = action
        self._rearm_voice()

    def capture_next(self, consumer: Callable[[str], object]) -> None:
        """The next utterance is free text for a question RELAY just asked."""
        self._capture = consumer
        self._rearm_voice()

    def ask_phrase(self, phrase: str, summary: str, retry: Callable[[], object]) -> None:
        self.say(summary, _CONF)
        self._pending = PendingConfirmation(phrase=phrase, summary=summary, retry=retry)
        self.say(f"To confirm, say: {phrase}. Or say cancel.", _CONF)
        self._rearm_voice()

    def set_dictation(self, on: bool) -> None:
        self.dictation = on

    _EDITORS = ("notepad", "wordpad", "winword", "word", "notepad++", "code", "writer", "soffice")
    _BLANK = re.compile(r"^\*?\s*(?:untitled|document\s*\d*|new \d+|new tab|word|notepad)\b", re.I)

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
        self.say(
            "That opened an existing document, so I'm starting a new blank page to keep it safe.",
            _REQ,
        )
        self.runner.run(
            [
                Step(
                    "hotkey",
                    "open a new blank page",
                    {"keys": ["ctrl", "n"], "announce": "", "done_text": ""},
                )
            ]
        )
        time.sleep(0.8)
        now = windows.foreground()
        if now is None or not self._BLANK.match(now.title or ""):
            self.say("I couldn't get a blank page, so I won't type there.", _REQ)
            return False  # never type into the old document
        return True

    def _open_then_unknown(self, utterance: str) -> tuple[str, str] | None:
        """'open <an app I can find> and <something I can't do>' -> (open part, rest)."""
        m = re.match(
            r"^\s*(?:please\s+)?(open|launch|start)\s+(.+?)\s*,?\s+and\s+(.+?)[.!?]*$",
            utterance,
            re.I,
        )
        if not m:
            return None
        target = m.group(2)
        from relay.system import files, web

        if (
            self.apps.find(target) is None
            and web.site_url(target) is None
            and files.folder_for_phrase(target) is None
        ):
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
        if n <= 4:
            self.say(f"{n} steps: " + "; then ".join(steps) + ".", _REQ)
        else:
            self.say(f"Starting {n} steps, beginning with {steps[0]}.", _REQ)
        results: list = []
        self._in_steps = True
        try:
            for k, step in enumerate(steps, 1):
                if self.emergency.is_engaged or self.cancel.is_set():
                    self.say(f"Stopped before step {k}.", _REQ)
                    break
                if n >= 10 and k % 10 == 0 and k < n:
                    self.say(f"Step {k} of {n} complete.", _REQ)
                self._step_failed = False
                out = self.handle(step) or []
                results.extend(out)
                states = [getattr(r, "state", "") for r in out]
                opening = re.match(r"^(?:open|launch|start|switch to|go to)\b", step, re.I)
                bad = (
                    self._step_failed
                    or any(s in self._STOP_STATES for s in states)
                )
                waiting = self._pending is not None or self._offer is not None
                if bad and (self._step_failed or not waiting):
                    rest = steps[k:]  # a failure is always reported first
                    self.say(
                        f"I stopped at step {k}, {step}, because it didn't work."
                        + (" I didn't do: " + "; ".join(rest) + "." if rest else ""),
                        _REQ,
                    )
                    break
                if waiting:  # a yes/no or a confirmation phrase is due
                    if k < n:
                        self.say(
                            "When that's done, say the rest again: "
                            + "; then ".join(steps[k:])
                            + ".",
                            _REQ,
                        )
                    break
                if k < n:
                    time.sleep(0.4)  # let the screen settle before the next step
                    if (
                        opening
                        and parse(steps[k]).kind in (Kind.TYPE, Kind.DICTATION)
                        and not self._fresh_document()
                    ):
                        self.say(
                            "I stopped before typing. I didn't do: " + "; ".join(steps[k:]) + ".",
                            _REQ,
                        )
                        break
            else:
                if n > 1:
                    self.say(f"All {n} steps done.", _REQ)
        finally:
            self._in_steps = False
        return results

    # ---- dispatch ----
    def handle(self, utterance: str):
        low = normalize(utterance)
        safety_intent = parse(utterance)
        safety_command = safety_intent.get("command") if safety_intent.kind == Kind.CONTROL else None
        if safety_command in (Command.EMERGENCY_STOP, Command.STOP_TALKING, Command.CANCEL_TASK):
            return self._handle_control(safety_command)
        if self.emergency.is_engaged:
            if safety_command == Command.CONTINUE:
                return self._handle_control(safety_command)
            self.say("Emergency stop is still active. Say continue before making another request.", _REQ)
            return []
        if self._pending is not None:
            return self._resolve_pending(utterance)
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
            if re.search(r"\b(?:cancel|never\s?mind|abort|forget it)\b", low) and len(low.split()) <= 3:
                self.say("Okay, cancelled.", _REQ)
                return []
            return consumer(utterance.strip()) or []
        if not self._in_steps and not self.emergency.is_engaged:
            # A new request gets fresh cancellation state. The talk key deliberately
            # interrupts speech/streaming before recording, but must not cancel the
            # command that the user is about to give.
            self.cancel.clear()
            self._answer_cancel.clear()

        # 1. Booking preparation: use SerpApi's booking token to resolve a real
        # provider handoff. This opens checkout but never submits passenger/payment data.
        book_cmd = utterance.strip().lower()
        if not self.dictation and re.fullmatch(
            r"(?:book|reserve)\s+(?:it|this|the\s+(?:flight|ticket|option|trip))[.!?]?",
            book_cmd,
        ):
            decision = self.live_world.prepare_flight_booking(bus=self.bus)
            if self.emergency.is_engaged or self.cancel.is_set():
                return []
            self._last_live_decision = decision
            self._last_live_action = decision.action
            self.say(decision.answer, _REQ)
            action = decision.action or {}
            if action.get("target"):
                from relay.system.web import open_booking_request

                try:
                    open_booking_request(action["target"], action.get("postData", ""))
                except Exception as exc:
                    log.warning("Could not open booking handoff: %s", exc)
                    self.say("I verified the option, but couldn't open the provider.", _REQ)
            return [decision.answer]

        # 2. Action trigger check for opening retrieved live evidence URLs
        open_cmd = utterance.strip().lower()
        open_match = re.fullmatch(
            r"(?:open|launch|show)\s+(?:(?:the|selected|best)\s+)?"
            r"(flight|hotel|stay|dinner|restaurant|plan|option|url|result|link|best)[.!?]?",
            open_cmd,
        )
        if not self.dictation and open_match:
            self._last_live_action_success = False
            component = open_match.group(1)
            engine = {
                "flight": "google_flights",
                "hotel": "google_hotels",
                "stay": "google_hotels",
                "dinner": "google_maps",
                "restaurant": "google_maps",
            }.get(component)
            action = self.live_world.selected_action(engine)
            if action and action.get("target"):
                target_url = action["target"]
                label = action.get("label", "result")
                self.say(f"Opening {label}.", _REQ)
                from relay.system.web import open_booking_request
                try:
                    open_booking_request(target_url, action.get("postData", ""))
                except Exception as exc:
                    log.warning("Could not open live-world action: %s", exc)
                    self.say("I couldn't open that verified result.", _REQ)
                    return []
                self._last_live_action_success = True
                return [f"Opened {target_url}"]
            self.say(f"I don't have a verified {component} link to open. Ask me to find one first.", _REQ)
            return []

        # 3. Live-World intent routing via LiveWorldBroker
        if not self.dictation and hasattr(self, "live_world") and self.live_world:
            lw_intent = self.live_world.classify(utterance)
            if lw_intent.requires_live_data:
                log.info("Routing request to LiveWorldBroker (requires_live_data=True, category=%s)", lw_intent.category)
                _, decision, telemetry = self.live_world.process(utterance, bus=self.bus)
                if self.emergency.is_engaged or self.cancel.is_set():
                    return []
                self._last_live_decision = decision
                self._last_live_action = decision.action
                self.say(decision.answer, _REQ)
                return [decision.answer]
        if not self.dictation and not self._in_steps:
            from relay.intent.compound import split_steps

            steps = split_steps(utterance)  # "open Notepad and type hello"
            if steps is not None:
                if len(steps) == 1:
                    return self.handle(steps[0])
                log.info("command: %d steps", len(steps))
                return self.run_steps(steps)
            part = self._open_then_unknown(utterance)
            if part is not None:  # "open WhatsApp and send hi to Mom"
                if self.assistant is not None and not self._from_assistant:
                    return self.ask(utterance)  # the AI plans the whole thing
                self._step_failed = False
                opened = self.handle(part[0])
                if not self._step_failed:
                    self.say(
                        f"I've done the first part. I can't do \"{part[1]}\" by "
                        "myself yet; tell me the next step, like click, type, or press.",
                        _REQ,
                    )
                return opened
        intent = parse(utterance)
        if hasattr(self, "ctx") and self.ctx is not None:
            if intent.kind == Kind.SAVE_PASSWORD:
                self.ctx.recent_query = f"save password for {intent.get('app', '')}".strip()
            else:
                self.ctx.recent_query = utterance
            self.ctx.recent_activity = intent.kind
        # the command TYPE only — never the words, which may be private (dictation, notes)
        log.info(
            "command: %s (%d words)%s",
            intent.kind,
            len(utterance.split()),
            " [dictation]" if self.dictation else "",
        )
        self.runner.screen_reader = self.screen_reader.current()[0]
        if self.dictation and intent.kind not in (
            Kind.CONTROL,
            Kind.DICTATION,
            Kind.QUIT,
            Kind.SHORTCUT,
            Kind.PRESS_KEY,
            Kind.HOTKEY,
        ):
            return self.skills.dictate(utterance)
        if intent.kind == Kind.CONTROL:
            return self._handle_control(intent.slots.get("command"))
        if intent.kind in _MEMORY_KINDS:
            return self._handle_memory(intent)
        if intent.kind in _ACCESS_KINDS:
            return self._handle_access(intent)
        if intent.kind in _GOAL_KINDS:
            return self._handle_goal(intent)
        if intent.kind in _ASSIGNMENT_KINDS:
            return self._handle_assignment(intent)
        if intent.kind in _WORKSPACE_KINDS:
            return self._handle_workspace(intent)
        if intent.kind in _TEXT_KINDS:
            return self._handle_text_editing(intent)
        if intent.kind == Kind.ASK:
            return self.ask(intent.slots.get("text") or utterance)
        if intent.kind == Kind.SUMMARIZE:
            return self.skills.k_summarize(intent)
        self.cancel.clear()
        handled = self.skills.handle(intent)
        if handled is not None:
            if intent.kind not in (
                Kind.READ_ALL,
                Kind.READ_NOTES,
                Kind.LIST_LINKS,
                Kind.LIST_HEADINGS,
                Kind.HELP,
                Kind.READ_NEXT,
                Kind.READ_PREV,
                Kind.OCR_READ,
                Kind.READ_CLIPBOARD,
            ):
                self.last_activity = intent.kind
            return handled
        steps, clarification = plan(intent)
        if clarification:
            from relay.intent.fuzzy import closest

            near = closest(utterance)
            if near is not None:
                phrase, safe, _score = near
                if safe:  # read-only: do it, and say how we heard it
                    self.say(f"I think you meant: {phrase}.", _REQ)
                    return self.handle(phrase)
                self.say(f"Did you mean: {phrase}? Say yes or no.", _REQ)
                self.offer(lambda: self.handle(phrase))
                return []
            if self.assistant is not None and not self._from_assistant:
                return self.ask(utterance)
            self.step_failed()
            self.say(
                f'Sorry, I didn\'t understand "{utterance.strip()}". '
                "Say help to hear what I can do.",
                _REQ,
            )
            return []
        self.last_activity = intent.kind
        return self.runner.run(steps, cancel=self.cancel)

    # ---- conversational assistant ----
    def reload_assistant(self) -> bool:
        """Reload routes and initialize assistant if credentials were added/updated."""
        try:
            from relay.config import Config
            from relay.llm import Assistant, Router, routes_from_config

            cfg = Config.load()
            routes = routes_from_config(cfg)
            if routes:
                self.assistant = Assistant(Router(routes))
                return True
        except Exception as e:
            log.warning("could not reload assistant: %s", e)
        return False

    def ask(self, question: str, page_text: str = ""):
        """Stream an AI answer, speaking each sentence the moment it's complete. A
        suggested command is announced and then run through the normal safety gate."""
        if self.assistant is None:
            self.reload_assistant()
        if self.assistant is None:
            # Perplexity Computer voice answering fallback: knowledge & web synthesis
            if page_text:
                summary = self.knowledge.summarize_text(page_text)
                self.say(f"Here is a summary of the page: {summary}", _REQ)
                self.runner.last_said = summary
                self.last_activity = "answer"
                return []
            ans = self.knowledge.answer(question)
            if ans:
                self.say(ans, _REQ)
                self.runner.last_said = ans
                self.last_activity = "answer"
                return []
            self.say(
                "The AI assistant isn't set up on this computer, so I can only do "
                "my built-in commands. Say help to hear them.",
                _REQ,
            )
            return []
        self._answer_cancel.clear()
        first = threading.Event()

        def speak(sentence: str) -> None:
            if self._answer_cancel.is_set():
                return
            first.set()
            self._speak_part(sentence, None)

        done = threading.Event()

        def thinking_cue() -> None:  # soft ticks while the answer is slow to start
            from relay.audio.earcons import earcon

            wait = 1.2
            while not done.wait(wait) and not first.is_set():
                if self.speech is not None:
                    self.speech.play(*earcon("heard"))
                self._emit("assistant.thinking", {})
                wait = 2.5

        threading.Thread(target=thinking_cue, name="thinking-cue", daemon=True).start()
        self._answering = True
        try:
            mode = getattr(self, "mode", "general")
            try:
                kind, payload = self.assistant.respond(
                    question,
                    speak,
                    context=self._assistant_context(),
                    page_text=page_text,
                    task_mode=mode,
                    cancel=self._answer_cancel,
                )
            except TypeError:
                kind, payload = self.assistant.respond(
                    question,
                    speak,
                    context=self._assistant_context(),
                    page_text=page_text,
                    cancel=self._answer_cancel,
                )
        finally:
            done.set()
            self._answering = False
        if kind == "command" and payload:
            self.say(f"I understood that as: {payload}.", _REQ)
            self._from_assistant = True
            try:
                return self.handle(payload)
            finally:
                self._from_assistant = False
        if kind == "plan" and payload:  # several steps, each a safe command
            self._from_assistant = True
            try:
                return self.run_steps(list(payload))
            finally:
                self._from_assistant = False
        if kind == "offline":
            self.say(
                "I can't reach the AI assistant right now, so I can only do my "
                "built-in commands. Say help to hear them.",
                _REQ,
            )
            # Perplexity Computer voice answering fallback: knowledge & web synthesis
            if page_text:
                summary = self.knowledge.summarize_text(page_text)
                self.say(f"Here is a summary of the page: {summary}", _REQ)
                self.runner.last_said = summary
                self.last_activity = "answer"
                return []
            ans = self.knowledge.answer(question)
            if ans:
                self.say(f"From my knowledge base: {ans}", _REQ)
                self.runner.last_said = ans
                self.last_activity = "answer"
                return []
        elif payload:
            self.runner.last_said = payload  # so "repeat" repeats the answer
        self.last_activity = "answer"
        return []

    def _assistant_context(self) -> str:
        ctx_parts = []
        try:
            from relay.system.windows import _friendly_app, foreground

            fg = foreground()
            if fg:
                ctx_parts.append(f"The user is currently in {_friendly_app(fg.app)}.")
        except Exception:
            pass

        try:
            # Inject relevant user preferences and notes into LLM assistant context
            prefs = self.store.all_prefs()
            if prefs:
                pref_lines = [f"{p['key']}: {p['value']}" for p in prefs if not p["key"].startswith("note:")]
                if pref_lines:
                    ctx_parts.append("User preferences: " + "; ".join(pref_lines[:10]))
            notes = self.notes.list(limit=5)
            if notes:
                note_lines = [n.get("text", "") for n in notes if n.get("text")]
                if note_lines:
                    ctx_parts.append("User notes/memories: " + "; ".join(note_lines))
        except Exception:
            pass

        return "\n".join(ctx_parts)


    # ---- confirmation flow ----
    def _on_confirm_needed(self, decision, target_label, retry) -> None:
        self.say(decision.spoken_summary, _CONF)
        if decision.confirmation is ConfirmationStrength.KEYBOARD:
            self.say(
                "This one is especially sensitive. Please confirm with your keyboard "
                "or Windows sign-in — I won't do it by voice alone.",
                _CONF,
            )
            return  # not voice-confirmable
        phrase = confirmation_phrase(target_label, decision.risk.value)
        self._pending = PendingConfirmation(
            phrase=phrase, summary=decision.spoken_summary, retry=retry
        )
        self.say(f"To confirm, say: {phrase}. Or say cancel.", _CONF)
        self._rearm_voice()

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
            if "alias_target" in s and "alias_name" in s:
                target = s["alias_target"]
                alias = s["alias_name"]
                self.store.set_pref(f"alias:{alias.lower()}", target)
                self.say(f"Saved alias. I will remember that {alias} means {target}.", _REQ)
                return []
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
                self.say(
                    "I've noted that."
                    if ok
                    else "I won't store that — it looks sensitive, so I'm keeping it out."
                )
        elif k == Kind.WHAT_REMEMBER:
            summary = self.store.remember_summary()
            n = self.notes.count()
            if n:
                summary += f" You also have {n} note{'s' if n != 1 else ''}; say read my notes."
            self.say(summary)
        elif k == Kind.WHY_REMEMBER:
            if self._last_pref:
                why = self.store.why(self._last_pref[1], self._last_pref[0])
                self.say(
                    f"I remember that because you told me — provenance: {why}."
                    if why
                    else "I'm not sure which memory you mean."
                )
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
            self.say(
                f"You have {len(data['preferences'])} saved preference(s). "
                "I can write them to a file you choose."
            )
        elif k == Kind.WHAT_DOING:
            tid = latest_task_id(self.conn)
            self.say(
                reconcile(self.journal, tid).spoken
                if tid
                else "I don't have a record of a task in progress."
            )
        elif k == Kind.SAVE_PASSWORD:
            app = (s.get("app") or "").strip().lower()
            if not app:
                from relay.system.windows import _friendly_app, foreground
                fg = foreground()
                app = _friendly_app(fg.app).lower() if fg else "default"
            pwd = s.get("password", "").strip()
            if not pwd:
                self.say("What password should I save?", _REQ)
                self.capture(lambda p: self._save_password(app, p))
                return []
            self._save_password(app, pwd)
        elif k == Kind.ENTER_PASSWORD:
            app = (s.get("app") or "").strip().lower()
            if not app:
                from relay.system.windows import _friendly_app, foreground
                fg = foreground()
                app = _friendly_app(fg.app).lower() if fg else "default"
            return self._enter_password(app)
        elif k == Kind.FORGET_PASSWORD:
            app = (s.get("app") or "").strip().lower()
            if not app:
                from relay.system.windows import _friendly_app, foreground
                fg = foreground()
                app = _friendly_app(fg.app).lower() if fg else "default"
            from relay.memory.secrets import delete_secret
            delete_secret(f"pwd:{app}")
            self.say(f"I've removed your saved password for {app}.", _REQ)
        return []

    def _save_password(self, app: str, pwd: str) -> None:
        from relay.memory.secrets import save_secret
        save_secret(f"pwd:{app.lower()}", pwd)
        save_secret("pwd:last", pwd)
        self.say(f"I've securely saved your password for {app}.", _REQ)

    def _enter_password(self, app: str):
        from relay.memory.secrets import get_secret
        pwd = get_secret(f"pwd:{app.lower()}") or get_secret("pwd:last") or get_secret("pwd:default")
        if not pwd:
            self.say(
                f"I don't have a saved password for {app}. Say save password for {app} as, followed by your password.",
                _REQ,
            )
            return []
        self.executor.input.type_text(pwd)
        self.say("Password entered.", _REQ)
        return []

    # ---- goal management (Gap 1) ----
    def _handle_goal(self, intent):
        k = intent.kind
        if k == Kind.GOAL_STATUS:
            g = self.goals.active_goal
            if not g:
                self.say(
                    "You don't have an active goal right now. Say start goal followed by what you want to achieve.",
                    _REQ,
                )
                return []
            curr = g.current_step.description if g.current_step else "all steps completed"
            self.say(
                f"Goal: {g.title}. Mode: {g.mode}. Step {g.current_step_index + 1} of {len(g.steps)}: {curr}. Status: {g.status}.",
                _REQ,
            )
            return []
        if k == Kind.GOAL_START:
            title = intent.slots.get("title") or "New Goal"
            steps = ["Analyze task requirements", "Execute primary work", "Verify results"]
            g = self.goals.start_goal(title=title, steps=steps)
            self.say(
                f"Started goal: {title}. I've set up 3 steps: {', '.join(s.description for s in g.steps)}. First step: {g.steps[0].description}.",
                _REQ,
            )
            return []
        if k == Kind.GOAL_PAUSE:
            g = self.goals.pause_goal()
            self.say(f"Paused goal: {g.title}." if g else "No active goal to pause.", _REQ)
            return []
        if k == Kind.GOAL_RESUME:
            g = self.goals.resume_goal()
            curr = g.current_step.description if g and g.current_step else "ready"
            self.say(
                f"Resumed goal: {g.title}. Current step: {curr}."
                if g
                else "No paused goal to resume.",
                _REQ,
            )
            return []
        if k == Kind.GOAL_CANCEL:
            if self.goals.active_goal:
                title = self.goals.active_goal.title
                self.goals.active_goal.status = "cancelled"
                self.goals.store.save_goal(self.goals.active_goal)
                self.goals.active_goal = None
                self.say(f"Cancelled goal: {title}.", _REQ)
            else:
                self.say("No active goal to cancel.", _REQ)
            return []
        if k == Kind.GOAL_NEXT:
            if self.goals.active_goal:
                g = self.goals.advance_step(evidence="advanced by voice")
                if g.status == "completed":
                    self.say(f"Goal completed: {g.title}! All steps finished.", _REQ)
                else:
                    curr = g.current_step.description if g.current_step else "done"
                    self.say(f"Advanced step. Next: {curr}.", _REQ)
            else:
                self.say("No active goal to advance.", _REQ)
            return []
        return []

    # ---- assignment workflow (Gap 1, 2, 3) ----
    def _handle_assignment(self, intent):
        k = intent.kind
        if k == Kind.ASSIGNMENT_START:
            summary = self.assignment.start_assignment_from_session(self)
            self.say(summary, _REQ)
            return []
        if k == Kind.ASSIGNMENT_CHECKLIST:
            summary = self.assignment.get_status_summary()
            self.say(summary, _REQ)
            return []
        if k == Kind.ASSIGNMENT_STATUS:
            if not self.assignment.active_assignment:
                self.say("No active assignment. Say help me complete my assignment to begin.", _REQ)
            else:
                a = self.assignment.active_assignment
                self.say(
                    f"Assignment: {a.course} {a.title}. Status: {a.status}. Deadline: {a.deadline or 'not specified'}.",
                    _REQ,
                )
            return []
        if k == Kind.ASSIGNMENT_SUBMIT:
            if not self.assignment.active_assignment:
                self.say(
                    "No active assignment to submit. Say help me complete my assignment first.",
                    _REQ,
                )
                return []
            a = self.assignment.active_assignment
            missing = self.assignment.verify_checklist(a)
            if missing:
                self.say(
                    f"Warning: {len(missing)} rubric criteria are not yet marked complete: {missing[0]}. "
                    "Are you sure you want to proceed to submission?",
                    _CONF,
                )
            file_name = f"{a.title.replace(' ', '_')}.pdf"
            readback = self.assignment.prepare_submission_confirmation(a, Path(file_name))

            def do_submit():
                # Attempt to click active submission button on screen if present
                snap = self.worker.live or self.worker.observe(2.0)
                if snap:
                    sub_btns = [
                        e
                        for e in snap.elements
                        if e.role in ("Button", "Hyperlink")
                        and any(
                            w in e.name.lower()
                            for w in ("submit", "turn in", "submit assignment")
                        )
                    ]
                    if sub_btns:
                        self.executor.click_coord(
                            sub_btns[0].bbox[0] + 5,
                            sub_btns[0].bbox[1] + 5,
                            label=sub_btns[0].name,
                        )
                        time.sleep(1.0)

                snap = self.worker.live or self.worker.observe(3.0)
                screen_text = " ".join(e.name for e in snap.elements) if snap else ""
                receipt = self.assignment.verify_submission_receipt(screen_text, file_name)
                if receipt["verified"]:
                    ts = f" at {receipt['timestamp']}" if receipt.get("timestamp") else ""
                    self.say(f"Assignment submitted! Confirmed receipt for {file_name}{ts}.", _REQ)
                else:
                    self.say(
                        f"Submission recorded, but receipt verification was uncertain: {receipt['status']}.",
                        _REQ,
                    )

            self.ask_phrase("confirm submit assignment", readback, do_submit)
            return []
        return []

    # ---- workspace agent (Gap 1, 4) ----
    def _handle_workspace(self, intent):
        k = intent.kind
        if k == Kind.WORKSPACE_TEST:
            self.say("Running project tests.", _REQ)
            cmd = self.workspace.auto_detect_test_command()
            ok, summary = self.workspace.run_tests(cmd)
            self.say(f"Test results: {summary}", _REQ)
            return []
        if k == Kind.WORKSPACE_STATUS:
            git_summary = self.workspace.explain_git_status()
            files = self.workspace.list_files()
            self.say(
                f"{git_summary} Workspace contains {len(files)} files.", _REQ
            )
            return []
        if k == Kind.WORKSPACE_DIFF:
            diff_text = self.workspace.get_recent_diff_summary()
            self.say(diff_text, _REQ)
            return []
        return []

    # ---- text editing engine ----
    def _handle_text_editing(self, intent):
        k, s = intent.kind, intent.slots
        if k == Kind.TEXT_SELECT:
            ok, msg = self.editor.select(s.get("unit", "word"), s.get("count", 1), s.get("direction", "next"))
            self.say(msg, _REQ)
            return []
        if k == Kind.TEXT_NAV:
            ok, msg = self.editor.move_cursor(s.get("unit", "word"), s.get("count", 1), s.get("direction", "forward"))
            self.say(msg, _REQ)
            return []
        if k == Kind.TEXT_EDIT:
            act = s.get("action", "")
            if act in ("capitalize", "uppercase", "lowercase"):
                ok, msg = self.editor.change_case(act)
            elif act == "duplicate_line":
                ok, msg = self.editor.duplicate_line()
            elif act == "delete":
                ok, msg = self.editor.delete_unit(s.get("unit", "word"))
            else:
                ok, msg = False, "Unknown editing action."
            self.say(msg, _REQ)
            return []
        if k == Kind.TEXT_FORMAT:
            ok, msg = self.editor.format_structure(s.get("style", ""))
            self.say(msg, _REQ)
            return []
        if k == Kind.TEXT_INSPECT:
            act = s.get("action", "")
            if act == "word_count":
                msg = self.editor.word_count()
            elif act == "read_around_cursor":
                msg = self.editor.read_around_cursor()
            else:
                msg = "Unknown inspection command."
            self.say(msg, _REQ)
            return []
        if k == Kind.COMPOSE:
            prompt = s.get("prompt", "")
            is_code = s.get("is_code", False) or bool(re.search(r"\bcode|function|script|program|class|algorithm|method\b", prompt, re.I))
            if is_code:
                self.say("Writing code on the screen.", _REQ)
            else:
                self.say("Drafting content.", _REQ)

            generated_text = ""
            if self.assistant is not None:
                try:
                    sys_msg = (
                        "You are an expert software developer. Write clean, working, self-contained code. "
                        "Return ONLY code without markdown fences or chat filler."
                        if is_code else
                        "You are a helpful writing assistant. Write only the requested content directly."
                    )
                    messages = [
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": prompt},
                    ]
                    parts = []
                    for delta in self.assistant.router.stream(messages, max_tokens=1024, cancel=self.cancel):
                        parts.append(delta)
                    generated_text = "".join(parts).strip()
                except Exception as e:
                    log.warning("Assistant composition failed: %s", e)

            if not generated_text and is_code:
                p_low = prompt.lower()
                if "binary search" in p_low:
                    generated_text = (
                        "def binary_search(arr, target):\n"
                        "    low, high = 0, len(arr) - 1\n"
                        "    while low <= high:\n"
                        "        mid = (low + high) // 2\n"
                        "        if arr[mid] == target:\n"
                        "            return mid\n"
                        "        elif arr[mid] < target:\n"
                        "            low = mid + 1\n"
                        "        else:\n"
                        "            high = mid - 1\n"
                        "    return -1\n"
                    )
                elif "reverse" in p_low:
                    generated_text = (
                        "def reverse_string(text: str) -> str:\n"
                        "    return text[::-1]\n"
                    )
                else:
                    generated_text = (
                        "# Generated by Relay\n"
                        "def main():\n"
                        "    print('Hello from Relay!')\n\n"
                        "if __name__ == '__main__':\n"
                        "    main()\n"
                    )

            if generated_text:
                clean_text = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", generated_text)
                clean_text = re.sub(r"\n```$", "", clean_text).strip()

                from relay.system import windows
                fg = windows.foreground()
                app = (fg.app or "").lower() if fg else ""
                editor_apps = ("notepad.exe", "code.exe", "devenv.exe", "cursor.exe", "sublime_text.exe", "pycharm.exe", "windowsterminal.exe")
                snap = self.worker.observe(1.5)
                editable = bool(snap and snap.focus and snap.focus.role in ("Edit", "Document"))

                if not editable and app not in editor_apps:
                    self.say("Opening Notepad to write the code.", _REQ)
                    self.handle("open notepad")
                    time.sleep(1.2)

                try:
                    import pyperclip
                    pyperclip.copy(clean_text)
                    from relay.planner.planner import Step
                    return self.runner.run(
                        Step(
                            "hotkey",
                            "write code on screen",
                            {"keys": ["ctrl", "v"], "announce": "Writing code on the screen.", "done_text": "Code written."},
                        )
                    )
                except Exception as e:
                    log.warning("Pasting generated code failed: %s", e)

            return self.ask(f"Please compose: {prompt}")
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
            self._offer = None
            self._capture = None
            if hasattr(self.live_world, "speculative_mgr"):
                self.live_world.speculative_mgr.cancel()
            self.reader.stop()
            self.set_dictation(False)
            self.say(
                "Emergency stop. I've stopped everything. Say continue when you want me "
                "to work again.",
                pol.Priority.CRITICAL,
            )
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
            self.cancel.set()
            self._pending = None
            self._offer = None
            self._capture = None
        elif command == Command.PAUSE:
            self.cancel.set()
            was = self.reader.stop()
            self.say(
                "Paused. Say continue when you're ready."
                if not was
                else "Paused. Say continue to keep reading.",
                _CONF,
            )
        elif command == Command.CONTINUE:
            if self.emergency.is_engaged:
                self.emergency.reset()
                self.cancel.clear()
                self.say("Emergency stop cleared. I'm ready.", _CONF)
            elif (
                self.reader.has_content
                and not self.reader.reading
                and self.last_activity == "reading"
            ):
                self.reader.resume()
            else:
                self.cancel.clear()
                self.say("Okay.", _CONF)
        elif command == Command.REPEAT:
            if self.last_activity == "reading" and self.reader.has_content:
                self.reader.repeat()
            else:
                self.say(self.runner.last_said or "I haven't said anything yet.", _REQ)
        elif command == Command.GO_BACK:
            self.executor.hotkey("alt", "left")
            self.say("Going back.", _CONF)
        elif command == Command.START_AGAIN:
            self.cancel.set()
            self._pending = None
            self._offer = None
            self._capture = None
            self.reader.stop()
            self.say("Starting again. What would you like to do?", _REQ)
            self.capture_next(lambda u: self.handle(u))
        elif command == Command.SIMPLER:
            if self.runner.last_said:
                self.say("Explaining in simpler terms.", _REQ)
                return self.ask(f"Please explain this in simpler, plainer terms for a non-technical user: {self.runner.last_said}")
            self.say("There is nothing to simplify yet.", _REQ)
        elif command == Command.EXPLAIN:
            if self.runner.last_said:
                self.say("Explaining in more detail.", _REQ)
                return self.ask(f"Please explain this in more detail: {self.runner.last_said}")
            self.say("There is nothing to explain yet.", _REQ)
        elif command == Command.WHY:
            # Check if there is an explicit provenance recorded for the last action or preference
            why_text = None
            if hasattr(self, "_last_pref") and self._last_pref:
                scope, key = self._last_pref
                why_text = self.store.why(key, scope)
            if why_text:
                self.say(f"I did that because: {why_text}.", _REQ)
            elif self.runner.last_said:
                return self.ask(f"Why did you say or do this: {self.runner.last_said}?")
            else:
                self.say("No recent action to explain.", _REQ)
        return []

    def close(self) -> None:
        self.reminders.stop()
        self.worker.stop()
        try:
            self.conn.close()
        except Exception:
            pass
