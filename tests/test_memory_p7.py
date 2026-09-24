"""P7: five-layer memory store, FTS, provenance, retention, deletion, restart
reconciliation, memory grammar, and Session memory ops. Memory-critical -> tested."""

from relay.intent import Kind, parse
from relay.memory import ActionJournal, ExecState, MemoryStore, connect, reconcile
from relay.memory.journal import ActionRecord
from relay.memory.reconcile import latest_task_id


def _store(path=":memory:"):
    return MemoryStore(connect(path))


# ---- L3 preferences ----
def test_pref_set_get_scope_fallback_and_delete():
    s = _store()
    s.set_pref("narration_mode", "detailed", scope="notepad.exe")
    s.set_pref("speech_rate", "1.2")  # global
    assert s.get_pref("narration_mode", scope="notepad.exe") == "detailed"
    assert s.get_pref("speech_rate", scope="notepad.exe") == "1.2"   # falls back to global
    assert s.get_pref("missing", default="x") == "x"
    assert s.delete_pref("narration_mode", scope="notepad.exe")
    assert s.get_pref("narration_mode", scope="notepad.exe") is None


def test_pref_provenance_and_export():
    s = _store()
    s.set_pref("voice", "lessac")
    assert "explicit_instruction" in s.why("voice")
    assert s.export_prefs()["preferences"][0]["key"] == "voice"


def test_sensitive_values_are_never_stored():
    s = _store()
    assert s.set_pref("mypassword", "hunter2") is False
    assert s.set_pref("bank", "my otp is 123456") is False
    assert s.set_pref("note:code", "483920") is False   # bare OTP-looking code
    assert s.all_prefs() == []


# ---- L4 learned labels + FTS sync ----
def test_learned_label_upsert_and_fts_sync():
    s = _store()
    s.learn_label("calc.exe", "the multiply sign", "Multiply by", "Button")
    s.learn_label("calc.exe", "the multiply sign", "Multiply by", "Button")  # again -> hits++
    rec = s.recall_label("calc.exe", "The Multiply Sign")
    assert rec["control_name"] == "Multiply by" and rec["hits"] == 2
    n = s.conn.execute("SELECT COUNT(*) c FROM labels_fts WHERE description='the multiply sign'"
                       ).fetchone()["c"]
    assert n == 1  # FTS mirror kept in sync, not duplicated


# ---- L4 workflows ----
def test_workflow_save_recall_validate():
    s = _store()
    wid = s.save_workflow("notepad.exe", "save as", [{"kind": "hotkey", "keys": "ctrl+s"}])
    wfs = s.recall_workflows("notepad.exe")
    assert wfs and wfs[0]["validation"] == "unvalidated"
    s.mark_workflow_validated(wid, True)
    assert s.recall_workflows("notepad.exe")[0]["validation"] == "validated"


# ---- L5 episodic (opt-in) + FTS + deletion purge ----
def test_episodic_requires_optin_then_searchable_and_deletable():
    s = _store()
    assert s.add_episodic("Saved report.docx to Documents") is None   # off by default
    s.set_permission("episodic", True)
    eid = s.add_episodic("Saved report.docx to Documents", app_key="notepad.exe")
    assert eid is not None
    hits = s.search_episodic("report")
    assert hits and hits[0]["id"] == eid
    assert s.delete_episodic(eid)
    # deletion purges the FTS index too
    assert s.search_episodic("report") == []
    assert s.conn.execute("SELECT COUNT(*) c FROM episodic_fts").fetchone()["c"] == 0


def test_episodic_never_stores_sensitive():
    s = _store()
    s.set_permission("episodic", True)
    assert s.add_episodic("user password is hunter2") is None


def test_clear_history_and_sweep_expired():
    s = _store()
    s.set_permission("episodic", True)
    eid = s.add_episodic("did a thing")
    s.conn.execute("UPDATE episodic_memories SET expires_at=1 WHERE id=?", (eid,))
    assert s.sweep_expired(now=1000) == 1
    assert s.conn.execute("SELECT COUNT(*) c FROM episodic_fts").fetchone()["c"] == 0
    s.set_permission("episodic", True)
    s.add_episodic("another")
    s.clear_task_history()
    assert s.list_episodic() == []


# ---- restart reconciliation ----
def test_reconcile_reports_uncertain_and_never_implies_repeat():
    conn = connect(":memory:")
    j = ActionJournal(conn)
    tid = "task_x"
    j.save_checkpoint(tid, goal="write my assignment", state="acting", data={})
    j.append(ActionRecord(tid, "a1", ExecState.VERIFIED, proposed_action="open editor"))
    j.append(ActionRecord(tid, "a2", ExecState.UNCERTAIN, proposed_action="save the file"))
    assert latest_task_id(conn) == tid
    rep = reconcile(j, tid)
    assert rep.goal == "write my assignment"
    assert "open editor" in rep.completed and "save the file" in rep.uncertain
    assert "won't repeat" in rep.spoken.lower()


# ---- persistence across a real restart (two connections to one file) ----
def test_preference_persists_across_restart(tmp_path):
    db = str(tmp_path / "relay.db")
    s1 = MemoryStore(connect(db))
    s1.set_pref("narration_mode", "detailed", scope="notepad.exe")
    s1.conn.close()
    s2 = MemoryStore(connect(db))   # fresh connection = a restart
    assert s2.get_pref("narration_mode", scope="notepad.exe") == "detailed"


# ---- memory grammar ----
def test_memory_intents_parse():
    assert parse("remember I prefer detailed narration in notepad").kind == Kind.REMEMBER
    assert parse("remember I prefer detailed narration in notepad").slots["mode"] == "detailed"
    assert parse("what do you remember").kind == Kind.WHAT_REMEMBER
    assert parse("forget this").kind == Kind.FORGET
    assert parse("clear my task history").kind == Kind.CLEAR_HISTORY
    assert parse("export my preferences").kind == Kind.EXPORT_PREFS
    assert parse("what were we doing").kind == Kind.WHAT_DOING


# ---- Session memory ops (headless; no UIA calls for these intents) ----
def test_session_remembers_and_recalls():
    from relay.session import Session
    spoken = []
    s = Session(speak=spoken.append, db_path=":memory:")
    try:
        s.handle("remember I prefer detailed narration in notepad")
        assert s.store.get_pref("narration_mode", scope="notepad.exe") == "detailed"
        spoken.clear()
        s.handle("what do you remember")
        assert any("preference" in t for t in spoken)
        spoken.clear()
        s.handle("what were we doing")
        assert any("don't have a record" in t.lower() for t in spoken)
    finally:
        s.close()
