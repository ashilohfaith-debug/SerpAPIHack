"""Session orchestrator — one utterance in, transparent narrated action out.

Ties the pieces together: parse the utterance into an Intent, handle control words
(stop/pause/cancel/emergency) immediately, otherwise plan and run it through the
TransparentRunner. RELAY acts only in response to a command and narrates every step;
it does not loop on its own. High-risk actions that need a spoken confirmation phrase
are announced and declined here in Essential P6 (the phrase flow arrives in P8).
"""

from __future__ import annotations

import threading

from relay.audio.wake import Command
from relay.core import EmergencyStop, new_task_id
from relay.executor import Executor
from relay.intent import Kind, parse
from relay.memory.db import connect
from relay.memory.journal import ActionJournal
from relay.memory.reconcile import latest_task_id, reconcile
from relay.memory.store import MemoryStore
from relay.memory.task_context import TaskContext
from relay.perception import UIAWorker
from relay.planner import TransparentRunner, plan
from relay.safety import PermissionEngine
from relay.verifier import Verifier

_MEMORY_KINDS = {
    Kind.REMEMBER, Kind.WHAT_REMEMBER, Kind.WHY_REMEMBER, Kind.FORGET,
    Kind.CLEAR_HISTORY, Kind.EXPORT_PREFS, Kind.WHAT_DOING,
}


class Session:
    def __init__(self, speak=None, bus=None, db_path: str = ":memory:") -> None:
        self.emergency = EmergencyStop()
        self.cancel = threading.Event()
        self._speak = speak
        self.bus = bus
        self.worker = UIAWorker(bus=bus)
        self.worker.start()
        engine = PermissionEngine()
        self.conn = connect(db_path)
        self.journal = ActionJournal(self.conn)
        self.store = MemoryStore(self.conn)
        self.task_id = new_task_id()
        self.ctx = TaskContext(self.task_id)
        self._last_pref: tuple[str, str] | None = None  # for "forget this" / "why"
        self.executor = Executor(engine, self.worker, self.journal, self.task_id,
                                 emergency=self.emergency, confirm=self._confirm)
        self.verifier = Verifier(self.worker, self.journal)
        # Apply persisted global narration preference, if any (L3).
        self.narration_mode = self.store.get_pref("narration_mode", default="quick")
        self.runner = TransparentRunner(self.executor, self.worker, self.verifier,
                                        self.ctx, speak=speak, emergency=self.emergency,
                                        bus=bus)

    def say(self, text: str) -> None:
        self.runner.say(text)

    def _confirm(self, decision) -> bool:
        # Essential P6: announce the exact consequence and decline high-risk actions
        # that need a spoken confirmation phrase (that flow lands in P8). This is safe
        # by default — RELAY never performs a high-risk action without real consent.
        self.say(decision.spoken_summary)
        self.say("This needs your confirmation, which I'll support by voice soon. "
                 "For now I won't do it automatically.")
        return False

    def handle(self, utterance: str):
        intent = parse(utterance)
        if intent.kind == Kind.CONTROL:
            return self._handle_control(intent.slots.get("command"))
        if intent.kind in _MEMORY_KINDS:
            return self._handle_memory(intent)
        self.cancel.clear()
        steps, clarification = plan(intent)
        if clarification:
            self.say(clarification)
            return []
        return self.runner.run(steps, cancel=self.cancel)

    def _handle_memory(self, intent):
        k, s = intent.kind, intent.slots
        if k == Kind.REMEMBER:
            if "mode" in s:
                scope = self._app_key(s.get("app", ""))
                self.store.set_pref("narration_mode", s["mode"], scope=scope)
                self._last_pref = (scope, "narration_mode")
                where = f" in {s['app']}" if s.get("app") else ""
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
            if tid is None:
                self.say("I don't have a record of a task in progress.")
            else:
                self.say(reconcile(self.journal, tid).spoken)
        return []

    @staticmethod
    def _app_key(app: str) -> str:
        from relay.planner.runner import _APP_EXE
        a = app.lower().strip()
        return _APP_EXE.get(a, a if a.endswith(".exe") else (f"{a}.exe" if a else ""))

    def _handle_control(self, command: str | None):
        if command == Command.EMERGENCY_STOP:
            self.emergency.engage("user")
            self.say("Emergency stop. I've stopped everything.")
        elif command == Command.CANCEL_TASK:
            self.cancel.set()
            self.say("Cancelling.")
        elif command == Command.STOP_TALKING:
            self.say("")  # a real speech queue interrupts here (P3 barge-in)
        elif command == Command.PAUSE:
            self.cancel.set()
            self.say("Paused. Say continue when you're ready.")
        elif command == Command.CONTINUE:
            self.say("Okay.")
        elif command == Command.REPEAT:
            self.say("Repeating.")
        return []

    def close(self) -> None:
        self.worker.stop()
        try:
            self.conn.close()
        except Exception:
            pass
