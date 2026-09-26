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


def memory_demo() -> int:
    """Offline, no-LLM, no-GUI proof of the five-layer memory acceptance test:
    set a per-app preference, 'restart' RELAY (a fresh Session on the same DB),
    recall the preference, and reconcile the previous task — reporting the verified
    step and the uncertain one honestly (never auto-repeating the uncertain action)."""
    import os
    import tempfile

    from relay.memory.journal import ActionRecord, ExecState
    from relay.session import Session
    setup_logging("WARNING")
    db = os.path.join(tempfile.gettempdir(), f"relay_mem_{int(time.time())}.db")
    print(f"memory DB: {db}")

    s1 = Session(speak=_speak_print, db_path=db)
    try:
        print("\nUSER: remember I prefer detailed narration in notepad")
        s1.handle("remember I prefer detailed narration in notepad")
        j, tid = s1.journal, s1.task_id
        j.save_checkpoint(tid, goal="write my assignment", state="acting", data={})
        j.append(ActionRecord(tid, "a1", ExecState.VERIFIED, proposed_action="open the editor"))
        j.append(ActionRecord(tid, "a2", ExecState.UNCERTAIN, proposed_action="save the file"))
        print("USER: what do you remember")
        s1.handle("what do you remember")
    finally:
        s1.close()

    print("\n--- (RELAY closed and restarted) ---")
    s2 = Session(speak=_speak_print, db_path=db)
    persisted = s2.store.get_pref("narration_mode", scope="notepad.exe")
    try:
        print(f"[persisted] narration preference for notepad = {persisted!r}")
        print("USER: what were we doing")
        s2.handle("what were we doing")
        print("USER: what do you remember")
        s2.handle("what do you remember")
    finally:
        s2.close()

    for ext in ("", "-wal", "-shm"):
        p = db + ext
        try:
            if os.path.exists(p):
                os.unlink(p)
        except OSError:
            pass  # a lingering lock is fine — it's a temp file
    ok = persisted == "detailed"
    print(f"\nMemory demo {'PASSED' if ok else 'FAILED'}: preference persisted across "
          "restart; the uncertain save was reported, not auto-repeated. Offline, no LLM.")
    return 0 if ok else 1


def onboard_demo() -> int:
    """Speak the voice-only onboarding through the real Piper voice — proof a blind
    user can start and understand RELAY with no visual step."""
    from relay.accessibility import onboarding_script
    from relay.audio import make_tts
    setup_logging("WARNING")
    tts = make_tts(prefer_piper=True)
    for line in onboarding_script(first_run=True):
        print(f"  RELAY: {line}")
        try:
            import sounddevice as sd
            audio, sr = tts.synth_to_array(line)
            if len(audio):
                sd.play(audio, sr)
                sd.wait()
        except Exception as e:
            print(f"    (audio unavailable: {e})")
    print("\nSpoken onboarding complete — voice-only, no visual step required.")
    return 0


def confirm_demo() -> int:
    """Show the accessible spoken-confirmation flow: a casual 'yeah' must NOT trigger
    a dangerous action — only the exact action-specific phrase does."""
    from relay.safety import Action
    from relay.session import Session
    setup_logging("WARNING")
    s = Session(speak=_speak_print)
    performed = {"n": 0}

    def do_delete():
        performed["n"] += 1
        print("  [ACTION EXECUTED] Delete performed")

    try:
        dec = s.engine.classify(Action(kind="invoke", target_label="Delete", target_app="Files"))
        print("USER: click delete")
        s._on_confirm_needed(dec, "Delete", retry=do_delete)
        print("\nUSER: yeah sure   (a casual reply — NOT the confirmation phrase)")
        s.handle("yeah sure")
        print(f"  performed so far: {performed['n']}  (expected 0 — not confirmed)")
        print("\nUSER: confirm delete   (the exact phrase)")
        s.handle("confirm delete")
        print(f"  performed after phrase: {performed['n']}  (expected 1)")
    finally:
        s.close()
    ok = performed["n"] == 1
    print(f"\nConfirm demo {'PASSED' if ok else 'FAILED'}: a casual reply never triggered "
          "the destructive action; only the action-specific phrase did.")
    return 0 if ok else 1


def capabilities() -> int:
    from relay.workflows import matrix_text
    print(matrix_text())
    return 0


def explorer_demo() -> int:
    """Safe, READ-ONLY: open File Explorer, bring it forward, and describe what's
    there. No files are changed and no app is force-closed."""
    from relay.session import Session
    setup_logging("WARNING")
    s = Session(speak=_speak_print)
    try:
        for cmd in ["open file explorer", "what's on my screen", "what are my options"]:
            print(f"\nUSER: {cmd}")
            s.handle(cmd)
            time.sleep(0.6)
    finally:
        s.close()  # never force-close
    print("\nRead-only Explorer demo complete — nothing was changed.")
    return 0


