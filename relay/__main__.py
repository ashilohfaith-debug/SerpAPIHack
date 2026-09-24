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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="relay", description="RELAY accessibility assistant")
    p.add_argument("--version", action="version", version=f"relay {__version__}")
    p.add_argument("--selftest", action="store_true", help="verify core wiring and exit")
    p.add_argument("--voice-selftest", action="store_true",
                   help="offline TTS->STT round-trip (no mic) and exit")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.voice_selftest:
        return _voice_selftest()
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
