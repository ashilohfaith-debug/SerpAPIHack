"""P8: narration modes/priorities, spelling, accessible spoken-confirmation flow,
screen-reader coexistence detection, and spoken onboarding. Headless."""

from relay.accessibility import confirmation_phrase, is_cancel, onboarding_script
from relay.accessibility.coexist import screen_reader_running
from relay.intent import Kind, parse
from relay.memory.journal import ExecState
from relay.memory.task_context import TaskContext
from relay.narration import policy as pol
from relay.perception.semantic import ScreenSnapshot, UIElement
from relay.planner import TransparentRunner, plan
from relay.safety import PermissionEngine


def _el(name, role="Button", value=""):
    return UIElement(uid=1, name=name, role=role, bbox=(0, 0, 10, 10), value=value)


# ---- narration policy ----
def test_mode_gating():
    assert pol.should_speak(pol.Priority.BACKGROUND, pol.QUICK) is False
    assert pol.should_speak(pol.Priority.TASK, pol.QUICK) is True
    assert pol.should_speak(pol.Priority.TASK, pol.QUIET) is False      # quiet drops task chatter
    assert pol.should_speak(pol.Priority.CRITICAL, pol.QUIET) is True   # keeps critical
    assert pol.should_speak(pol.Priority.BACKGROUND, pol.DETAILED) is True


def test_describe_verbosity_and_spell():
    snap = ScreenSnapshot(1, foreground_app="notepad.exe", foreground_title="Untitled",
                          elements=[_el("Save"), _el("Cancel")])
    assert "controls include" not in pol.describe(snap, pol.QUICK).lower()
    assert "controls include" in pol.describe(snap, pol.DETAILED).lower()
    assert pol.spell("Hi!") == "H, I, !"
    assert "space" in pol.spell("a b")


# ---- confirmation helpers ----
def test_confirmation_phrase_and_cancel():
    assert confirmation_phrase("Delete", "elevated") == "confirm delete"
    assert confirmation_phrase("Buy now", "elevated") == "confirm buy"
    assert is_cancel("no thanks") and is_cancel("cancel")
    assert not is_cancel("confirm delete")


# ---- accessibility misc ----
def test_screen_reader_detection_structure():
    running, name = screen_reader_running()  # none installed on the dev box
    assert isinstance(running, bool) and isinstance(name, str)


def test_onboarding_script_is_spoken_and_voice_only():
    lines = onboarding_script(wake_word="relay", first_run=True)
    assert any("Relay" in ln for ln in lines)
    assert any("stop" in ln.lower() for ln in lines)
    assert all(isinstance(ln, str) and ln for ln in lines)


# ---- grammar for accessibility intents ----
def test_access_intents_parse():
    assert parse("read the dialog").kind == Kind.READ_DIALOG
    assert parse("next").kind == Kind.NEXT_ELEMENT
    assert parse("previous").kind == Kind.PREV_ELEMENT
    assert parse("spell that").kind == Kind.SPELL
    assert parse("quiet mode").kind == Kind.SET_MODE
    assert parse("detailed mode").slots["mode"] == "detailed"


# ---- confirmation flow at the runner level ----
class FakeOutcome:
    def __init__(self, state):
        self.state = state
        self.detail = ""
        self.ok = state in (ExecState.EXECUTED, ExecState.VERIFIED)


class FakeExec:
    def __init__(self):
        self.invoked = []
        self._granted = False

    def grant_next_confirmation(self):
        self._granted = True

    def invoke_element(self, el):
        self.invoked.append(el.name)
        return FakeOutcome(ExecState.EXECUTED)


class FakeVerifier:
    def verify(self, outcome, ok, detail=""):
        return FakeOutcome(ExecState.VERIFIED if ok else ExecState.UNCERTAIN)


class FakeWorker:
    def __init__(self, snap):
        self.snap = snap

    def observe(self, timeout=2):
        return self.snap


def test_dangerous_click_requires_spoken_confirmation_before_acting():
    snap = ScreenSnapshot(1, foreground_app="app", foreground_title="App",
                          elements=[_el("Delete")])
    ctx = TaskContext("t")
    ctx.last_narrated = snap
    fx = FakeExec()
    captured = {}

    def on_confirm(dec, target, retry):
        captured.update(dec=dec, target=target, retry=retry)

    runner = TransparentRunner(fx, FakeWorker(snap), FakeVerifier(), ctx,
                               speak=lambda t: None, engine=PermissionEngine(),
                               on_confirm_needed=on_confirm)
    steps, _ = plan(parse("click delete"))
    results = runner.run(steps)
    # It asked for confirmation and did NOT act.
    assert results[-1].state == "awaiting_confirmation"
    assert fx.invoked == []
    assert captured["target"] == "Delete"
    # Only after the user confirms (retry) does it act.
    captured["retry"]()
    assert fx.invoked == ["Delete"]


# ---- Session-level confirmation + mode ----
def test_session_confirmation_and_mode(tmp_path):
    from relay.safety import Action
    from relay.session import Session
    spoken = []
    s = Session(speak=spoken.append, db_path=":memory:")
    try:
        # mode change
        s.handle("quiet mode")
        assert s.narration_mode == "quiet" and s.runner.mode == "quiet"

        # drive the confirmation flow directly with a real dangerous decision
        dec = s.engine.classify(Action(kind="invoke", target_label="Delete", target_app="Files"))
        ran = {"n": 0}
        s._on_confirm_needed(dec, "Delete", retry=lambda: ran.__setitem__("n", ran["n"] + 1))
        assert s._pending is not None
        spoken.clear()
        s.handle("nope")                 # cancel path
        assert s._pending is None and ran["n"] == 0
        assert any("cancel" in t.lower() for t in spoken)

        s._on_confirm_needed(dec, "Delete", retry=lambda: ran.__setitem__("n", ran["n"] + 1))
        s.handle("confirm delete")       # confirm path
        assert ran["n"] == 1 and s._pending is None
    finally:
        s.close()
