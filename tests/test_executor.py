"""P5: executor gating/revalidation/journaling, verification outcomes, and recovery
detection — all headless via a fake UIA worker and a recording input backend, so no
real keystrokes or clicks are fired during tests."""

from relay.core import EmergencyStop, new_task_id
from relay.executor import Executor, RecordingBackend
from relay.memory.db import connect
from relay.memory.journal import ActionJournal, ExecState
from relay.perception.semantic import Dialog, ScreenSnapshot, UIElement
from relay.recovery import detect
from relay.safety import PermissionEngine
from relay.verifier import Verifier


class FakeWorker:
    """run() returns scripted (value, ok) without executing the UIA lambda; observe()
    returns scripted snapshots."""

    def __init__(self, run_results=None, observe_snaps=None):
        self.run_results = list(run_results or [])
        self.observe_snaps = list(observe_snaps or [])

    def start(self):
        pass

    def run(self, fn, timeout=2):
        return self.run_results.pop(0) if self.run_results else (True, True)

    def observe(self, timeout=2):
        return self.observe_snaps.pop(0) if self.observe_snaps else None

    def stop(self):
        pass


def _setup(worker=None, confirm=None, emergency=None):
    engine = PermissionEngine()
    journal = ActionJournal(connect(":memory:"))
    tid = new_task_id()
    backend = RecordingBackend()
    ex = Executor(
        engine,
        worker or FakeWorker(),
        journal,
        tid,
        emergency=emergency,
        confirm=confirm,
        input_backend=backend,
    )
    return ex, journal, tid, backend


def _el(name, role="Button"):
    return UIElement(uid=1, name=name, role=role, bbox=(0, 0, 10, 10), window_title="App")


# ---- gating ----
def test_dangerous_action_blocked_without_confirmation():
    ex, journal, tid, _ = _setup(worker=FakeWorker(run_results=[(True, True), (True, True)]))
    o = ex.invoke_element(_el("Delete"))  # ELEVATED -> needs confirmation
    assert o.state is ExecState.CANCELLED and "not confirmed" in o.detail
    states = [r.execution_state for r in journal.for_task(tid)]
    assert ExecState.PROPOSED in states and ExecState.CANCELLED in states


def test_dangerous_action_runs_after_confirmation():
    ex, _, _, _ = _setup(
        worker=FakeWorker(run_results=[(True, True), (True, True)]), confirm=lambda d: True
    )
    o = ex.invoke_element(_el("Delete"))
    assert o.state is ExecState.EXECUTED


def test_emergency_stop_blocks_execution():
    es = EmergencyStop()
    es.engage("test")
    ex, _, _, backend = _setup(emergency=es)
    o = ex.type_text("hello")
    assert o.state is ExecState.CANCELLED and "emergency" in o.detail
    assert backend.calls == []  # nothing was injected


def test_revalidation_failure_aborts_without_acting():
    # exists() returns False -> target gone -> FAILED, invoke never attempted
    ex, _, _, _ = _setup(worker=FakeWorker(run_results=[(False, True)]), confirm=lambda d: True)
    o = ex.invoke_element(_el("OK"))
    assert o.state is ExecState.FAILED and "revalidation" in o.detail


def test_type_text_uses_backend_and_journals():
    ex, journal, tid, backend = _setup()
    o = ex.type_text("meeting notes")
    assert o.state is ExecState.EXECUTED
    assert backend.calls == [("type_text", "meeting notes")]
    assert any(r.execution_state is ExecState.EXECUTED for r in journal.for_task(tid))


# ---- verification ----
def test_verifier_window_and_focus_and_file(tmp_path):
    snap = ScreenSnapshot(
        1,
        foreground_title="Untitled - Notepad",
        focus=UIElement(1, "Editor", "Document", (0, 0, 5, 5), value="hello brave new world"),
    )
    w = FakeWorker(observe_snaps=[snap, snap])
    vf = Verifier(w)
    assert vf.window_present("Notepad")
    assert vf.focus_value_contains("brave new")
    f = tmp_path / "x.txt"
    f.write_text("hi")
    assert vf.file_exists(str(f))
    assert not vf.file_exists(str(tmp_path / "nope.txt"))


def test_verify_folds_outcome_and_journals():
    from relay.executor.executor import ActionOutcome

    journal = ActionJournal(connect(":memory:"))
    vf = Verifier(FakeWorker(), journal)
    ex_ok = ActionOutcome("task_x.a1", ExecState.EXECUTED, "did it")
    assert vf.verify(ex_ok, True, "confirmed").state is ExecState.VERIFIED
    assert vf.verify(ex_ok, False, "could not confirm").state is ExecState.UNCERTAIN
    failed = ActionOutcome("task_x.a2", ExecState.FAILED, "boom")
    assert vf.verify(failed, True).state is ExecState.FAILED  # failed stays failed


# ---- recovery ----
def test_recovery_detects_unexpected_dialog():
    prev = ScreenSnapshot(1, foreground_title="Editor")
    cur = ScreenSnapshot(
        2,
        foreground_title="Editor",
        dialogs=[Dialog("Save changes?", ("Save", "Don't Save", "Cancel"))],
    )
    issue = detect(prev, cur, action_ok=True)
    assert issue and issue.kind == "unexpected_dialog" and "Save" in issue.spoken


def test_recovery_detects_no_effect():
    a = ScreenSnapshot(1, foreground_title="Editor", elements=[_el("OK")])
    b = ScreenSnapshot(2, foreground_title="Editor", elements=[_el("OK")])
    issue = detect(a, b, action_ok=True)
    assert issue and issue.kind == "no_effect"


def test_recovery_no_observation_and_clean():
    assert detect(None, None, True).kind == "no_observation"
    a = ScreenSnapshot(1, foreground_title="A", elements=[_el("OK")])
    b = ScreenSnapshot(2, foreground_title="B", elements=[_el("Cancel")])
    assert detect(a, b, True) is None  # a real change, no problem
