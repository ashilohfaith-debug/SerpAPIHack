"""P6: intent grammar, change-delta, L2 references, planner, and the transparent
runner (announce-before -> act -> narrate result + every change) — all headless."""

from relay.intent import Kind, parse
from relay.memory.journal import ExecState
from relay.memory.task_context import TaskContext, resolve_reference
from relay.narration import diff
from relay.perception.semantic import Dialog, ScreenSnapshot, UIElement
from relay.planner import plan
from relay.planner.runner import TransparentRunner


def _el(name, role="Button", value="", bbox=(0, 0, 10, 10)):
    return UIElement(uid=1, name=name, role=role, bbox=bbox, value=value)


# ---- grammar ----
def test_intent_parsing():
    assert parse("what's on my screen").kind == Kind.DESCRIBE_SCREEN
    assert parse("where am I").kind == Kind.WHERE_AM_I
    assert parse("what changed").kind == Kind.WHAT_CHANGED
    assert parse("open notepad").kind == Kind.OPEN_APP
    assert parse("open notepad").slots["app"] == "notepad"
    t = parse("type Hello there world")
    assert t.kind == Kind.TYPE and t.slots["text"] == "Hello there world"
    a = parse("click the second option")
    assert a.kind == Kind.ACTIVATE and a.slots["ordinal"] == 2
    assert parse("save").kind == Kind.SAVE
    assert parse("stop").kind == Kind.CONTROL
    assert parse("press enter").slots["key"] == "enter"
    assert parse("qwerty zxcv").kind == Kind.UNKNOWN


# ---- change delta ----
def test_delta_reports_changes():
    a = ScreenSnapshot(1, foreground_app="notepad.exe", foreground_title="Untitled",
                       elements=[_el("Save")])
    b = ScreenSnapshot(2, foreground_app="notepad.exe", foreground_title="Untitled",
                       elements=[_el("Save")], dialogs=[Dialog("Save As", ("Save", "Cancel"))])
    changes = diff(a, b)
    assert any("dialog opened" in c.lower() for c in changes)
    assert diff(None, a) == []                      # first observation
    assert diff(a, a) == []                          # no change


def test_delta_focus_and_app_change():
    a = ScreenSnapshot(1, foreground_title="A", focus=_el("Field1", "Edit"))
    b = ScreenSnapshot(2, foreground_title="B", focus=_el("Field2", "Edit"))
    changes = diff(a, b)
    assert any("now in b" in c.lower() for c in changes)
    assert any("focus is now on" in c.lower() for c in changes)


# ---- L2 reference resolution ----
def test_resolve_ordinal_and_demonstrative_and_stale():
    ctx = TaskContext("t")
    snap = ScreenSnapshot(5, elements=[_el("Alpha"), _el("Beta"), _el("Gamma")])
    el, err = resolve_reference(ctx, snap, ordinal=2)
    assert err is None and el.name == "Beta"
    el2, err2 = resolve_reference(ctx, snap, target="that")  # last remembered = Beta
    assert err2 is None and el2.name == "Beta"
    _, e3 = resolve_reference(ctx, snap, target="Nonexistent")
    assert e3 == "not_found"
    # after screen changes and Beta is gone, "that" is stale
    snap2 = ScreenSnapshot(6, elements=[_el("Alpha"), _el("Gamma")])
    _, e4 = resolve_reference(ctx, snap2, target="it")
    assert e4 == "reference_stale"


# ---- planner ----
def test_plan_maps_intents_and_clarifies_unknown():
    steps, clar = plan(parse("open notepad"))
    assert clar is None and steps[0].kind == "open"
    steps2, clar2 = plan(parse("what's on my screen"))
    assert steps2[0].kind == "answer"
    steps3, clar3 = plan(parse("flibber the wibble"))
    assert steps3 == [] and clar3 is not None


# ---- transparent runner (fakes) ----
class FakeOutcome:
    def __init__(self, state, detail=""):
        self.state, self.detail = state, detail
        self.ok = state in (ExecState.EXECUTED, ExecState.VERIFIED)


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def _mk(self, name):
        self.calls.append(name)
        return FakeOutcome(ExecState.EXECUTED, name)

    def launch_app(self, exe):
        return self._mk(f"launch {exe}")

    def type_text(self, t):
        return self._mk(f"type {t}")

    def hotkey(self, *k):
        return self._mk("hotkey")

    def press(self, k):
        return self._mk(f"press {k}")

    def invoke_element(self, el):
        return self._mk(f"invoke {el.name}")


class FakeVerifier:
    def verify(self, outcome, ok, detail=""):
        return FakeOutcome(ExecState.VERIFIED if ok else ExecState.UNCERTAIN, detail)

    def app_running(self, x):
        return True

    def window_present(self, x, **k):
        return True

    def focus_value_contains(self, x, **k):
        return True

    def dialog_present(self, **k):
        return True


class FakeWorker:
    def __init__(self, snaps):
        self.snaps = list(snaps)

    def observe(self, timeout=2):
        return self.snaps.pop(0) if self.snaps else self.snaps and self.snaps[-1] or None

    def start(self):
        pass

    def stop(self):
        pass


def test_runner_announces_before_and_reports_change():
    ctx = TaskContext("t")
    spoken = []
    before = ScreenSnapshot(1, foreground_app="notepad.exe", foreground_title="Untitled",
                            elements=[_el("Save")])
    after = ScreenSnapshot(2, foreground_app="notepad.exe", foreground_title="Untitled",
                           elements=[_el("Save")], dialogs=[Dialog("Save As", ("Save",))])
    ctx.last_narrated = before
    worker = FakeWorker([after, after, after])
    runner = TransparentRunner(FakeExecutor(), worker, FakeVerifier(), ctx,
                               speak=spoken.append)
    steps, _ = plan(parse("save"))
    runner.run(steps)
    joined = " | ".join(spoken)
    assert "going to" in joined.lower()                  # announced BEFORE acting
    assert "done" in joined.lower()                       # result reported
    assert any("dialog opened" in s.lower() for s in spoken)  # change reported


def test_runner_answer_describe_uses_summary():
    ctx = TaskContext("t")
    spoken = []
    snap = ScreenSnapshot(1, foreground_app="brave.exe", foreground_title="Docs",
                          elements=[_el("Home"), _el("Back")])
    runner = TransparentRunner(FakeExecutor(), FakeWorker([snap]), FakeVerifier(),
                               ctx, speak=spoken.append)
    steps, _ = plan(parse("what's on my screen"))
    runner.run(steps)
    assert any("brave.exe" in s for s in spoken)


def test_runner_stops_on_cancel():
    import threading
    ctx = TaskContext("t")
    spoken = []
    cancel = threading.Event()
    cancel.set()
    snap = ScreenSnapshot(1, foreground_title="X")
    runner = TransparentRunner(FakeExecutor(), FakeWorker([snap, snap]), FakeVerifier(),
                               ctx, speak=spoken.append)
    steps, _ = plan(parse("open notepad"))
    results = runner.run(steps, cancel=cancel)
    assert results and results[0].state == "cancelled"
    assert any("stopping" in s.lower() for s in spoken)
