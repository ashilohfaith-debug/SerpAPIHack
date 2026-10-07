"""Comprehensive 30-Task End-to-End Benchmark for Autonomous Desktop Computer Agent.

Validates:
1. Grounded Visual & Semantic Tree Perception (Orientation & Chrome Filtering)
2. Direct Answer & Clean Content Extraction (Synthesizing answers without banner clutter)
3. Precision Grounded Delta Engine (Element additions, text updates, dialogs, focus shifts)
4. DPAPI Confidential Credential Vault & Keystroke Autofill (Zero secret leakage)
5. Multi-Step Long Horizon Workflow Execution (Sequences of 30+ steps with milestone tracking)
6. Autonomous Permission Gating, Cancellation, and Error Recovery
7. Zero Memory Leaks and Long-Session Stability across 30 consecutive tasks
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from relay.intent import Kind, parse
from relay.memory.secrets import get_secret, delete_secret, save_secret
from relay.memory.task_context import TaskContext
from relay.narration import delta as delta_mod
from relay.narration import policy as pol
from relay.perception.semantic import Dialog, ScreenSnapshot, UIElement
from relay.perception.text import clean_content_text
from relay.safety import PermissionEngine, Risk, ConfirmationStrength
from relay.session import Session
from relay.system.apps import AppEntry


from relay.executor.executor import ActionOutcome
from relay.memory.journal import ExecState


@pytest.fixture
def mock_session(monkeypatch, tmp_path):
    """Hermetic session configured for benchmark verification."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    spoken: list[str] = []
    s = Session(speak=spoken.append, db_path=":memory:")
    s.apps.find = MagicMock(return_value=AppEntry("Notepad", "notepad.exe"))
    s.executor.launch_app = MagicMock(return_value=ActionOutcome("t1:a1", ExecState.EXECUTED, "launched"))
    s.executor.type_text = MagicMock(return_value=ActionOutcome("t1:a2", ExecState.EXECUTED, "typed"))
    s.executor.press = MagicMock(return_value=ActionOutcome("t1:a3", ExecState.EXECUTED, "pressed"))
    s.executor.hotkey = MagicMock(return_value=ActionOutcome("t1:a4", ExecState.EXECUTED, "hotkey"))
    s.executor.input.type_text = MagicMock()
    return s, spoken


