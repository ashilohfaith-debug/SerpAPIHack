"""Comprehensive production verification tests for Points 23 through 78."""

from pathlib import Path
from unittest.mock import MagicMock

from relay.audio.wake import Command, match_command
from relay.editing.editor import TextEditor
from relay.goals.assignment import Assignment, AssignmentWorkflow, RubricCriterion
from relay.goals.goal import GoalManager
from relay.intent import Kind, parse
from relay.intent.normalize import normalize
from relay.memory.db import connect
from relay.memory.task_context import TaskContext, resolve_reference
from relay.perception.semantic import ScreenSnapshot, UIElement
from relay.session import Session
from relay.system.apps import AppCatalog, AppEntry
from relay.workspace.agent import WorkspaceAgent


def test_talk_key_interruption_does_not_cancel_next_compound_command():
    spoken = []
    entry = AppEntry("Notepad", "notepad.exe")
    s = Session(
        speak=spoken.append,
        apps=AppCatalog(entries=[entry]),
        db_path=":memory:",
    )
    s.apps.wait_ready = MagicMock(return_value=True)
    s.apps.find = MagicMock(return_value=entry)
    s.runner.run = MagicMock(return_value=[MagicMock(state="verified")])
    s._fresh_document = MagicMock(return_value=True)

    # Push-to-talk silences any current speech before capturing the new request.
    s.stop_speaking()
    s.cancel.set()  # also simulate a task that was cancelled before this request
    assert s._answer_cancel.is_set()
    assert s.cancel.is_set()

    s.handle("open notepad and write hi")

    assert s.runner.run.call_count == 2
    assert not any("Stopped before step 1" in line for line in spoken)
    assert not s.cancel.is_set()
    s.close()


def test_speech_self_correction_normalization():
    # Point 28: blind-user self-corrections
    assert normalize("open edge no wait open chrome") == "open chrome"
    assert normalize("search for pizza scratch that search for coffee") == "search for coffee"
    assert normalize("type hello world wait no type good morning") == "type good morning"
    # Recognition slips
    assert normalize("open no pad") == "open notepad"
    assert normalize("open you tube") == "open youtube"
    assert normalize("open fire fox") == "open firefox"
    assert normalize("open whats app") == "open whatsapp"


def test_conversational_control_commands():
    # Point 27: simpler, explain that, why, repeat, go back, start again
    assert match_command("go back") == Command.GO_BACK
    assert match_command("navigate back") == Command.GO_BACK
    assert match_command("start again") == Command.START_AGAIN
    assert match_command("start over") == Command.START_AGAIN
    assert match_command("make it simpler") == Command.SIMPLER
    assert match_command("explain that") == Command.EXPLAIN
    assert match_command("why did you do that") == Command.WHY


def test_typing_vs_composing_separation():
    # Point 49: separation between literal typing and content creation
    i_type = parse("type hello world")
    assert i_type.kind == Kind.TYPE
    assert i_type.slots["text"] == "hello world"

    i_compose_essay = parse("write an essay about the solar system")
    assert i_compose_essay.kind == Kind.COMPOSE

    i_compose_code = parse("write a function to reverse a string")
    assert i_compose_code.kind == Kind.COMPOSE

    i_draft = parse("draft a polite reply to the teacher")
    assert i_draft.kind == Kind.COMPOSE


def test_spoken_text_editing_and_selection_grammar():
    # Points 30, 31, 32, 34, 35
    i_sel_word = parse("select word")
    assert i_sel_word.kind == Kind.TEXT_SELECT
    assert i_sel_word.slots["unit"] == "word"

    i_sel_line = parse("select line")
    assert i_sel_line.kind == Kind.TEXT_SELECT
    assert i_sel_line.slots["unit"] == "line"

    i_sel_para = parse("select paragraph")
    assert i_sel_para.kind == Kind.TEXT_SELECT
    assert i_sel_para.slots["unit"] == "paragraph"

    i_sel_all = parse("select all")
    assert i_sel_all.kind == Kind.SHORTCUT
    assert list(i_sel_all.slots["keys"]) == ["ctrl", "a"]

    i_nav_left = parse("move left 3 words")
    assert i_nav_left.kind == Kind.TEXT_NAV
    assert i_nav_left.slots["unit"] == "word"
    assert i_nav_left.slots["count"] == 3
    assert i_nav_left.slots["direction"] == "left"

    i_cap = parse("capitalize that")
    assert i_cap.kind == Kind.TEXT_EDIT
    assert i_cap.slots["action"] == "capitalize"

    i_dup = parse("duplicate current line")
    assert i_dup.kind == Kind.TEXT_EDIT
    assert i_dup.slots["action"] == "duplicate_line"

    i_wc = parse("word count")
    assert i_wc.kind == Kind.TEXT_INSPECT
    assert i_wc.slots["action"] == "word_count"

    i_h1 = parse("make heading 1")
    assert i_h1.kind == Kind.TEXT_FORMAT
    assert i_h1.slots["style"] == "heading 1"


