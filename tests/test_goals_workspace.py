"""Unit and integration tests for GoalManager, AssignmentWorkflow, WorkspaceAgent,
RelayState state machine, WinEventMonitor, and Earcon synthesis.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from relay.audio.earcons import (
    earcon,
    to_wav_bytes,
)
from relay.core.state import RelayState, relay_state_machine
from relay.goals.assignment import Assignment, AssignmentWorkflow
from relay.goals.goal import GoalManager
from relay.perception.events import WinEventMonitor
from relay.workspace.agent import WorkspaceAgent

# ---------------------------------------------------------------------------
# 1. State Machine Tests
# ---------------------------------------------------------------------------


class TestRelayStateMachine:
    """Verifies the 17-state dialogue and lifecycle state machine."""

    def test_all_17_states_exist(self) -> None:
        expected_states = {
            "booting",
            "greeting",
            "loading",
            "idle",
            "listening",
            "transcribing",
            "clarifying",
            "planning",
            "awaiting_confirmation",
            "acting",
            "verifying",
            "reporting",
            "paused",
            "cancelled",
            "emergency_stopped",
            "failed",
            "recovering",
        }
        actual_states = {s.value for s in RelayState}
        assert actual_states == expected_states
        assert len(RelayState) == 17

    def test_valid_transitions(self) -> None:
        from relay.core.bus import EventBus

        bus = EventBus()
        sm = relay_state_machine("test_machine", bus=bus)
        assert sm.state == RelayState.BOOTING

        assert sm.can(RelayState.GREETING) is True
        sm.transition(RelayState.GREETING)
        assert sm.state == RelayState.GREETING

        sm.transition(RelayState.LOADING)
        assert sm.state == RelayState.LOADING

        sm.transition(RelayState.IDLE)
        assert sm.state == RelayState.IDLE

        sm.transition(RelayState.LISTENING)
        assert sm.state == RelayState.LISTENING

        sm.transition(RelayState.TRANSCRIBING)
        assert sm.state == RelayState.TRANSCRIBING

        sm.transition(RelayState.PLANNING)
        assert sm.state == RelayState.PLANNING

        sm.transition(RelayState.AWAITING_CONFIRMATION)
        assert sm.state == RelayState.AWAITING_CONFIRMATION

        sm.transition(RelayState.ACTING)
        assert sm.state == RelayState.ACTING

        sm.transition(RelayState.VERIFYING)
        assert sm.state == RelayState.VERIFYING

        sm.transition(RelayState.REPORTING)
        assert sm.state == RelayState.REPORTING

        sm.transition(RelayState.IDLE)
        assert sm.state == RelayState.IDLE

    def test_invalid_transition_rejected(self) -> None:
        from relay.core.state import InvalidTransition

        sm = relay_state_machine("test_invalid")
        # BOOTING to ACTING is not allowed directly
        assert sm.can(RelayState.ACTING) is False
        with pytest.raises(InvalidTransition):
            sm.transition(RelayState.ACTING)

    def test_emergency_stop_from_acting(self) -> None:
        sm = relay_state_machine("test_emergency")
        sm.state = RelayState.ACTING
        assert sm.can(RelayState.EMERGENCY_STOPPED) is True
        sm.transition(RelayState.EMERGENCY_STOPPED)
        assert sm.state == RelayState.EMERGENCY_STOPPED
        # Can recover or go to idle
        assert sm.can(RelayState.RECOVERING) is True
        sm.transition(RelayState.RECOVERING)
        assert sm.state == RelayState.RECOVERING
        sm.transition(RelayState.IDLE)
        assert sm.state == RelayState.IDLE

    def test_event_bus_emission(self) -> None:
        from relay.core.bus import EventBus

        bus = EventBus()
        events = []
        bus.subscribe("relay.state", lambda evt: events.append(evt.data))

        sm = relay_state_machine("test_bus", bus=bus)
        sm.transition(RelayState.GREETING)
        assert len(events) == 1
        assert events[0]["from"] == "booting"
        assert events[0]["to"] == "greeting"


# ---------------------------------------------------------------------------
# 2. Earcons Tests
# ---------------------------------------------------------------------------


class TestEarcons:
    """Verifies that all 12 procedural earcons synthesize valid WAV headers."""

    @pytest.mark.parametrize(
        "name",
        [
            "listen",
            "heard",
            "processing",
            "success",
            "warning",
            "uncertainty",
            "cancellation",
            "nothing",
            "failure",
            "error",
            "emergency_stop",
            "alert",
        ],
    )
    def test_earcon_generation(self, name: str) -> None:
        snd, sr = earcon(name)
        assert snd is not None
        assert len(snd) > 0
        assert sr == 22050

        wav_data = to_wav_bytes(name)
        assert isinstance(wav_data, bytes)
        assert len(wav_data) > 44  # Standard WAV header is 44 bytes
        assert wav_data[:4] == b"RIFF"
        assert wav_data[8:12] == b"WAVE"
        assert wav_data[12:16] == b"fmt "


# ---------------------------------------------------------------------------
# 3. WinEventMonitor Tests
# ---------------------------------------------------------------------------


class TestWinEventMonitor:
    """Verifies event monitor debouncer and clean lifecycle."""

    def test_monitor_debounce_and_start_stop(self) -> None:
        triggered: list[int] = []

        def on_event() -> None:
            triggered.append(1)

        monitor = WinEventMonitor(on_change=on_event, debounce_s=0.05)
        # Test debouncer directly
        monitor._trigger_debounced()
        monitor._trigger_debounced()
        monitor._trigger_debounced()

        # Wait for debouncer
        time.sleep(0.15)
        monitor.stop()

        # Should only have fired once due to debouncing
        assert len(triggered) == 1


# ---------------------------------------------------------------------------
# 4. GoalManager Tests
# ---------------------------------------------------------------------------


class TestGoalManager:
    """Verifies multi-mode goals, checkpoints, persistence, and recovery."""

    def test_create_and_manage_goal(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test_goals.db")
        conn = sqlite3.connect(db_path)
        manager = GoalManager(conn=conn)

        goal = manager.start_goal(
            title="Complete CS50 Homework 1",
            mode="Assignment",
            steps=[
                "Read assignment PDF",
                "Write python solution",
                "Run test suite",
                "Submit solution",
            ],
            context={"course": "CS50", "due_date": "2026-10-01"},
        )

        assert goal.goal_id is not None
        assert goal.mode == "Assignment"
        assert len(goal.steps) == 4
        assert goal.status == "active"
        assert goal.steps[0].state == "current"

        # Advance step 0
        manager.advance_step(evidence="Read PDF pages 1-4")
        assert goal.current_step_index == 1
        assert goal.steps[0].state == "completed"
        assert goal.steps[0].evidence == "Read PDF pages 1-4"
        assert goal.steps[1].state == "current"

        # Add a checkpoint
        manager.create_checkpoint("Finished reading instructions")
        assert len(goal.checkpoints) == 1
        assert goal.checkpoints[0]["note"] == "Finished reading instructions"

        # Pause goal
        paused = manager.pause_goal()
        assert paused is not None
        assert paused.status == "paused"

        # Resume goal
        resumed = manager.resume_goal()
        assert resumed is not None
        assert resumed.status == "active"
        conn.close()

    def test_goal_persistence_across_manager_restarts(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "persistent_goals.db")
        conn1 = sqlite3.connect(db_path)
        manager1 = GoalManager(conn=conn1)

        g = manager1.start_goal(
            title="Write Research Paper",
            mode="Writing",
            steps=["Outline", "Draft Introduction", "Draft Body", "References"],
        )
        manager1.advance_step(evidence="Outline finalized")
        conn1.close()

        # Restart manager with fresh connection to same DB
        conn2 = sqlite3.connect(db_path)
        manager2 = GoalManager(conn=conn2)
        loaded = manager2.store.load_goal(g.goal_id)
        assert loaded is not None
        assert loaded.title == "Write Research Paper"
        assert loaded.mode == "Writing"
        assert len(loaded.steps) == 4
        assert loaded.steps[0].state == "completed"
        assert loaded.steps[0].evidence == "Outline finalized"
        assert loaded.current_step_index == 1
        conn2.close()


# ---------------------------------------------------------------------------
# 5. AssignmentWorkflow Tests
# ---------------------------------------------------------------------------


class TestAssignmentWorkflow:
    """Verifies instructions parsing, rubric checklist, accessible doc gen,
    and gated confirmation prompt before submission."""

    def test_parse_instructions_and_rubric(self) -> None:
        instructions = (
            "Title: Operating Systems Lab 2\n"
            "Deadline: Friday 11:59 PM\n"
            "Format: pdf\n"
            "Instructions:\n"
            "- Implement Round Robin process scheduler\n"
            "- Implement Preemptive Priority scheduler\n"
            "- Clean memory leaks and test edge cases\n"
        )
        wf = AssignmentWorkflow()
        assignment = wf.parse_instructions(
            raw_text=instructions,
            title="Operating Systems Lab 2",
            course="CS301",
        )

        assert assignment.course == "CS301"
        assert assignment.title == "Operating Systems Lab 2"
        assert len(assignment.rubric) >= 3
        rubric_texts = [r.criterion for r in assignment.rubric]
        assert any("Round Robin" in r for r in rubric_texts)

    def test_accessible_document_generation(self, tmp_path: Path) -> None:
        wf = AssignmentWorkflow()
        doc_path = tmp_path / "accessible_report.md"

        sections = [
            ("Abstract", "This report explores Round Robin and Priority scheduling."),
            ("Performance Metrics", "The simulation results show low latency across 50 tasks."),
        ]

        generated_file = wf.generate_accessible_document(
            title="Operating Systems Scheduling Analysis",
            author="Relay Student",
            sections=sections,
            output_path=doc_path,
        )

        assert generated_file.is_file()
        content = generated_file.read_text(encoding="utf-8")

        # Check accessibility structure: logical markdown headers
        assert "# Operating Systems Scheduling Analysis" in content
        assert "## Abstract" in content
        assert "## Performance Metrics" in content
        assert "Relay Student" in content

    def test_gated_submission_confirmation(self) -> None:
        wf = AssignmentWorkflow()
        assignment = Assignment(
            assignment_id="asg_01",
            title="Assignment 3",
            course="Operating Systems",
        )

        sub_file = Path("Operating_Systems_Assignment.pdf")
        prompt = wf.prepare_submission_confirmation(assignment, sub_file)
        expected_prompt = (
            "Submit Operating_Systems_Assignment.pdf to Operating Systems Assignment 3 now?"
        )
        assert prompt == expected_prompt

        # Verification of receipt
        sample_receipt = (
            "Submission confirmed: Operating_Systems_Assignment.pdf "
            "uploaded at 11:42 PM, attempt #1"
        )
        receipt = wf.verify_submission_receipt(
            receipt_text=sample_receipt,
            expected_filename="Operating_Systems_Assignment.pdf",
        )
        assert receipt["verified"] is True
        assert receipt["attempt"] == 1
        assert "11:42 PM" in receipt["timestamp"]


# ---------------------------------------------------------------------------
# 6. WorkspaceAgent Tests
# ---------------------------------------------------------------------------


class TestWorkspaceAgent:
    """Verifies file sandboxing, structured patches, checkpoints, and rollback."""

    def test_sandbox_path_traversal_prevention(self, tmp_path: Path) -> None:
        workspace_dir = tmp_path / "sandbox"
        workspace_dir.mkdir()
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("SUPER_SECRET_KEY", encoding="utf-8")

        agent = WorkspaceAgent(root_dir=workspace_dir)

        # Attempt to read outside workspace root
        with pytest.raises(PermissionError):
            agent.read_file(str(secret_file))

        # Attempt directory traversal with ..
        with pytest.raises(PermissionError):
            agent.read_file("../secret.txt")

        # Writing outside workspace must also raise PermissionError
        with pytest.raises(PermissionError):
            agent.apply_patch("../evil.txt", "evil content")

    def test_sandboxed_file_read_write(self, tmp_path: Path) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        agent = WorkspaceAgent(root_dir=workspace_dir)

        agent.apply_patch("main.py", "print('hello relay')\n")
        content = agent.read_file("main.py")
        assert content == "print('hello relay')\n"

        files = agent.list_files()
        assert "main.py" in files

    def test_patch_proposal_and_accessible_diff(self, tmp_path: Path) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        agent = WorkspaceAgent(root_dir=workspace_dir)

        agent.apply_patch("code.py", "def add(a, b):\n    return a - b\n")

        new_code = "def add(a, b):\n    return a + b\n"
        patch = agent.propose_patch("code.py", new_code)

        assert patch.file_path == "code.py"
        assert "-    return a - b" in patch.diff_text
        assert "+    return a + b" in patch.diff_text
        assert patch.lines_added == 1
        assert patch.lines_removed == 1
        assert "1 lines added" in patch.spoken_summary

    def test_checkpoint_and_rollback(self, tmp_path: Path) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        agent = WorkspaceAgent(root_dir=workspace_dir)

        agent.apply_patch("data.txt", "v1 initial state\n")
        ckpt = agent.create_checkpoint("initial_checkpoint")

        # Mutate file
        agent.apply_patch("data.txt", "v2 broke everything\n")
        assert agent.read_file("data.txt") == "v2 broke everything\n"

        # Rollback
        success = agent.rollback(ckpt.checkpoint_id)
        assert success is True
        assert agent.read_file("data.txt") == "v1 initial state\n"
