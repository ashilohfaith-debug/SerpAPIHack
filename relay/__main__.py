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
    print(
        f"RELAY {__version__} selftest OK "
        f"(events={len(events)}, permission+journal+emergency wired, data_dir={user_data_dir()})"
    )
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
        audio = np.interp(
            np.linspace(0, len(audio), n, endpoint=False), np.arange(len(audio)), audio
        ).astype(np.float32)
    text = WhisperSTT().transcribe(audio)
    woke, cmd = detect_wake(text)
    log.info("TTS engine=%s stt=%r woke=%s cmd=%r", type(tts).__name__, text, woke, cmd)
    want = set(phrase.split()) - {"relay"}
    heard = set(text.lower().replace(".", "").replace(",", "").split())
    ok = len(want & heard) / len(want) >= 0.7  # content survived round-trip
    print(
        f"voice-selftest {'OK' if ok else 'FAILED'}: "
        f"tts={type(tts).__name__} heard={text!r} wake={woke} command={cmd!r}"
    )
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


def _starting_cue() -> None:
    """Loading the voice and speech models takes 5-10 s on a basic laptop. A blind user
    who just pressed Ctrl+Alt+R must not sit in silence wondering if anything happened:
    say so at once with Windows' built-in voice (asynchronous, returns immediately)."""
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voice.Speak("Starting Relay. One moment.", 1)  # 1 = SVSFlagsAsync
        _starting_cue.voice = voice  # keep it alive while speaking
    except Exception:
        pass


def _start(panel: bool = False, toggle: bool = False) -> int:
    """Run the app. Launched from the Ctrl+Alt+R shortcut there is no console, so a
    start-up failure must be SPOKEN, or a blind user just hears silence. With
    ``toggle`` (the shortcut), pressing the key while RELAY runs closes it instead."""
    from relay.diagnostics import get_logger, setup_logging

    setup_logging("INFO")
    if toggle:
        from relay.core.single_instance import QuitSignal, SingleInstance

        probe = SingleInstance()
        if probe.acquire():
            probe.release()  # not running: start it
        elif QuitSignal.request():
            return 0  # running: it says goodbye and closes
    _starting_cue()
    try:
        from relay.app import RelayApp

        return RelayApp(panel=panel).run()
    except Exception as e:
        get_logger("main").exception("Relay failed to start: %s", e)
        reason = str(e).split("\n")[0][:120] or type(e).__name__
        try:
            from relay.audio import SapiTTS

            SapiTTS().speak_blocking(
                "Sorry, Relay could not start. " + reason + ". Details are in the Relay log file."
            )
        except Exception:
            print("Relay could not start:", reason)
        return 1


