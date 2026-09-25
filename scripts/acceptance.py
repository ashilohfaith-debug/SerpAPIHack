"""Offline acceptance runner — the release checks that need no GUI, no network, and
no risk to the desktop. Real-app end-to-end, NVDA coexistence and blind-user testing
are separate and require hardware/people (see docs/ACCEPTANCE.md).

    uv run python scripts/acceptance.py
"""

from __future__ import annotations

import os
import tempfile
import urllib.error
import urllib.request

import numpy as np


def check_single_instance():
    from relay.core.single_instance import SingleInstance
    a, b = SingleInstance("acc"), SingleInstance("acc")
    try:
        ok1 = a.acquire()
        ok2 = b.acquire()   # second must fail while first holds the lock
        return ok1 and not ok2, "second instance correctly refused"
    finally:
        a.release()
        b.release()


def check_memory_persist_and_reconcile():
    from relay.memory import ActionJournal, ExecState, MemoryStore, connect, reconcile
    from relay.memory.journal import ActionRecord
    db = os.path.join(tempfile.gettempdir(), "acc_mem.db")
    for ext in ("", "-wal", "-shm"):
        try:
            os.remove(db + ext)
        except OSError:
            pass
    s1 = MemoryStore(connect(db))
    s1.set_pref("narration_mode", "detailed", scope="notepad.exe")
    j = ActionJournal(s1.conn)
    j.save_checkpoint("t", goal="write my assignment", state="acting", data={})
    j.append(ActionRecord("t", "a1", ExecState.VERIFIED, proposed_action="open editor"))
    j.append(ActionRecord("t", "a2", ExecState.UNCERTAIN, proposed_action="save"))
    s1.conn.close()
    s2 = MemoryStore(connect(db))          # restart
    persisted = s2.get_pref("narration_mode", scope="notepad.exe") == "detailed"
    rep = reconcile(ActionJournal(s2.conn), "t")
    s2.conn.close()
    ok = persisted and "save" in rep.uncertain and "won't repeat" in rep.spoken.lower()
    return ok, "pref persisted across restart; uncertain action reported, not auto-repeated"


def check_confirmation_safety():
    from relay.safety import Action
    from relay.session import Session
    s = Session(speak=lambda t: None, db_path=":memory:")
    try:
        dec = s.engine.classify(Action(kind="invoke", target_label="Delete", target_app="X"))
        ran = {"n": 0}
        s._on_confirm_needed(dec, "Delete", retry=lambda: ran.__setitem__("n", ran["n"] + 1))
        s.handle("yeah sure")
        before = ran["n"]
        s._on_confirm_needed(dec, "Delete", retry=lambda: ran.__setitem__("n", ran["n"] + 1))
        s.handle("confirm delete")
        return before == 0 and ran["n"] == 1, "casual reply never acted; phrase did"
    finally:
        s.close()


def check_voice_roundtrip_offline():
    from relay.audio import WhisperSTT, make_tts
    phrase = "please open the file and read the text"
    tts = make_tts(prefer_piper=True)
    audio, sr = tts.synth_to_array(phrase)
    if sr != 16000:
        n = int(len(audio) * 16000 / sr)
        audio = np.interp(np.linspace(0, len(audio), n, endpoint=False),
                          np.arange(len(audio)), audio).astype(np.float32)
    text = WhisperSTT().transcribe(audio).lower()
    want = set(phrase.split())
    heard = set(text.replace(".", "").split())
    overlap = len(want & heard) / len(want)
    return overlap >= 0.7, f"Piper->faster-whisper word overlap {overlap:.2f}"


def check_ipc_auth():
    from relay.core import EventBus
    from relay.ipc import IpcServer

    class FS:
        def handle(self, t): return []
        def onboard(self): pass
    srv = IpcServer(FS(), EventBus(), port=0)
    url = srv.start()
    base, token = url.split("/?")[0], url.split("token=")[1]
    try:
        try:
            urllib.request.urlopen(base + "/", timeout=5)
            return False, "no-token request was NOT refused"
        except urllib.error.HTTPError as e:
            if e.code != 403:
                return False, f"expected 403, got {e.code}"
        r = urllib.request.urlopen(base + "/?token=" + token, timeout=5)
        return r.status == 200, "loopback token auth enforced (403 without, 200 with)"
    finally:
        srv.stop()


def check_capabilities():
    from relay.workflows import capability_for, matrix_text
    ok = capability_for("notepad").level == "full" and "Calculator" in matrix_text()
    return ok, "honest capability matrix present"


def check_everyday_language():
    from relay.intent import Kind, parse
    cases = {
        "Um, can you open WhatsApp for me, please?": Kind.OPEN_APP,
        "What's the time?": Kind.TIME, "How's my battery?": Kind.BATTERY,
        "search for bus stop near me": Kind.WEB_SEARCH, "read the page": Kind.READ_ALL,
        "remind me in 10 minutes to call mom": Kind.SET_REMINDER,
        "what is 15 percent of 2 lakh": Kind.CALCULATE, "stop": Kind.CONTROL,
        "send the message": Kind.SEND, "turn on connected mode": Kind.CONNECTED,
    }
    wrong = [u for u, k in cases.items() if parse(u).kind != k]
    return not wrong, (f"{len(cases)} natural phrasings routed correctly" if not wrong
                       else f"misrouted: {wrong}")


def check_send_needs_readback():
    from relay.executor.input_backend import RecordingBackend
    from relay.session import Session
    said = []
    s = Session(speak=said.append, db_path=":memory:")
    try:
        s.executor.input = RecordingBackend()
        s.skills._fg_app = lambda: "whatsapp.root.exe"
        s.skills._focus_value = lambda: "see you at five"
        s.handle("send it")
        s.handle("yeah")
        sent = ("press", "enter") in s.executor.input.calls
        read_back = any("see you at five" in t for t in said)
        return not sent and read_back, "draft read back; a casual 'yeah' did not send"
    finally:
        s.close()


CHECKS = [
    ("single instance guard", check_single_instance),
    ("five-layer memory: persist + reconcile (offline)", check_memory_persist_and_reconcile),
    ("high-risk spoken confirmation (safety)", check_confirmation_safety),
    ("offline voice round-trip (TTS->STT)", check_voice_roundtrip_offline),
    ("optional panel IPC auth", check_ipc_auth),
    ("application capability matrix", check_capabilities),
    ("everyday natural language (offline grammar)", check_everyday_language),
    ("messages read back before sending", check_send_needs_readback),
]


def main() -> int:
    print("RELAY offline acceptance suite\n" + "=" * 40)
    passed = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"error: {type(e).__name__}: {e}"
        passed += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    print("=" * 40)
    print(f"{passed}/{len(CHECKS)} offline acceptance checks passed.")
    print("Live checks: scripts/e2e_voice.py, scripts/live_app_check.py, "
          "scripts/live_window_check.py. Still required (need hardware/people/keys): "
          "live Sarvam calls (relay --sarvam-selftest), NVDA coexistence, clean-VM "
          "offline install, supervised blind-user testing, 4 GB-hardware latency.")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
