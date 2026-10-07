"""Tests for Delta Engine overhaul, screen reading content extraction,
secure password management (DPAPI), and 60-step execution support.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from relay.intent import Kind, parse
from relay.memory.secrets import get_secret, delete_secret
from relay.memory.task_context import TaskContext
from relay.narration import delta as delta_mod
from relay.narration import policy as pol
from relay.perception.semantic import ScreenSnapshot, UIElement
from relay.perception.text import clean_content_text, visible_text
from relay.session import Session


# ============================================================================
# 1. Delta Engine & Content vs Chrome filtering
# ============================================================================

def test_delta_ignores_header_chrome_and_surfaces_content():
    """Verify that delta engine discards browser/app header buttons and surfaces real content."""
    ctx = TaskContext("task-delta-1")
    ctx.recent_query = "who won the game"
    ctx.recent_activity = "search"

    el_search = UIElement(1, "Search", "Edit", (100, 50, 400, 30), value="who won the game")
    snap1 = ScreenSnapshot(1, "brave.exe", "Search - Brave", elements=[el_search], focus=el_search)

    # In snap2, browser adds navigation buttons AND a content answer
    btn_back = UIElement(2, "Back", "Button", (10, 10, 30, 30))
    btn_home = UIElement(3, "Home", "Button", (40, 10, 30, 30))
    btn_reload = UIElement(4, "Reload page", "Button", (70, 10, 30, 30))
    btn_cookie = UIElement(5, "Accept all cookies", "Button", (200, 500, 120, 40))
    answer_text = UIElement(
        6,
        "Final Score: Tigers 5, Giants 2 in Game 7",
        "Text",
        (100, 150, 600, 80),
        value="Tigers won 5-2.",
    )

    snap2 = ScreenSnapshot(
        2,
        "brave.exe",
        "Search Results - Brave",
        elements=[el_search, btn_back, btn_home, btn_reload, btn_cookie, answer_text],
        focus=answer_text,
    )

    diffs = delta_mod.diff(snap1, snap2, context=ctx, activity="check game results")
    diff_text = " ".join(diffs)

    # Meaningful answer should be narrated
    assert "Tigers" in diff_text or "Final Score" in diff_text
    # Browser chrome buttons must NOT be narrated as new elements
    assert "Button 'Back'" not in diff_text
    assert "Button 'Home'" not in diff_text
    assert "Button 'Reload page'" not in diff_text
    assert "Accept all cookies" not in diff_text


def test_delta_reports_concrete_text_value_update():
    """When an element's text changes, the delta says 'The text is now ...' with the value."""
    el1 = UIElement(10, "Status", "Text", (100, 100, 200, 30), value="Loading results...")
    snap1 = ScreenSnapshot(1, "app.exe", "Main", elements=[el1], focus=el1)

    el2 = UIElement(10, "Status", "Text", (100, 100, 200, 30), value="Calculation complete: 42")
    snap2 = ScreenSnapshot(2, "app.exe", "Main", elements=[el2], focus=el2)

    diffs = delta_mod.diff(snap1, snap2)
    assert any("The text is now 'Calculation complete: 42'" in d for d in diffs)


# ============================================================================
# 2. Perception & Screen Reading Clean Content (Perplexity style)
# ============================================================================

def test_clean_content_text_filters_boilerplate_and_prioritizes_query():
    """clean_content_text strips toolbar buttons, cookie banners, and ranks query matches."""
    sample_text = (
        "Minimize\n"
        "Maximize\n"
        "Accept all cookies to continue\n"
        "Privacy policy and terms of service\n"
        "James Webb Space Telescope discovered an ancient galaxy from 300 million years after the Big Bang.\n"
        "The telescope continues its observational run."
    )

    with patch("relay.perception.text.document_text") as mock_doc:
        mock_doc.return_value = ("Discovery Article", sample_text)
        title, cleaned = clean_content_text(query="James Webb discovery")
        assert "James Webb Space Telescope discovered" in cleaned
        assert "Minimize" not in cleaned
        assert "Accept all cookies" not in cleaned


def test_policy_describe_focuses_on_content_matching_query():
    """pol.describe prioritizes query-matching content over window chrome."""
    header = UIElement(1, "Toolbar navigation", "ToolBar", (0, 0, 800, 40))
    result = UIElement(2, "Paris is the capital of France.", "Text", (50, 100, 400, 50))
    snap = ScreenSnapshot(1, "browser.exe", "Search - Browser", elements=[header, result], focus=result)

    ctx = TaskContext("task-describe-1")
    ctx.recent_query = "capital of France"

    desc = pol.describe(snap, mode=pol.QUICK, context=ctx, query="what is the capital of France")
    assert "Paris is the capital of France" in desc
    assert "Toolbar navigation" not in desc


# ============================================================================
# 3. Password Manager ("password puter") & DPAPI Keystroke Injection
# ============================================================================

