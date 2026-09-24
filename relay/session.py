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
from relay.memory.task_context import TaskContext
from relay.perception import UIAWorker
from relay.planner import TransparentRunner, plan
from relay.safety import PermissionEngine
from relay.verifier import Verifier


class Session:
    def __init__(self, speak=None, bus=None, db_path: str = ":memory:") -> None:
        self.emergency = EmergencyStop()
        self.cancel = threading.Event()
        self._speak = speak
        self.bus = bus
        self.worker = UIAWorker(bus=bus)
        self.worker.start()
        engine = PermissionEngine()
        journal = ActionJournal(connect(db_path))
        self.task_id = new_task_id()
        self.ctx = TaskContext(self.task_id)
        self.executor = Executor(engine, self.worker, journal, self.task_id,
                                 emergency=self.emergency, confirm=self._confirm)
        self.verifier = Verifier(self.worker, journal)
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
        self.cancel.clear()
        steps, clarification = plan(intent)
        if clarification:
            self.say(clarification)
            return []
        return self.runner.run(steps, cancel=self.cancel)

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
