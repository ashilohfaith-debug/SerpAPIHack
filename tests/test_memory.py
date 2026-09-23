"""P2 memory: durable action journal + checkpoints + uncertain-action tracking."""

from relay.memory.db import connect, has_fts5
from relay.memory.journal import ActionJournal, ActionRecord, ExecState


def _journal():
    conn = connect(":memory:")
    return conn, ActionJournal(conn)


def test_journal_append_is_ordered_and_readable():
    _, j = _journal()
    for i in range(3):
        j.append(ActionRecord(task_id="t", action_id=f"a{i}", execution_state=ExecState.PROPOSED))
    recs = j.for_task("t")
    assert [r.action_id for r in recs] == ["a0", "a1", "a2"]


def test_journal_is_append_only_history():
    # the same action_id can have multiple rows (proposed -> executed -> verified)
    _, j = _journal()
    for st in (ExecState.PROPOSED, ExecState.EXECUTED, ExecState.VERIFIED):
        j.append(ActionRecord(task_id="t", action_id="a", execution_state=st))
    assert [r.execution_state for r in j.for_task("t")] == [
        ExecState.PROPOSED, ExecState.EXECUTED, ExecState.VERIFIED
    ]


def test_uncertain_actions_flagged_for_no_blind_replay():
    _, j = _journal()
    j.append(ActionRecord(task_id="t", action_id="send1", execution_state=ExecState.EXECUTED))
    j.append(ActionRecord(task_id="t", action_id="send1", execution_state=ExecState.UNCERTAIN))
    j.append(ActionRecord(task_id="t", action_id="save1", execution_state=ExecState.VERIFIED))
    assert j.uncertain_actions("t") == ["send1"]  # save1 verified -> not listed


def test_checkpoint_roundtrip():
    _, j = _journal()
    assert j.latest_checkpoint("t") is None
    j.save_checkpoint("t", goal="write doc", state="acting", data={"step": 2})
    j.save_checkpoint("t", goal="write doc", state="verifying", data={"step": 3})
    cp = j.latest_checkpoint("t")
    assert cp["state"] == "verifying" and cp["data"]["step"] == 3


def test_fts5_available():
    conn = connect(":memory:")
    # FTS5 is needed for L3/L4/L5 text search in P7; assert the runtime has it.
    assert has_fts5(conn) is True