def test_password_grammar_intents():
    """Grammar parsing for save, enter, and forget password intents."""
    i1 = parse("save my password for github as S3cur3T0k3n!")
    assert i1.kind == Kind.SAVE_PASSWORD
    assert i1.get("app") == "github"
    assert i1.get("password") == "S3cur3T0k3n!"

    i2 = parse("save password is mySuperPass")
    assert i2.kind == Kind.SAVE_PASSWORD
    assert i2.get("password") == "mySuperPass"

    i3 = parse("paste password")
    assert i3.kind == Kind.ENTER_PASSWORD

    i4 = parse("enter my password for google")
    assert i4.kind == Kind.ENTER_PASSWORD
    assert i4.get("app") == "google"

    i5 = parse("forget my password for github")
    assert i5.kind == Kind.FORGET_PASSWORD
    assert i5.get("app") == "github"


def test_password_save_enter_and_forget_in_session():
    """Session securely stores password via DPAPI and types it without speaking the secret."""
    spoken: list[str] = []
    s = Session(speak=spoken.append, db_path=":memory:")
    s.executor.input.type_text = MagicMock()

    secret_val = "SuperP@ssw0rd99!"

    # 1. Save password
    s.handle(f"save my password for portal as {secret_val}")
    # Plaintext password must NEVER appear in spoken audio
    assert not any(secret_val in msg for msg in spoken)
    assert any("securely saved your password for portal" in msg for msg in spoken)

    # Verify DPAPI store
    stored = get_secret("pwd:portal")
    assert stored == secret_val

    # 2. Enter / paste password
    spoken.clear()
    s.handle("enter password for portal")
    # Keystroke typing called
    s.executor.input.type_text.assert_called_once_with(secret_val)
    # Speech confirms action without uttering secret
    assert any("Password entered." in msg for msg in spoken)
    assert not any(secret_val in msg for msg in spoken)

    # 3. Forget password
    spoken.clear()
    s.handle("forget my password for portal")
    assert any("removed your saved password for portal" in msg for msg in spoken)
    assert get_secret("pwd:portal") is None

    s.close()


def test_password_shielded_in_delta_and_describe():
    """Password/secret fields are masked and never spoken aloud by delta or describe."""
    pwd_el_old = UIElement(
        1,
        "Master Password",
        "Edit",
        (10, 10, 200, 30),
        value="",
        states={"is_password": True},
    )
    pwd_el_new = UIElement(
        1,
        "Master Password",
        "Edit",
        (10, 10, 200, 30),
        value="Secret123!",
        states={"is_password": True},
    )
    snap_old = ScreenSnapshot(1, "vault.exe", "Vault Login", elements=[pwd_el_old], focus=pwd_el_old)
    snap_new = ScreenSnapshot(2, "vault.exe", "Vault Login", elements=[pwd_el_new], focus=pwd_el_new)

    # 1. Delta engine test: must NOT contain "Secret123!"
    diffs = delta_mod.diff(snap_old, snap_new)
    diff_text = " ".join(diffs)
    assert "Secret123!" not in diff_text
    assert "Password text updated." in diff_text

    # 2. Describe test: must NOT speak the password value
    desc = pol.describe(snap_new, mode=pol.DETAILED)
    assert "Secret123!" not in desc
    assert "[password protected]" in desc or "Master Password" in desc


# ============================================================================
# 4. Multi-Step Execution Longevity (60 Steps at a time)
# ============================================================================

def test_session_60_steps_execution(monkeypatch):
    """Session can execute a 60-step sequence with milestone tracking and concise plan speech."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    spoken: list[str] = []
    s = Session(speak=spoken.append, db_path=":memory:")

    executed_steps: list[str] = []
    # Mock handle to track all steps executed
    def _mock_handle(utterance):
        executed_steps.append(utterance)
        return []

    s.handle = _mock_handle

    steps_60 = [f"action step number {i}" for i in range(1, 61)]
    res = s.run_steps(steps_60)

    # 1. Total steps executed must be 60
    assert len(executed_steps) == 60
    assert executed_steps[0] == "action step number 1"
    assert executed_steps[-1] == "action step number 60"

    # 2. Plan speech announcement must NOT be a gigantic recitation of all 60 steps
    # It must say: "Starting 60 steps, beginning with action step number 1."
    assert any("Starting 60 steps, beginning with action step number 1." in msg for msg in spoken)

    # 3. Milestones reported every 10 steps
    assert any("Step 10 of 60 complete." in msg for msg in spoken)
    assert any("Step 20 of 60 complete." in msg for msg in spoken)
    assert any("Step 30 of 60 complete." in msg for msg in spoken)
    assert any("Step 40 of 60 complete." in msg for msg in spoken)
    assert any("Step 50 of 60 complete." in msg for msg in spoken)

    # 4. Final completion announcement ("All 60 steps done.")
    assert any("All 60 steps done." in msg for msg in spoken)

    s.close()