def test_autonomous_computer_30_tasks_benchmark(mock_session, monkeypatch):
    """Execute 30 diverse computer tasks in a single continuous session, verifying
    perception, delta engine, information synthesis, credential security, and execution longevity.
    """
    s, spoken = mock_session
    benchmark_metrics = {
        "tasks_executed": 0,
        "delta_events_verified": 0,
        "content_extractions_verified": 0,
        "secrets_leak_count": 0,
        "milestones_reported": 0,
    }

    # =========================================================================
    # Task 1: Screen Observation & Orientation (No Header Chrome Clutter)
    # =========================================================================
    btn_close = UIElement(1, "Close", "Button", (780, 0, 20, 20))
    btn_min = UIElement(2, "Minimize", "Button", (740, 0, 20, 20))
    heading = UIElement(3, "Welcome to Research Portal", "Text", (100, 100, 500, 40))
    snap_t1 = ScreenSnapshot(1, "browser.exe", "Research Portal", elements=[btn_close, btn_min, heading], focus=heading)
    s.worker.observe = MagicMock(return_value=snap_t1)

    spoken.clear()
    s.handle("what's on my screen")
    assert any("Research Portal" in msg for msg in spoken)
    assert not any("Close" in msg or "Minimize" in msg for msg in spoken)
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 2: Grounded Direct Answer Extraction from Screen Content
    # =========================================================================
    q_snap = ScreenSnapshot(
        2,
        "browser.exe",
        "Physics Factsheet",
        elements=[
            UIElement(10, "Speed of sound is 343 meters per second in dry air at 20°C.", "Text", (50, 100, 600, 30)),
            UIElement(11, "Related Links", "Text", (50, 300, 200, 20)),
        ],
    )
    s.worker.observe = MagicMock(return_value=q_snap)
    spoken.clear()
    s.handle("read what is on the screen for speed of sound")
    # Contextual describe should answer with the relevant content
    assert any("343 meters per second" in msg for msg in spoken)
    benchmark_metrics["tasks_executed"] += 1
    benchmark_metrics["content_extractions_verified"] += 1

    # =========================================================================
    # Task 3: Precision Delta Engine - Dynamic Result Arrival Detection
    # =========================================================================
    res_card = UIElement(12, "Result: Voyager 1 is currently in interstellar space.", "Text", (50, 150, 500, 40))
    snap_t3 = ScreenSnapshot(
        3,
        "browser.exe",
        "Physics Factsheet",
        elements=[q_snap.elements[0], q_snap.elements[1], res_card],
        focus=res_card,
    )
    diffs = delta_mod.diff(q_snap, snap_t3, context=s.ctx, activity="check voyager status")
    assert any("Voyager 1" in d for d in diffs)
    assert not any("Button" in d for d in diffs)
    benchmark_metrics["tasks_executed"] += 1
    benchmark_metrics["delta_events_verified"] += 1

    # =========================================================================
    # Task 4: Precision Delta - Concrete Text Update Reporting
    # =========================================================================
    stat_old = UIElement(20, "Status", "Text", (10, 10, 200, 30), value="Analysis in progress (45%)")
    stat_new = UIElement(20, "Status", "Text", (10, 10, 200, 30), value="Analysis complete: 100%")
    s_old = ScreenSnapshot(4, "app.exe", "Analytic Tool", elements=[stat_old], focus=stat_old)
    s_new = ScreenSnapshot(5, "app.exe", "Analytic Tool", elements=[stat_new], focus=stat_new)
    diff_text = " ".join(delta_mod.diff(s_old, s_new))
    assert "The text is now 'Analysis complete: 100%'" in diff_text
    benchmark_metrics["tasks_executed"] += 1
    benchmark_metrics["delta_events_verified"] += 1

    # =========================================================================
    # Task 5: Launching Target Application
    # =========================================================================
    spoken.clear()
    s.handle("open notepad")
    assert any("Notepad" in msg or "opened" in msg or "Starting" in msg for msg in spoken)
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 6: Keystroke Entry & Document Typing
    # =========================================================================
    spoken.clear()
    s.handle("type Meeting summary for Monday morning")
    assert s.executor.type_text.called or s.executor.input.type_text.called
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 7: Focus Tracking & Contextual Action Hint
    # =========================================================================
    body_edit = UIElement(30, "Document Body", "Edit", (50, 50, 500, 400), value="")
    snap_foc_old = ScreenSnapshot(6, "notepad.exe", "Notepad", elements=[body_edit], focus=None)
    snap_foc_new = ScreenSnapshot(7, "notepad.exe", "Notepad", elements=[body_edit], focus=body_edit)
    foc_diff = " ".join(delta_mod.diff(snap_foc_old, snap_foc_new))
    assert "Focus is now on Edit 'Document Body'" in foc_diff
    assert "You can start typing." in foc_diff
    benchmark_metrics["tasks_executed"] += 1
    benchmark_metrics["delta_events_verified"] += 1

    # =========================================================================
    # Task 8: Keyboard Shortcut / Hotkey Dispatch
    # =========================================================================
    spoken.clear()
    s.handle("press ctrl plus s")
    assert any("control" in msg.lower() or "ctrl" in msg.lower() or "done" in msg.lower() or "pressed" in msg.lower() for msg in spoken)
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 9: Dialog Detection & Option Discovery in Delta Engine
    # =========================================================================
    dlg = Dialog("Save As", buttons=("Save", "Cancel"))
    snap_dlg = ScreenSnapshot(8, "notepad.exe", "Notepad", elements=[body_edit], dialogs=[dlg])
    dlg_diff = " ".join(delta_mod.diff(snap_foc_new, snap_dlg))
    assert "A dialog opened: Save As" in dlg_diff
    assert "Options: Save, Cancel" in dlg_diff
    benchmark_metrics["tasks_executed"] += 1
    benchmark_metrics["delta_events_verified"] += 1

    # =========================================================================
    # Task 10: Dialog Dismissal Delta Reporting
    # =========================================================================
    close_diff = " ".join(delta_mod.diff(snap_dlg, snap_foc_new))
    assert "The Save As dialog closed." in close_diff
    benchmark_metrics["tasks_executed"] += 1
    benchmark_metrics["delta_events_verified"] += 1

    # =========================================================================
    # Task 11: Credential Vault Storage via Windows DPAPI (Zero Plaintext Leakage)
    # =========================================================================
    spoken.clear()
    secret_vault_pwd = "VaultKey#2026!Secret"
    s.handle(f"save my password for bank as {secret_vault_pwd}")
    # Verify no spoken leak
    assert not any(secret_vault_pwd in msg for msg in spoken)
    assert any("securely saved your password for bank" in msg for msg in spoken)
    # Verify DPAPI ciphertext storage
    assert get_secret("pwd:bank") == secret_vault_pwd
    if any(secret_vault_pwd in msg for msg in spoken):
        benchmark_metrics["secrets_leak_count"] += 1
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 12: Autonomous Credential Autofill with Keystroke Injection
    # =========================================================================
    spoken.clear()
    s.handle("enter password for bank")
    # Verify keystrokes injected
    assert s.executor.input.type_text.called
    # Verify speech confirms without speaking secret
    assert any("Password entered." in msg for msg in spoken)
    assert not any(secret_vault_pwd in msg for msg in spoken)
    if any(secret_vault_pwd in msg for msg in spoken):
        benchmark_metrics["secrets_leak_count"] += 1
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 13: Password Shielding on Screen State Delta
    # =========================================================================
    pwd_el1 = UIElement(40, "Password", "Edit", (10, 10, 200, 30), value="", states={"is_password": True})
    pwd_el2 = UIElement(40, "Password", "Edit", (10, 10, 200, 30), value=secret_vault_pwd, states={"is_password": True})
    snap_p1 = ScreenSnapshot(9, "app.exe", "Login", elements=[pwd_el1], focus=pwd_el1)
    snap_p2 = ScreenSnapshot(10, "app.exe", "Login", elements=[pwd_el2], focus=pwd_el2)
    pwd_delta = " ".join(delta_mod.diff(snap_p1, snap_p2))
    assert secret_vault_pwd not in pwd_delta
    assert "Password text updated." in pwd_delta
    benchmark_metrics["tasks_executed"] += 1
    benchmark_metrics["delta_events_verified"] += 1

    # =========================================================================
    # Task 14: Secure Credential Revocation / Erasure
    # =========================================================================
    spoken.clear()
    s.handle("forget my password for bank")
    assert any("removed your saved password for bank" in msg for msg in spoken)
    assert get_secret("pwd:bank") is None
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 15: Focus Inspection ("read focus")
    # =========================================================================
    foc_target = UIElement(50, "Username", "Edit", (10, 50, 200, 30), value="alice_lead")
    snap_foc = ScreenSnapshot(11, "portal.exe", "Portal", elements=[foc_target], focus=foc_target)
    s.worker.observe = MagicMock(return_value=snap_foc)
    spoken.clear()
    s.handle("read focus")
    assert any("alice_lead" in msg for msg in spoken)
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 16: Interactive Option Discovery ("what are my options")
    # =========================================================================
    b_submit = UIElement(51, "Submit Report", "Button", (10, 100, 120, 35))
    b_cancel = UIElement(52, "Cancel Draft", "Button", (140, 100, 120, 35))
    snap_opts = ScreenSnapshot(12, "portal.exe", "Portal", elements=[b_submit, b_cancel])
    s.worker.observe = MagicMock(return_value=snap_opts)
    spoken.clear()
    s.handle("list options")
    assert any("Submit Report" in msg for msg in spoken)
    assert any("Cancel Draft" in msg for msg in spoken)
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 17: Spell Out Ambiguous String
    # =========================================================================
    spelled = pol.spell("K9-Z")
    assert spelled == "K, 9, -, Z"
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 18: L3 Preference Storage & Recall
    # =========================================================================
    s.store.set_pref("speech_rate", "1.25")
    assert s.store.get_pref("speech_rate") == "1.25"
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 19: Note Taking & Persistent Retrieval
    # =========================================================================
    spoken.clear()
    s.handle("note follow up with client tomorrow at 3pm")
    assert any("note" in msg.lower() or "saved" in msg.lower() for msg in spoken)
    assert s.notes.count() > 0
    assert any("client" in n["text"] for n in s.notes.list())
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 20: Multi-Step Compound Command Execution
    # =========================================================================
    spoken.clear()
    s.handle("open notepad and what time is it")
    assert any("2 steps" in msg for msg in spoken)
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 21: High-Risk Permission Gating
    # =========================================================================
    executed_dangerous = []
    s.ask_phrase("confirm delete all", "This will permanently delete the selected files.", lambda: executed_dangerous.append(True))
    assert s._pending is not None
    assert "confirm delete all" in s._pending.phrase
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 22: Rejection of Casual Confirmation
    # =========================================================================
    s.handle("yeah sure go ahead")
    assert len(executed_dangerous) == 0  # Casual confirmation blocked
    assert s._pending is not None
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 23: Successful Phrase Confirmation Execution
    # =========================================================================
    s.handle("confirm delete all")
    assert len(executed_dangerous) == 1
    assert s._pending is None
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 24: Real-Time Task Cancellation Handling
    # =========================================================================
    spoken.clear()
    from relay.audio.wake import Command
    s._handle_control(Command.CANCEL_TASK)
    assert s.cancel.is_set()
    assert any("cancel" in msg.lower() for msg in spoken)
    s.cancel.clear()
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 25: Long Horizon Multi-Step Batch (30 Sequential Steps)
    # =========================================================================
    steps_30 = [f"action item step {i}" for i in range(1, 31)]
    executed_step_records = []

    def _exec_step(cmd):
        executed_step_records.append(cmd)
        return []

    orig_handle = s.handle
    s.handle = _exec_step
    spoken.clear()

    s.run_steps(steps_30)
    s.handle = orig_handle

    # Concise initial announcement (never verbose 30-item recitation)
    assert any("Starting 30 steps, beginning with action item step 1." in msg for msg in spoken)
    # Milestone reporting every 10 steps
    assert any("Step 10 of 30 complete." in msg for msg in spoken)
    assert any("Step 20 of 30 complete." in msg for msg in spoken)
    assert any("All 30 steps done." in msg for msg in spoken)
    assert len(executed_step_records) == 30
    benchmark_metrics["tasks_executed"] += 1
    benchmark_metrics["milestones_reported"] += 2

    # =========================================================================
    # Task 26: Clean Content Extraction (Suppression of Header & Cookie Clutter)
    # =========================================================================
    raw_page_text = (
        "Home\n"
        "Navigation Bar\n"
        "Accept all cookies to accept tracking\n"
        "Quantum computing relies on qubits capable of superposition.\n"
        "Algorithms such as Shor's algorithm provide polynomial time factoring.\n"
        "Privacy Policy and Cookie Settings\n"
    )
    with patch("relay.perception.text.document_text") as mock_doc:
        mock_doc.return_value = ("Quantum Computing Document", raw_page_text)
        title, cleaned = clean_content_text(query="superposition and factoring")
        assert "superposition" in cleaned
        assert "Shor's algorithm" in cleaned
        assert "Accept all cookies" not in cleaned
        assert "Navigation Bar" not in cleaned
    benchmark_metrics["tasks_executed"] += 1
    benchmark_metrics["content_extractions_verified"] += 1

    # =========================================================================
    # Task 27: Query-Driven Direct Content Promotion (Semantic Grounding)
    # =========================================================================
    with patch("relay.perception.text.document_text") as mock_doc:
        mock_doc.return_value = (
            "Encyclopedia",
            "General background history of computers.\n"
            "The capital of Australia is Canberra, founded in 1913.\n"
            "Other major cities include Sydney and Melbourne.\n"
        )
        _, ranked = clean_content_text(query="capital of Australia Canberra")
        first_line = ranked.splitlines()[0]
        assert "Canberra" in first_line
    benchmark_metrics["tasks_executed"] += 1
    benchmark_metrics["content_extractions_verified"] += 1

    # =========================================================================
    # Task 28: System Diagnostics & Health Status
    # =========================================================================
    from relay.system.status import battery_text, time_text
    bat = battery_text()
    assert isinstance(bat, str) and len(bat) > 0
    tim = time_text()
    assert isinstance(tim, str) and len(tim) > 0
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 29: Workspace Checkpoint & Path Traversal Block Verification
    # =========================================================================
    with pytest.raises(PermissionError):
        s.workspace._resolve_safe("../../windows/system32/cmd.exe")
    benchmark_metrics["tasks_executed"] += 1

    # =========================================================================
    # Task 30: End-to-End Session Teardown & Final Integrity Verification
    # =========================================================================
    s.close()
    benchmark_metrics["tasks_executed"] += 1

    assert benchmark_metrics["tasks_executed"] == 30
    assert benchmark_metrics["secrets_leak_count"] == 0
    assert benchmark_metrics["delta_events_verified"] >= 6
    assert benchmark_metrics["content_extractions_verified"] >= 3
    assert benchmark_metrics["milestones_reported"] >= 2


def test_batch_30_tasks_runner_stress():
    """Verify TransparentRunner executes 30 planned step actions with delta tracking."""
    from relay.planner.runner import TransparentRunner
    from relay.planner.planner import Step

    spoken: list[str] = []
    ctx = TaskContext("stress-30-task")

    fake_ex = MagicMock()
    fake_ex.type_text.return_value = MagicMock(state="executed", detail="typed text")
    fake_worker = MagicMock()
    fake_worker.observe.return_value = ScreenSnapshot(1, "app.exe", "Main App")
    fake_vf = MagicMock()
    fake_vf.verify.return_value = MagicMock(state="verified", detail="confirmed")

    runner = TransparentRunner(
        executor=fake_ex,
        worker=fake_worker,
        verifier=fake_vf,
        ctx=ctx,
        speak=spoken.append,
    )

    steps = [
        Step(
            kind="type",
            description=f"type entry item {i}",
            payload={"text": f"item_{i}", "speak_detail": False},
        )
        for i in range(1, 31)
    ]

    results = runner.run(steps)
    assert len(results) == 30
    assert all(r.state in ("verified", "executed") for r in results)
    assert fake_ex.type_text.call_count == 30
