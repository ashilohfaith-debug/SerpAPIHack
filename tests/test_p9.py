"""P9: capability matrix, window enumeration/activation robustness, and unexpected-
dialog surfacing. Headless (real-app runs are via the safe CLI demos)."""

from relay.intent import Kind, parse
from relay.memory.journal import ExecState
from relay.memory.task_context import TaskContext
from relay.perception.semantic import Dialog, ScreenSnapshot, UIElement
from relay.planner import TransparentRunner, plan
from relay.workflows import capability_for, matrix_text, spoken_summary


def _el(name, role="Button"):
    return UIElement(uid=1, name=name, role=role, bbox=(0, 0, 10, 10))


# ---- capability matrix ----
def test_capability_lookup_and_text():
    assert capability_for("notepad.exe").level == "full"
    assert capability_for("calc").level == "keyboard"  # UWP -> keyboard
    assert capability_for("brave").level == "partial"  # chromium partial
    assert capability_for("some_unknown_app") is None
    assert "Notepad" in matrix_text() and "keyboard" in matrix_text()
    assert "reliably operate" in spoken_summary()


def test_capabilities_intent_parses():
    assert parse("what apps do you support").kind == Kind.CAPABILITIES
    assert parse("what can you control").kind == Kind.CAPABILITIES
    assert parse("what can you do").kind == Kind.HELP  # still help, not caps


# ---- verifier finds an app that opened but isn't foreground ----
def test_window_present_checks_all_top_level_windows():
    from relay.verifier import Verifier

    class FakeWorker:
        def observe(self, timeout=2):
            # foreground is a DIFFERENT app (e.g. the user's browser)
            return ScreenSnapshot(1, foreground_app="brave.exe", foreground_title="Brave")

        def list_windows(self, timeout=3):
            return [{"title": "Calculator", "app": "ApplicationFrameHost.exe", "hwnd": 1}]

    vf = Verifier(FakeWorker())
    assert vf.window_present("calculator") is True  # found among top-level windows
    assert vf.window_present("nonesuch") is False


# ---- unexpected dialog is surfaced with guidance ----
class Res:
    def __init__(self, state, detail=""):
        self.state = state
        self.detail = detail
        self.ok = state in (ExecState.EXECUTED, ExecState.VERIFIED)


class FakeExec:
    def type_text(self, t):
        return Res(ExecState.EXECUTED)


class FakeVerifier:
    def verify(self, outcome, ok, detail=""):
        return Res(ExecState.VERIFIED if ok else ExecState.UNCERTAIN, detail)

    def focus_value_contains(self, *a, **k):
        return True


class FakeWorker2:
    def __init__(self, after):
        self.after = after

    def observe(self, timeout=2):
        return self.after


def test_runner_surfaces_unexpected_dialog():
    before = ScreenSnapshot(1, foreground_title="Editor", elements=[_el("Body", "Edit")])
    after = ScreenSnapshot(
        2,
        foreground_title="Editor",
        elements=[_el("Body", "Edit")],
        dialogs=[Dialog("Unsaved changes", ("Save", "Don't Save", "Cancel"))],
    )
    ctx = TaskContext("t")
    ctx.last_narrated = before
    spoken = []
    runner = TransparentRunner(
        FakeExec(), FakeWorker2(after), FakeVerifier(), ctx, speak=spoken.append
    )
    steps, _ = plan(parse("type hello"))  # a non-save step that unexpectedly pops a dialog
    runner.run(steps)
    joined = " | ".join(spoken).lower()
    assert "dialog opened" in joined  # the change was reported
    assert "how would you like to proceed" in joined  # recovery guidance offered