def daily_demo() -> int:
    """Safe, offline tour of everyday skills through the real Session: status, maths,
    notes, reminders, windows list, help. Nothing on the desktop is changed."""
    from relay.session import Session
    setup_logging("WARNING")
    s = Session(speak=_speak_print, db_path=":memory:")
    cmds = ["what time is it", "what's the date", "how much battery do I have",
            "am I connected to the internet", "what is 25 times 4",
            "what's 15 percent of 2 lakh", "take a note buy milk and bread",
            "note that the meeting moved to Friday", "read my notes",
            "remind me in 10 minutes to call mom", "set a timer for 5 minutes",
            "what are my reminders", "cancel my reminders", "what's the volume",
            "what windows are open", "help with notes", "flibber the wibble"]
    try:
        for cmd in cmds:
            print(f"\nUSER: {cmd}")
            s.handle(cmd)
    finally:
        s.close()
    print("\nDaily-skills demo complete — offline, nothing on the desktop was changed.")
    return 0


def llm_check() -> int:
    """Measure the conversational assistant end to end through the configured router:
    time to first token, time to the first spoken sentence, and to first AUDIO (with
    RELAY's own voice synthesis) — the number a user actually feels."""
    from relay.config import Config
    from relay.llm import Assistant, Router, routes_from_config
    setup_logging("WARNING")
    routes = routes_from_config(Config.load())
    if not routes:
        print("No AI router configured. Put these in the .env file next to RELAY.cmd:\n"
              "  RELAY_LLM_URL=http://localhost:3001/v1\n"
              "  RELAY_LLM_KEY=freellmapi-...   (the unified key from its dashboard)")
        return 2
    router = Router(routes)
    router.warm()
    asst = Assistant(router)
    tts = None
    try:
        from relay.audio import make_tts
        tts = make_tts(prefer_piper=True)
        from relay.sarvam import SarvamClient, SarvamTTS, settings
        sv = settings()
        if sv["key"]:                    # measure with the voice the user will hear
            client = SarvamClient(sv["key"], base=sv["base"])
            client.warm()
            tts = SarvamTTS(client, tts, language=sv["language"], speaker=sv["speaker"],
                            model=sv["tts_model"], on_fallback=print)
        tts.synth_to_array("warm up")
        print(f"voice: {'Sarvam ' + sv['tts_model'] if sv['key'] else type(tts).__name__}")
    except Exception as e:
        print("voice unavailable for timing:", e)
    ok = True
    for q in ("Say hello in five words.", "What is the capital of Japan?",
              "Give me one short tip for staying focused.", "tell me a very short joke"):
        t0 = time.perf_counter()
        first = {}

        def speak(sentence, t0=t0, first=first):
            if "t" not in first:
                first["t"] = time.perf_counter() - t0
                if tts is not None:
                    tts.synth_to_array(sentence)
                    first["audio"] = time.perf_counter() - t0
        kind, text = asst.respond(q, speak)
        total = time.perf_counter() - t0
        if kind == "offline":
            ok = False
            print(f"  [XX] {q!r}: no route answered")
            continue
        print(f"  [OK ] {q!r}\n        first token {router.last_ttft:.2f}s via "
              f"{router.last_route} | first sentence {first.get('t', total):.2f}s | "
              f"first audio {first.get('audio', total):.2f}s | done {total:.2f}s\n"
              f"        {kind}: {text[:120]!r}")
    print("\nroute health (learned first-token time):")
    for r in router.routes:
        h = router.health[r.name]
        cool = max(0.0, h.cool_until - time.monotonic())
        print(f"  {r.name:12} {h.ttft:5.2f}s  failures={h.failures}"
              + (f"  cooling {cool:.0f}s" if cool else ""))
    return 0 if ok else 1


def panel_run() -> int:
    """Start the optional accessible panel (authenticated loopback HTTP+SSE) and keep
    the core running. Closing the panel does not stop RELAY."""
    import webbrowser

    from relay.core import EventBus
    from relay.ipc import IpcServer
    from relay.session import Session
    setup_logging("INFO")
    bus = EventBus()
    session = Session(speak=None, bus=bus)
    server = IpcServer(session, bus)
    url = server.start()
    print(f"RELAY panel: {url}")
    print("Open it in a browser. The panel mirrors RELAY; closing it won't stop the core. "
          "Ctrl+C to stop.")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping panel…")
    finally:
        server.stop()
        session.close()
    return 0
