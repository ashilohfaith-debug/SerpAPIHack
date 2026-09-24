"""Session orchestrator — one utterance in, transparent narrated action out.

Parses the utterance, handles control words (stop/pause/cancel/emergency) and memory
and accessibility commands directly, and otherwise plans and runs it through the
TransparentRunner. RELAY acts only in response to a command and narrates every step;
it never loops on its own.

High-risk actions do not run automatically: the runner asks the Session for an
accessible spoken confirmation (an action-specific phrase, never a bare "yes"); the
most sensitive actions require a keyboard/Windows-auth confirm and are declined by
voice. Narration verbosity follows the current mode; onboarding is fully spoken.
"""

from __future__ import annotations

import threading

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
from relay.executor import Executor
from relay.intent import Kind, parse
from relay.memory.db import connect
from relay.memory.journal import ActionJournal
from relay.memory.reconcile import latest_task_id, reconcile
from relay.memory.store import MemoryStore
from relay.memory.task_context import TaskContext
from relay.narration import policy as pol
from relay.perception import UIAWorker
from relay.planner import TransparentRunner, plan
from relay.safety import ConfirmationStrength, PermissionEngine
from relay.verifier import Verifier

_MEMORY_KINDS = {
    Kind.REMEMBER, Kind.WHAT_REMEMBER, Kind.WHY_REMEMBER, Kind.FORGET,
    Kind.CLEAR_HISTORY, Kind.EXPORT_PREFS, Kind.WHAT_DOING,
}
_ACCESS_KINDS = {
    Kind.SET_MODE, Kind.READ_DIALOG, Kind.NEXT_ELEMENT, Kind.PREV_ELEMENT, Kind.SPELL,
}
_REQ = pol.Priority.REQUESTED
_CONF = pol.Priority.CONFIRMATION


class Session:
    def __init__(self, speak=None, bus=None, db_path: str = ":memory:") -> None:
        self.emergency = EmergencyStop()
        self.cancel = threading.Event()
        self._speak = speak
        self.bus = bus
        self.worker = UIAWorker(bus=bus)
        self.worker.start()
        self.engine = PermissionEngine()
        self.conn = connect(db_path)
        self.journal = ActionJournal(self.conn)
        self.store = MemoryStore(self.conn)
        self.task_id = new_task_id()
        self.ctx = TaskContext(self.task_id)
        self._last_pref: tuple[str, str] | None = None
        self._pending: PendingConfirmation | None = None
        self._nav_index = -1
        self.executor = Executor(self.engine, self.worker, self.journal, self.task_id,
                                 emergency=self.emergency, confirm=lambda d: False)
        self.verifier = Verifier(self.worker, self.journal)
        self.narration_mode = self.store.get_pref("narration_mode", default="quick")
        self.runner = TransparentRunner(
            self.executor, self.worker, self.verifier, self.ctx, speak=speak,
            emergency=self.emergency, bus=bus, engine=self.engine,
            on_confirm_needed=self._on_confirm_needed, mode=self.narration_mode)

    # ---- narration ----
    def say(self, text: str, priority: int = pol.Priority.TASK) -> None:
        self.runner.say(text, priority)

    def onboard(self) -> None:
        wake = self.store.get_pref("wake_word", default="relay")
        for line in onboarding_script(wake_word=wake, first_run=is_first_run()):
            self.say(line, _REQ)
        mark_onboarded()

    # ---- dispatch ----
    def handle(self, utterance: str):
        if self._pending is not None:
            return self._resolve_pending(utterance)
        intent = parse(utterance)
        if intent.kind == Kind.CONTROL:
            return self._handle_control(intent.slots.get("command"))
        if intent.kind in _MEMORY_KINDS:
            return self._handle_memory(intent)
        if intent.kind in _ACCESS_KINDS:
            return self._handle_access(intent)
        self.cancel.clear()
        steps, clarification = plan(intent)
        if clarification:
            self.say(clarification, _REQ)
            return []
        return self.runner.run(steps, cancel=self.cancel)

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

    def _resolve_pending(self, utterance: str):
        p = self._pending
        low = utterance.lower().strip()
        if p.phrase in low or low == p.phrase:
            self._pending = None
            self.say("Confirmed.", _CONF)
            return [p.retry()]
        if is_cancel(low):
            self._pending = None
            self.say("Cancelled — I won't do it.", _CONF)
            return []
        p.reprompts += 1
        if p.reprompts > 2:
            self._pending = None
            self.say("Okay, cancelling that.", _CONF)
            return []
        self.say(f"To confirm, say {p.phrase}, or say cancel.", _CONF)
        return []

    # ---- accessibility read / navigate / spell / mode ----
    def _handle_access(self, intent):
        k, s = intent.kind, intent.slots
        if k == Kind.SET_MODE:
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
            snap = self.worker.observe(3.0)
            els = [e for e in (snap.elements if snap else []) if e.name]
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
                self._last_pref = ("", f"note:{fact[:40]}") if ok else None
                self.say("I've noted that." if ok else
                         "I won't store that — it looks sensitive, so I'm keeping it out.")
        elif k == Kind.WHAT_REMEMBER:
            self.say(self.store.remember_summary())
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

    def _handle_control(self, command: str | None):
        if command == Command.EMERGENCY_STOP:
            self.emergency.engage("user")
            self.say("Emergency stop. I've stopped everything.", _CONF)
        elif command == Command.CANCEL_TASK:
            self.cancel.set()
            self._pending = None
            self.say("Cancelling.", _CONF)
        elif command == Command.STOP_TALKING:
            pass  # a real speech queue interrupts here (P3 barge-in)
        elif command == Command.PAUSE:
            self.cancel.set()
            self.say("Paused. Say continue when you're ready.", _CONF)
        elif command == Command.CONTINUE:
            self.say("Okay.", _CONF)
        elif command == Command.REPEAT:
            self.say(self.runner.last_said or "I haven't said anything yet.", _REQ)
        return []

    def close(self) -> None:
        self.worker.stop()
        try:
            self.conn.close()
        except Exception:
            pass
