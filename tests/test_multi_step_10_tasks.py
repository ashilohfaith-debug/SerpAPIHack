"""Tests for multi-step tasks (10 steps end-to-end) in RELAY.

Validates that complex multi-step workflows (10+ steps) execute sequentially,
transparently announce progress and milestones, integrate with the delta engine,
and safely handle cancellations and failures without blind execution.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from relay.intent.compound import split_steps
from relay.llm.assistant import Assistant, validate_command
from relay.llm.router import Router
from relay.memory.journal import ExecState
from relay.memory.task_context import TaskContext
from relay.perception.semantic import ScreenSnapshot, UIElement
from relay.planner.planner import Step
from relay.planner.runner import StepResult, TransparentRunner
from relay.session import Session
from relay.verifier.verifier import ActionOutcome


def test_split_steps_10_commands_compound():
    """Verify that a 10-step compound command is parsed into exactly 10 sequential commands."""
    utterance = (
        "open notepad then type first line then press enter then "
        "type second line then press enter then type third line then "
        "press enter then type fourth line then press enter then save it"
    )
    steps = split_steps(utterance)
    assert steps is not None
    assert len(steps) == 10
    assert steps[0] == "open notepad"
    assert steps[1] == "type first line"
    assert steps[2] == "press enter"
    assert steps[3] == "type second line"
    assert steps[4] == "press enter"
    assert steps[5] == "type third line"
    assert steps[6] == "press enter"
    assert steps[7] == "type fourth line"
    assert steps[8] == "press enter"
    assert steps[9] == "save it"


def test_session_runs_10_step_task_end_to_end():
    """Session executes all 10 steps sequentially, announcing start, milestones, and completion."""
    spoken: list[str] = []
    executed: list[str] = []

    s = Session(speak=spoken.append, db_path=":memory:")

    # Mock handle to record execution and return verified results
    original_handle = s.handle

    def mock_handle(step_text: str):
        executed.append(step_text)
        res = StepResult(description=step_text, state="verified")
        return [res]

    s.handle = mock_handle

    steps = [
        "open notepad",
        "type line one",
        "press enter",
        "type line two",
        "press enter",
        "type line three",
        "press enter",
        "type line four",
        "press enter",
        "save file",
    ]

    results = s.run_steps(steps)

    # 1. All 10 steps executed
    assert len(executed) == 10
    assert executed == steps
    assert len(results) == 10

    # 2. Starting announcement made
    assert any("Starting 10 steps, beginning with open notepad" in msg for msg in spoken)

    # 3. Completion announcement made
    assert any("All 10 steps done." in msg for msg in spoken)

    s.close()


def test_assistant_multi_step_plan_10_steps():
    """Assistant generates and validates a 10-step plan, which session executes."""
    # 10 DO commands
    ten_do_lines = "\n".join([
        f"DO: type Item {i}" if i % 2 == 1 else "DO: press enter"
        for i in range(1, 11)
    ])

    mock_router = MagicMock(spec=Router)
    mock_router.stream.return_value = [ten_do_lines]

    assistant = Assistant(router=mock_router)
    spoken: list[str] = []
    mode, payload = assistant.respond("create a 10-item checklist", speak=spoken.append)

    assert mode == "plan"
    assert isinstance(payload, list)
    assert len(payload) == 10
    for cmd in payload:
        assert validate_command(f"DO: {cmd}") is not None

    # Now execute this plan through session
    s_spoken: list[str] = []
    executed_cmds: list[str] = []
    s = Session(speak=s_spoken.append, db_path=":memory:")

    def mock_step_exec(cmd: str):
        executed_cmds.append(cmd)
        return [StepResult(cmd, "verified")]

    s.handle = mock_step_exec

    out = s.run_steps(payload)
    assert len(executed_cmds) == 10
    assert len(out) == 10
    assert any("All 10 steps done." in msg for msg in s_spoken)
    s.close()


def test_transparent_runner_10_step_plan():
    """TransparentRunner executes 10 discrete steps with delta diffing and milestones."""
    spoken: list[str] = []
    ctx = TaskContext("multi-step-10")

    worker = MagicMock()
    # Mock observation trees
    def mock_observe(timeout=3.0):
        return ScreenSnapshot(
            1,
            foreground_app="Notepad",
            foreground_title="Document - Notepad",
            elements=[
                UIElement(1, "Edit", "edit", (0, 0, 100, 100), value="Text content"),
            ],
        )
    worker.observe = mock_observe

    executor = MagicMock()
    executor.type_text.return_value = ActionOutcome("1.0", ExecState.EXECUTED, "typed text")

    verifier = MagicMock()
    verifier.verify.return_value = ActionOutcome("1.0", ExecState.VERIFIED, "text verified")

    bus = MagicMock()

    runner = TransparentRunner(
        executor=executor,
        worker=worker,
        verifier=verifier,
        ctx=ctx,
        speak=spoken.append,
        bus=bus,
        mode="quick",
    )

    steps = [
        Step(
            kind="type",
            description=f"type line {i}",
            payload={"text": f"line {i}\n", "announce": f"typing line {i}"},
        )
        for i in range(1, 11)
    ]

    results = runner.run(steps)
    assert len(results) == 10
    assert all(r.state == "verified" for r in results)
    assert executor.type_text.call_count == 10

    # Task bus state emitted as acting then completed
    bus.emit.assert_any_call("task.state", to="acting")
    bus.emit.assert_any_call("task.state", to="completed")


def test_multi_step_10_task_cancel_midway():
    """Cancelling midway at step 5 cleanly aborts remaining steps."""
    spoken: list[str] = []
    executed: list[str] = []

    s = Session(speak=spoken.append, db_path=":memory:")

    def mock_handle(step_text: str):
        executed.append(step_text)
        if len(executed) == 5:
            # Trigger cancel midway
            s.cancel.set()
        return [StepResult(step_text, "verified")]

    s.handle = mock_handle

    steps = [f"step {i}" for i in range(1, 11)]
    results = s.run_steps(steps)

    # Executed steps 1 to 5, cancelled before step 6
    assert len(executed) == 5
    assert any("Stopped before step 6." in msg for msg in spoken)
    assert not any(f"step {j}" in executed for j in range(6, 11))
    s.close()


def test_multi_step_10_task_failure_stops_pipeline():
    """A failing step stops execution immediately and reports remaining undone steps."""
    spoken: list[str] = []
    executed: list[str] = []

    s = Session(speak=spoken.append, db_path=":memory:")

    def mock_handle(step_text: str):
        executed.append(step_text)
        if len(executed) == 3:
            s.step_failed()
            return [StepResult(step_text, "failed")]
        return [StepResult(step_text, "verified")]

    s.handle = mock_handle

    steps = [f"step {i}" for i in range(1, 11)]
    results = s.run_steps(steps)

    # Stopped at step 3
    assert len(executed) == 3
    assert any("I stopped at step 3, step 3, because it didn't work." in msg for msg in spoken)
    # Remaining steps announced as not done
    assert any("I didn't do: step 4; step 5; step 6" in msg for msg in spoken)
    s.close()
