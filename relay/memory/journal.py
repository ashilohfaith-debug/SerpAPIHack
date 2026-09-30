"""Append-only action journal and task checkpoints.

Every important execution transition is appended here durably, so that after a
crash RELAY can tell what was completed, what was pending and — critically — what
was UNCERTAIN, and never auto-repeat an uncertain irreversible action. The journal
is append-only: rows are inserted, never updated, so history cannot be silently
rewritten. A later "executed" and its later "verified" are separate rows sharing
an action_id.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum


class ExecState(str, Enum):
    PROPOSED = "proposed"
    EXECUTED = "executed"  # input sent — NOT proof of success
    VERIFIED = "verified"  # re-observed and confirmed
    UNCERTAIN = "uncertain"  # outcome could not be confirmed
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ActionRecord:
    task_id: str
    action_id: str
    execution_state: ExecState
    target_identity: str = ""
    proposed_action: str = ""
    permission_decision: str = ""
    verification_result: str = ""
    ts: float = 0.0


class ActionJournal:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, rec: ActionRecord) -> int:
        """Durably append one journal row. Returns its sequence number."""
        ts = rec.ts or time.time()
        cur = self._conn.execute(
            """INSERT INTO action_journal
               (task_id, action_id, target_identity, proposed_action,
                permission_decision, execution_state, verification_result, ts)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                rec.task_id,
                rec.action_id,
                rec.target_identity,
                rec.proposed_action,
                rec.permission_decision,
                rec.execution_state.value,
                rec.verification_result,
                ts,
            ),
        )
        return int(cur.lastrowid)

    def for_task(self, task_id: str) -> list[ActionRecord]:
        rows = self._conn.execute(
            "SELECT * FROM action_journal WHERE task_id=? ORDER BY seq", (task_id,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def uncertain_actions(self, task_id: str) -> list[str]:
        """Action ids whose LAST recorded state is UNCERTAIN (need inspection,
        never blind replay)."""
        latest: dict[str, ExecState] = {}
        for rec in self.for_task(task_id):
            latest[rec.action_id] = rec.execution_state
        return [aid for aid, st in latest.items() if st == ExecState.UNCERTAIN]

    def save_checkpoint(self, task_id: str, goal: str, state: str, data: dict) -> None:
        self._conn.execute(
            """INSERT INTO task_checkpoints (task_id, goal, state, data_json, ts)
               VALUES (?,?,?,?,?)""",
            (task_id, goal, state, json.dumps(data, ensure_ascii=False), time.time()),
        )

    def latest_checkpoint(self, task_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM task_checkpoints WHERE task_id=? ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row["task_id"],
            "goal": row["goal"],
            "state": row["state"],
            "data": json.loads(row["data_json"]),
            "ts": row["ts"],
        }

    @staticmethod
    def _row(r: sqlite3.Row) -> ActionRecord:
        return ActionRecord(
            task_id=r["task_id"],
            action_id=r["action_id"],
            execution_state=ExecState(r["execution_state"]),
            target_identity=r["target_identity"],
            proposed_action=r["proposed_action"],
            permission_decision=r["permission_decision"],
            verification_result=r["verification_result"],
            ts=r["ts"],
        )
