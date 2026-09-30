"""Restart reconciliation — pick up safely after a crash or restart.

Reads the durable action journal and the latest checkpoint for a task and reports
what was completed, what was still pending, and — most importantly — what was
UNCERTAIN. RELAY never auto-repeats an uncertain irreversible action (an email that
may have sent, a file that may have saved); it reports the uncertainty and, in the
live flow, re-observes the world before doing anything else. This module only
reports; it performs no actions and restores no stale UIA objects.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from relay.memory.journal import ActionJournal, ExecState


@dataclass
class ReconcileReport:
    task_id: str
    goal: str
    completed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    spoken: str = ""


def latest_task_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT task_id FROM action_journal ORDER BY ts DESC LIMIT 1").fetchone()
    if row:
        return row["task_id"]
    row = conn.execute("SELECT task_id FROM task_checkpoints ORDER BY ts DESC LIMIT 1").fetchone()
    return row["task_id"] if row else None


def reconcile(journal: ActionJournal, task_id: str) -> ReconcileReport:
    cp = journal.latest_checkpoint(task_id)
    goal = cp["goal"] if cp else ""

    latest: dict[str, ExecState] = {}
    order: list[str] = []
    labels: dict[str, str] = {}
    for rec in journal.for_task(task_id):
        if rec.action_id not in latest:
            order.append(rec.action_id)
        latest[rec.action_id] = rec.execution_state
        if rec.proposed_action:
            labels[rec.action_id] = rec.proposed_action

    def names(state):
        return [labels.get(a, a) for a in order if latest[a] == state]

    completed = names(ExecState.VERIFIED)
    uncertain = names(ExecState.UNCERTAIN)
    pending = [
        labels.get(a, a) for a in order if latest[a] in (ExecState.PROPOSED, ExecState.EXECUTED)
    ]
    failed = names(ExecState.FAILED)

    bits = []
    if goal:
        bits.append(f"Last time we were working on: {goal}.")
    if completed:
        bits.append(f"I completed and verified {len(completed)} step(s).")
    if uncertain:
        bits.append(
            f"{len(uncertain)} step(s) were uncertain — I won't repeat those "
            "on my own; I'll check the current state first."
        )
    if pending:
        bits.append(f"{len(pending)} step(s) were still pending.")
    if failed:
        bits.append(f"{len(failed)} step(s) had failed.")
    if not bits:
        bits.append("I don't have a record of a task in progress.")

    return ReconcileReport(task_id, goal, completed, pending, uncertain, failed, " ".join(bits))
