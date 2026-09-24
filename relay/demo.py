"""P5 real demonstration: perceive -> act -> verify -> recover, end to end.

notepad_demo drives real Notepad through the central executor and verifies the
result by re-observing the world and by checking the file on disk — never by
assuming a keystroke worked. injected_failure_demo proves RELAY reports a failure
honestly instead of fabricating success. Both clean up after themselves.

These touch the real desktop, so they are run via the CLI, not the unit tests.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from relay.core import new_task_id
from relay.diagnostics import get_logger, setup_logging
from relay.executor import Executor
from relay.memory.db import connect
from relay.memory.journal import ActionJournal, ExecState
from relay.perception import UIAWorker
from relay.recovery import detect as detect_issue
from relay.safety import PermissionEngine
from relay.verifier import Verifier

log = get_logger("demo")
_DEMO_TEXT = "RELAY demo file. Created and verified by voice-driven automation."


def _line(step: str, outcome, extra: str = "") -> None:
    mark = {"verified": "OK ", "executed": "-> ", "uncertain": "??",
            "failed": "XX", "cancelled": "--"}.get(outcome.state.value, "  ")
    print(f"  [{mark}] {step}: {outcome.state.value}. {outcome.detail} {extra}".rstrip())


def notepad_demo() -> int:
    setup_logging("WARNING")
    engine = PermissionEngine()
    worker = UIAWorker()
    worker.start()
    conn = connect(":memory:")
    journal = ActionJournal(conn)
    tid = new_task_id()
    # Demo auto-confirms; the real flow requires a spoken confirmation phrase (P8).
    ex = Executor(engine, worker, journal, tid, confirm=lambda d: True)
    vf = Verifier(worker, journal)

    out = Path(tempfile.gettempdir()) / f"relay_demo_{int(time.time())}.txt"
    out.unlink(missing_ok=True)
    print(f"RELAY P5 demo — target file: {out}")
    passed = False
    try:
        # 1. launch + verify the app is really running
        o = ex.launch_app("notepad.exe")
        time.sleep(2.2)
        o = vf.verify(o, vf.app_running("Notepad.exe"), "Notepad process present")
        _line("launch Notepad", o)

        # 2. type into the focused editor + verify the text is actually there
        o = ex.type_text(_DEMO_TEXT)
        time.sleep(0.8)
        seen = vf.focus_value_contains("voice-driven")
        o = vf.verify(o, seen, "typed text observed in the document" if seen
                      else "could not confirm text in document")
        _line("type document", o)

        # 3. save: Ctrl+S should raise the Save dialog (recovery notes the dialog)
        prev = worker.observe(2.0)
        o = ex.hotkey("ctrl", "s")
        time.sleep(1.3)
        cur = worker.observe(2.0)
        issue = detect_issue(prev, cur, o.ok)
        dialog_up = bool(cur and cur.dialogs)
        o = vf.verify(o, dialog_up, "save dialog appeared" if dialog_up
                      else "no save dialog observed")
        saw = issue.kind if issue else "expected dialog"
        _line("open save dialog", o, f"(recovery saw: {saw})")

        # 4. type the full path into the dialog + Enter
        ex.type_text(str(out))
        time.sleep(0.5)
        o = ex.press("enter")
        time.sleep(1.4)

        # 5. verify the file actually exists on disk (the real postcondition)
        exists = vf.file_exists(str(out))
        o = vf.verify(o, exists, f"file exists at {out}" if exists else "file NOT found on disk")
        _line("verify saved file", o)
        passed = exists
    finally:
        # SAFETY: never force-kill apps — a Notepad may hold the user's unsaved work.
        # Leave the window open; the user closes it. Only our own temp file is removed.
        content_ok = False
        try:
            if out.exists():
                content_ok = "voice-driven" in out.read_text(encoding="utf-8", errors="ignore")
                out.unlink(missing_ok=True)
        except Exception:
            pass
        worker.stop()
        print("(Left Notepad open — RELAY never force-closes apps that may hold unsaved work.)")

    print(f"\nP5 demo {'PASSED' if passed and content_ok else 'FAILED'} "
          f"(file created + verified on disk, content match={content_ok}). "
          f"No step claimed success without observation.")
    print(f"journal rows: {len(journal.for_task(tid))}, "
          f"uncertain actions: {journal.uncertain_actions(tid)}")
    return 0 if (passed and content_ok) else 1


def injected_failure_demo() -> int:
    """Try to open an app that does not exist; RELAY must report FAILED, not success."""
    setup_logging("WARNING")
    engine = PermissionEngine()
    worker = UIAWorker()
    worker.start()
    conn = connect(":memory:")
    journal = ActionJournal(conn)
    tid = new_task_id()
    ex = Executor(engine, worker, journal, tid, confirm=lambda d: True)
    vf = Verifier(worker, journal)
    try:
        o = ex.launch_app("this_application_does_not_exist_zzq.exe")
        running = vf.app_running("this_application_does_not_exist_zzq.exe")
        o = vf.verify(o, running, "process present" if running else "process not found")
        _line("launch nonexistent app", o)
        honest = o.state in (ExecState.FAILED, ExecState.UNCERTAIN)
        print(f"\nInjected-failure demo {'PASSED' if honest else 'FAILED'}: "
              f"RELAY reported '{o.state.value}' rather than a false success.")
        return 0 if honest else 1
    finally:
        worker.stop()


def _speak_print(text: str) -> None:
    if text:
        print(f"  RELAY: {text}")


def transparent_demo() -> int:
    """Run a short real sequence through the Session, printing every narration line
    so the transparency contract is visible: each action is announced before it runs
    and every change is reported after."""
    from relay.session import Session
    setup_logging("WARNING")
    lines: list[str] = []

    def speak(t: str) -> None:
        if t:
            print(f"  RELAY: {t}")
            lines.append(t)

    s = Session(speak=speak)
    try:
        for cmd in ["what's on my screen", "open notepad",
                    "type Hello, this is Relay narrating every step",
                    "what changed", "what are my options"]:
            print(f"\nUSER: {cmd}")
            s.handle(cmd)
            time.sleep(0.6)
    finally:
        s.close()  # SAFETY: never force-kill apps — the user closes their own windows
    print(f"\nTransparent run complete: {len(lines)} narration lines "
          "(every action announced before acting; every change reported after).")
    print("(RELAY left every app open — it never force-closes windows that may hold "
          "unsaved work.)")
    return 0


def do_command(command: str) -> int:
    """Run one spoken command transparently against the real desktop."""
    from relay.session import Session
    setup_logging("WARNING")
    s = Session(speak=_speak_print)
    try:
        print(f"USER: {command}")
        s.handle(command)
    finally:
        s.close()  # SAFETY: never force-kill apps
    return 0