def test_text_editor_primitives():
    executor = MagicMock()
    editor = TextEditor(executor)

    ok, msg = editor.select("all")
    assert ok and "all" in msg
    executor.hotkey.assert_called_with("ctrl", "a")

    ok, msg = editor.select("line")
    assert ok and "line" in msg
    executor.press.assert_called_with("home")
    executor.hotkey.assert_called_with("shift", "end")

    ok, msg = editor.move_cursor("word", count=2, direction="back")
    assert ok and "2 words" in msg

    ok, msg = editor.duplicate_line()
    assert ok and "Duplicated" in msg

    ok, msg = editor.format_structure("heading 1")
    assert ok and "Heading 1" in msg
    executor.hotkey.assert_called_with("ctrl", "alt", "1")


def test_reference_resolution_previous_next_field():
    # Point 24: pronoun & reference resolution
    ctx = TaskContext("task_1")
    f1 = UIElement(1, "Username", "Edit", (10, 10, 100, 25))
    f2 = UIElement(2, "Password", "Edit", (10, 50, 100, 25))
    f3 = UIElement(3, "Email", "Edit", (10, 90, 100, 25))
    snap = ScreenSnapshot("Login", "app.exe", (0, 0, 800, 600), elements=[f1, f2, f3], focus=f2)

    # Next field from Password should be Email
    el, err = resolve_reference(ctx, snap, target="next field")
    assert err is None
    assert el.name == "Email"

    # Previous field from Password should be Username
    el, err = resolve_reference(ctx, snap, target="previous field")
    assert err is None
    assert el.name == "Username"


def test_reference_resolution_disambiguation():
    # Point 25: clarification when targets are ambiguous
    ctx = TaskContext("task_2")
    b1 = UIElement(1, "Save", "Button", (10, 10, 50, 25))
    b2 = UIElement(2, "Save", "Button", (100, 200, 50, 25))
    c1 = UIElement(3, "Cancel", "Button", (160, 200, 50, 25))
    snap = ScreenSnapshot("Editor", "app.exe", (0, 0, 800, 600), elements=[b1, b2, c1])

    # Disambiguation triggers when multiple distinct elements share target label
    el, err = resolve_reference(ctx, snap, target="Save")
    assert el is None
    assert err == "ambiguous"


def test_assignment_workflow_grounding_rejects_empty_screen(monkeypatch):
    import pyperclip

    monkeypatch.setattr(pyperclip, "paste", lambda: "")
    # Point 39: protection against treating unrelated screen text as an assignment
    workflow = AssignmentWorkflow()
    session = MagicMock()
    session.worker.live = None
    session.worker.observe.return_value = None

    # Blank screen text should never manufacture generic assignments
    res = workflow.start_assignment_from_session(session)
    assert "could not detect an assignment" in res.lower()
    assert workflow.active_assignment is None


def test_assignment_submission_confirmation_states_attempt_and_irreversibility():
    # Point 45: states course, assignment, filename, attempt number, and irreversible consequence
    workflow = AssignmentWorkflow()
    a = Assignment(
        assignment_id="a1",
        title="Essay 1",
        course="History 101",
        rubric=[RubricCriterion(criterion="Intro", completed=True)],
    )
    conf = workflow.prepare_submission_confirmation(a, Path("History_Essay.pdf"), attempt=2)
    assert "History 101" in conf
    assert "Essay 1" in conf
    assert "History_Essay.pdf" in conf
    assert "attempt 2" in conf
    assert "irreversible" in conf


def test_paused_goal_recovery_across_restarts():
    # Point 47: paused goals correctly restored
    conn = connect(":memory:")
    gm1 = GoalManager(conn)
    g1 = gm1.start_goal("Finish Research", ["Step 1", "Step 2"])
    gm1.pause_goal()
    assert g1.status == "paused"

    # Simulate restart by instantiating new GoalManager
    gm2 = GoalManager(conn)
    restored = gm2.active_goal
    assert restored is not None
    assert restored.goal_id == g1.goal_id
    assert restored.status == "paused"

    # Resume goal
    resumed = gm2.resume_goal()
    assert resumed is not None
    assert resumed.status == "active"


def test_workspace_auto_test_detection_and_git_status(tmp_path):
    # Points 54 and 55: tool detection and ordinary-language git status
    agent = WorkspaceAgent(tmp_path)
    pkg = tmp_path / "package.json"
    pkg.write_text('{"name": "test"}', encoding="utf-8")
    assert agent.auto_detect_test_command() == ["npm", "test"]
    pkg.unlink()

    cargo = tmp_path / "Cargo.toml"
    cargo.write_text('[package]\nname = "test"', encoding="utf-8")
    assert agent.auto_detect_test_command() == ["cargo", "test"]

    # Git status explanation returns clean message or informative message
    msg = agent.explain_git_status()
    assert isinstance(msg, str) and len(msg) > 0


def test_session_user_taught_alias():
    # Point 26: user-taught aliases connected to runtime
    spoken = []
    s = Session(speak=spoken.append, db_path=":memory:")
    s.handle("call visual studio code as code")
    assert any("remember that code means visual studio code" in t for t in spoken)
    assert s.store.get_pref("alias:code") == "visual studio code"
    s.close()
