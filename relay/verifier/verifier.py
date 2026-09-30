"""Action verification — success is OBSERVED, never assumed.

The executor only reports that an action was executed (input was sent). The Verifier
re-observes the world and decides the real outcome:

    VERIFIED   the expected postcondition is observed (window open, text present,
               file on disk, dialog gone, …)
    UNCERTAIN  the action ran but the postcondition could not be confirmed
    FAILED     the action itself failed

An uncertain outcome is surfaced, not upgraded — and an uncertain irreversible
action is never retried (that decision lives in the planner/recovery). Verification
re-observes fresh; it never trusts a prior snapshot.
"""

from __future__ import annotations

import os

from relay.executor.executor import ActionOutcome
from relay.memory.journal import ActionJournal, ActionRecord, ExecState


class Verifier:
    def __init__(self, worker, journal: ActionJournal | None = None) -> None:
        self.worker = worker
        self.journal = journal

    # --- observations of specific postconditions ---
    def app_running(self, exe_name: str) -> bool:
        try:
            import psutil
            target = exe_name.lower()
            for p in psutil.process_iter(["name"]):
                if (p.info.get("name") or "").lower() == target:
                    return True
        except Exception:
            pass
        return False

    def window_present(self, title_substr: str, timeout: float = 3.0) -> bool:
        t = title_substr.lower().replace(".exe", "").strip()
        snap = self.worker.observe(timeout)
        if snap and (t in (snap.foreground_title or "").lower()
                     or any(t in (e.window_title or "").lower() for e in snap.elements)):
            return True
        # also check ALL top-level windows — the app may be open but not foreground
        for wd in self.worker.list_windows():
            if t and (t in wd.get("title", "").lower() or t in wd.get("app", "").lower()):
                return True
        return False

    def focus_value_contains(self, text: str, timeout: float = 3.0) -> bool:
        snap = self.worker.observe(timeout)
        if snap is None:
            return False
        needle = text.strip().lower()
        if snap.focus and needle in (snap.focus.value or "").lower():
            return True
        if needle in (snap.selection or "").lower():
            return True
        return any(needle in (e.value or "").lower() for e in snap.elements)

    def file_exists(self, path: str) -> bool:
        return os.path.exists(path)

    def dialog_present(self, timeout: float = 3.0) -> bool:
        snap = self.worker.observe(timeout)
        return bool(snap and snap.dialogs)

    # --- fold a check into an outcome + journal it ---
    def verify(self, outcome: ActionOutcome, ok: bool, detail: str = "") -> ActionOutcome:
        """Given an EXECUTED outcome and a verification result, produce the final
        VERIFIED/UNCERTAIN outcome and record it in the journal."""
        if outcome.state != ExecState.EXECUTED:
            # FAILED / CANCELLED (blocked, not confirmed, emergency stop) stay exactly
            # that — an action that never ran can't be "verified" by a lucky screen.
            return outcome
        state = ExecState.VERIFIED if ok else ExecState.UNCERTAIN
        result = ActionOutcome(outcome.action_id, state, detail or outcome.detail)
        if self.journal is not None:
            self.journal.append(ActionRecord(
                task_id=outcome.action_id.split(".")[0], action_id=outcome.action_id,
                execution_state=state, verification_result=detail))
        return result
