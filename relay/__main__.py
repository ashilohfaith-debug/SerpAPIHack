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


def _voice_selftest() -> int:
    """Offline voice round-trip with no microphone: synthesize a known phrase with
    the configured TTS (Piper if installed, else SAPI), transcribe it back with the
    offline STT, and check the words survived. Proves the offline voice pipeline."""
    import numpy as np

    from relay.audio import WhisperSTT, make_tts
    from relay.audio.wake import detect_wake, match_command
    from relay.diagnostics import get_logger, setup_logging

    setup_logging("INFO")
    log = get_logger("voice-selftest")

    phrase = "relay please open the file and read the text out loud"
    tts = make_tts(prefer_piper=True)
    audio, sr = tts.synth_to_array(phrase)
    if sr != 16000 and len(audio):
        n = int(len(audio) * 16000 / sr)
        audio = np.interp(np.linspace(0, len(audio), n, endpoint=False),
                          np.arange(len(audio)), audio).astype(np.float32)
    text = WhisperSTT().transcribe(audio)
    woke, cmd = detect_wake(text)
    log.info("TTS engine=%s stt=%r woke=%s cmd=%r", type(tts).__name__, text, woke, cmd)
    want = set(phrase.split()) - {"relay"}
    heard = set(text.lower().replace(".", "").replace(",", "").split())
    ok = len(want & heard) / len(want) >= 0.7  # content survived round-trip
    print(f"voice-selftest {'OK' if ok else 'FAILED'}: "
          f"tts={type(tts).__name__} heard={text!r} wake={woke} command={cmd!r}")
    print(f"  (control-word check: 'stop' -> {match_command('stop')})")
    return 0 if ok else 1


def _observe() -> int:
    """Read the current foreground window via UI Automation and describe it —
    proves real perception on this machine."""
    from relay.diagnostics import setup_logging
    from relay.perception import UIAWorker

    setup_logging("INFO")
    worker = UIAWorker()
    snap = worker.observe(timeout=5.0)
    if snap is None:
        print("observe: timed out or no foreground window")
        return 1
    print(snap.summary())
    if snap.dialogs:
        for d in snap.dialogs:
            print(f"  dialog: {d.title!r} buttons={list(d.buttons)}")
    focus_role = snap.focus.role if snap.focus else None
    focus_name = snap.focus.name if snap.focus else ""
    print(f"  focus: {focus_role} {focus_name!r}")
    print(f"  first controls (of {len(snap.elements)}):")
    for e in snap.elements[:12]:
        name = (e.name[:40]) if e.name else ""
        print(f"    [{e.uid}] {e.role:12} {name!r:44} actions={list(e.actions)}")
    worker.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="relay", description="RELAY accessibility assistant")
    p.add_argument("--version", action="version", version=f"relay {__version__}")
    p.add_argument("--selftest", action="store_true", help="verify core wiring and exit")
    p.add_argument("--voice-selftest", action="store_true",
                   help="offline TTS->STT round-trip (no mic) and exit")
    p.add_argument("--observe", action="store_true",
                   help="describe the current foreground window via UI Automation")
    p.add_argument("--demo-notepad", action="store_true",
                   help="real perceive->act->verify demo: create + save + verify a file in Notepad")
    p.add_argument("--demo-fail", action="store_true",
                   help="prove failures are reported honestly (open a nonexistent app)")
    p.add_argument("--demo-transparent", action="store_true",
                   help="run a real command sequence, narrating every action and change")
    p.add_argument("--do", metavar="COMMAND",
                   help="run one spoken command transparently against the real desktop")
    p.add_argument("--demo-memory", action="store_true",
                   help="offline five-layer memory demo: preference persists across restart")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.voice_selftest:
        return _voice_selftest()
    if args.observe:
        return _observe()
    if args.demo_notepad:
        from relay.demo import notepad_demo
        return notepad_demo()
    if args.demo_fail:
        from relay.demo import injected_failure_demo
        return injected_failure_demo()
    if args.demo_transparent:
        from relay.demo import transparent_demo
        return transparent_demo()
    if args.do:
        from relay.demo import do_command
        return do_command(args.do)
    if args.demo_memory:
        from relay.demo import memory_demo
        return memory_demo()
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
