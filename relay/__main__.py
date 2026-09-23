"""RELAY command-line entry point.

Essential runtime wiring will grow here phase by phase. For now it supports:
  relay --version    print the version
  relay --selftest   wire up the P2 core (bus, state machines, permission engine,
                     in-memory journal) and confirm it imports and runs, without
                     touching the real desktop, audio or any model.
"""

from __future__ import annotations

import argparse
import sys

from relay import __version__


def _selftest() -> int:
    from relay.config import Config, user_data_dir
    from relay.core import EmergencyStop, EventBus, new_task_id
    from relay.core.state import TaskState, VoiceState, task_machine, voice_machine
    from relay.diagnostics import get_logger, setup_logging
    from relay.memory.db import connect
    from relay.memory.journal import ActionJournal, ActionRecord, ExecState
    from relay.safety import Action, PermissionEngine

    setup_logging("INFO")
    log = get_logger("selftest")

    cfg = Config.load()
    bus = EventBus()
    events: list[str] = []
    bus.subscribe("*", lambda e: events.append(e.type))

    tid = new_task_id()
    task = task_machine(tid, bus)
    voice = voice_machine("selftest", bus)
    task.transition(TaskState.PLANNING)
    voice.transition(VoiceState.LISTENING)

    engine = PermissionEngine()
    d1 = engine.classify(Action(kind="read_screen"))
    d2 = engine.classify(Action(kind="click", target_label="Delete", target_app="Notepad"))
    assert d1.risk.value == "safe"
    assert d2.requires_confirmation

    conn = connect(":memory:")
    j = ActionJournal(conn)
    j.append(ActionRecord(task_id=tid, action_id="act1", execution_state=ExecState.PROPOSED))
    assert len(j.for_task(tid)) == 1

    es = EmergencyStop()
    flushed = []
    es.register_flush(lambda: flushed.append(True))
    es.engage("selftest")
    assert es.is_engaged and flushed

    log.info("selftest OK: events=%s wake=%s", len(events), cfg.wake_word)
    print(f"RELAY {__version__} selftest OK "
          f"(events={len(events)}, permission+journal+emergency wired, data_dir={user_data_dir()})")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="relay", description="RELAY accessibility assistant")
    p.add_argument("--version", action="version", version=f"relay {__version__}")
    p.add_argument("--selftest", action="store_true", help="verify core wiring and exit")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