def main(argv: list[str] | None = None) -> int:
    from relay.envfile import load_env

    load_env()  # the developer's keys/settings from .env (optional)
    return _main(argv)


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="relay", description="RELAY accessibility assistant")
    p.add_argument("--version", action="version", version=f"relay {__version__}")
    p.add_argument("--selftest", action="store_true", help="verify core wiring and exit")
    p.add_argument(
        "--voice-selftest",
        action="store_true",
        help="offline TTS->STT round-trip (no mic) and exit",
    )
    p.add_argument(
        "--observe",
        action="store_true",
        help="describe the current foreground window via UI Automation",
    )
    p.add_argument(
        "--demo-notepad",
        action="store_true",
        help="real perceive->act->verify demo: create + save + verify a file in Notepad",
    )
    p.add_argument(
        "--demo-fail",
        action="store_true",
        help="prove failures are reported honestly (open a nonexistent app)",
    )
    p.add_argument(
        "--demo-transparent",
        action="store_true",
        help="run a real command sequence, narrating every action and change",
    )
    p.add_argument(
        "--do",
        metavar="COMMAND",
        help="run one spoken command transparently against the real desktop",
    )
    p.add_argument(
        "--demo-memory",
        action="store_true",
        help="offline five-layer memory demo: preference persists across restart",
    )
    p.add_argument(
        "--onboard",
        action="store_true",
        help="speak the voice-only onboarding through the local Piper voice",
    )
    p.add_argument(
        "--demo-confirm",
        action="store_true",
        help="show the spoken-confirmation flow: a casual reply never acts",
    )
    p.add_argument(
        "--capabilities", action="store_true", help="print the honest supported-application matrix"
    )
    p.add_argument(
        "--demo-explorer",
        action="store_true",
        help="read-only: open File Explorer and describe it (nothing changed)",
    )
    p.add_argument(
        "--panel",
        action="store_true",
        help="start the optional accessible web panel (authenticated, loopback)",
    )
    p.add_argument(
        "--start",
        action="store_true",
        help="run RELAY: spoken onboarding + live voice loop (say 'Relay' + a command)",
    )
    p.add_argument(
        "--with-panel", action="store_true", help="with --start, also serve the accessible panel"
    )
    p.add_argument(
        "--toggle",
        action="store_true",
        help="start RELAY, or close it if it's already running (Ctrl+Alt+R)",
    )
    p.add_argument("--models-status", action="store_true", help="report managed model files")
    p.add_argument(
        "--setup-models",
        action="store_true",
        help="download/verify Essential models for offline use",
    )
    p.add_argument(
        "--acceptance",
        action="store_true",
        help="run the offline acceptance suite (safe, no desktop changes)",
    )
    p.add_argument(
        "--install",
        action="store_true",
        help="create the desktop shortcut (Ctrl+Alt+R) and Start-menu entry",
    )
    p.add_argument("--uninstall", action="store_true", help="remove Relay's shortcuts")
    p.add_argument(
        "--autostart",
        choices=["on", "off"],
        help="start Relay automatically when you sign in to Windows",
    )
    p.add_argument("--say", metavar="TEXT", help="speak TEXT with Relay's voice and exit")
    p.add_argument(
        "--check",
        action="store_true",
        help="check everything works on this computer (spoken result)",
    )
    p.add_argument("--quiet", action="store_true", help="with --check: don't speak the result")
    p.add_argument(
        "--llm-check",
        action="store_true",
        help="measure the AI assistant's latency through your router",
    )
    p.add_argument(
        "--llm-tune",
        action="store_true",
        help="time your router's models and use the fastest that follow the rules",
    )
    p.add_argument(
        "--demo-daily",
        action="store_true",
        help="safe offline demo of everyday skills (time, battery, maths, notes...)",
    )
    p.add_argument(
        "--update",
        action="store_true",
        help="check for updates from GitHub and update relay.exe in place",
    )
    args = p.parse_args(argv)
    if args.update:
        from relay.update import handle_update_command

        handle_update_command(speak_cb=print)
        return 0
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
    if args.onboard:
        from relay.demo import onboard_demo

        return onboard_demo()
    if args.demo_confirm:
        from relay.demo import confirm_demo

        return confirm_demo()
    if args.capabilities:
        from relay.demo import capabilities

        return capabilities()
    if args.demo_explorer:
        from relay.demo import explorer_demo

        return explorer_demo()
    if args.panel:
        from relay.demo import panel_run

        return panel_run()
    if args.models_status:
        from relay.models_manager import status_text

        print(status_text())
        return 0
    if args.setup_models:
        from relay.models_manager import ensure

        ok = ensure(download=True)
        print("Essential models are ready." if ok else "Some models are still missing.")
        return 0 if ok else 1
    if args.acceptance:
        import os

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import acceptance

        return acceptance.main()
    if args.install:
        from relay.config import Config
        from relay.install import install

        for pth in install(hotkey=Config.load().launch_hotkey):
            print("created", pth)
        print("Press Ctrl+Alt+R from anywhere to start Relay.")
        return 0
    if args.uninstall:
        from relay.install import uninstall

        for pth in uninstall():
            print("removed", pth)
        return 0
    if args.autostart:
        from relay.install import set_autostart

        pth = set_autostart(args.autostart == "on")
        print(
            (
                "Relay will start when you sign in: "
                if args.autostart == "on"
                else "Relay will no longer start automatically: "
            )
            + str(pth)
        )
        return 0
    if args.say:
        from relay.app import speak_once

        speak_once(args.say)
        return 0
    if args.llm_check:
        from relay.demo import llm_check

        return llm_check()
    if args.llm_tune:
        from relay.demo import llm_tune

        return llm_tune()
    if args.check:
        from relay.diagnostics import setup_logging
        from relay.health import main as check_main

        setup_logging("WARNING")
        return check_main(speak=not args.quiet)
    if args.demo_daily:
        from relay.demo import daily_demo

        return daily_demo()
    if args.toggle:
        return _start(panel=args.with_panel, toggle=True)
    if args.start:
        return _start(panel=args.with_panel)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
