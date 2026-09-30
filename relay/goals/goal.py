"""Persistent Goal Manager for multi-step, multi-application user workflows.

Tracks complex tasks across applications, crashes, and restarts with bounded steps,
checkpoints, undo records, and mode transitions.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from relay.diagnostics import get_logger

log = get_logger("goals")

MODES = (
    "Quick",
    "Guided",
    "Learning",
    "Assignment",
    "Writing",
    "Coding",
    "Explore",
    "Privacy",
    "Focus",
    "Emergency",
)


@dataclass
class GoalStep:
    step_id: str
    description: str
    state: str = "pending"  # pending | current | completed | skipped | blocked | failed
    action_kind: str = ""
    payload: dict = field(default_factory=dict)
    evidence: str = ""
    undo_info: dict = field(default_factory=dict)


@dataclass
class Goal:
    goal_id: str
    title: str
    mode: str = "Guided"
    steps: list[GoalStep] = field(default_factory=list)
    current_step_index: int = 0
    context: dict = field(default_factory=dict)
    checkpoints: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "active"  # active | paused | completed | failed | cancelled

    @property
    def current_step(self) -> Optional[GoalStep]:
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.steps if s.state == "completed")

    @property
    def remaining_count(self) -> int:
        return sum(1 for s in self.steps if s.state in ("pending", "current", "blocked"))

    def spoken_status(self) -> str:
        total = len(self.steps)
        done = self.completed_count
        curr = self.current_step
        curr_desc = f" Currently: {curr.description}." if curr else ""
        return (
            f"Goal {self.title} in {self.mode} mode: {done} of {total} steps completed."
            f"{curr_desc}"
        )


class GoalStore:
    """SQLite-backed goal persistence."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._init_db()

    def _init_db(self) -> None:
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS goals (
                    goal_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step_index INTEGER NOT NULL,
                    steps_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    checkpoints_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

    def save_goal(self, goal: Goal) -> None:
        goal.updated_at = time.time()
        steps_data = [asdict(s) for s in goal.steps]
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO goals (
                    goal_id, title, mode, status, current_step_index,
                    steps_json, context_json, checkpoints_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(goal_id) DO UPDATE SET
                    title=excluded.title,
                    mode=excluded.mode,
                    status=excluded.status,
                    current_step_index=excluded.current_step_index,
                    steps_json=excluded.steps_json,
                    context_json=excluded.context_json,
                    checkpoints_json=excluded.checkpoints_json,
                    updated_at=excluded.updated_at
                """,
                (
                    goal.goal_id,
                    goal.title,
                    goal.mode,
                    goal.status,
                    goal.current_step_index,
                    json.dumps(steps_data),
                    json.dumps(goal.context),
                    json.dumps(goal.checkpoints),
                    goal.created_at,
                    goal.updated_at,
                ),
            )

    def load_goal(self, goal_id: str) -> Optional[Goal]:
        cur = self.conn.execute(
            """
            SELECT goal_id, title, mode, status, current_step_index,
                   steps_json, context_json, checkpoints_json, created_at, updated_at
            FROM goals WHERE goal_id = ?
            """,
            (goal_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        steps = [GoalStep(**s) for s in json.loads(row[5])]
        return Goal(
            goal_id=row[0],
            title=row[1],
            mode=row[2],
            status=row[3],
            current_step_index=row[4],
            steps=steps,
            context=json.loads(row[6]),
            checkpoints=json.loads(row[7]),
            created_at=row[8],
            updated_at=row[9],
        )

    def load_active_goal(self) -> Optional[Goal]:
        cur = self.conn.execute(
            """
            SELECT goal_id FROM goals
            WHERE status = 'active'
            ORDER BY updated_at DESC LIMIT 1
            """
        )
        row = cur.fetchone()
        return self.load_goal(row[0]) if row else None


class GoalManager:
    """Manages active user goals, multi-app workflows, and checkpoints."""

    def __init__(self, conn: sqlite3.Connection, bus: Any = None) -> None:
        self.store = GoalStore(conn)
        self.bus = bus
        self.active_goal: Optional[Goal] = self.store.load_active_goal()

    def start_goal(
        self,
        title: str,
        steps: list[str],
        mode: str = "Guided",
        context: Optional[dict] = None,
    ) -> Goal:
        import uuid

        gid = f"goal_{uuid.uuid4().hex[:8]}"
        goal_steps = [
            GoalStep(step_id=f"{gid}_s{idx}", description=desc)
            for idx, desc in enumerate(steps, 1)
        ]
        if goal_steps:
            goal_steps[0].state = "current"
        goal = Goal(
            goal_id=gid,
            title=title,
            mode=mode if mode in MODES else "Guided",
            steps=goal_steps,
            context=context or {},
        )
        self.active_goal = goal
        self.store.save_goal(goal)
        if self.bus is not None:
            self.bus.emit("goal.started", goal_id=gid, title=title, mode=mode)
        return goal

    def pause_goal(self) -> Optional[Goal]:
        if not self.active_goal:
            return None
        self.active_goal.status = "paused"
        self.store.save_goal(self.active_goal)
        if self.bus is not None:
            self.bus.emit("goal.paused", goal_id=self.active_goal.goal_id)
        return self.active_goal

    def resume_goal(self) -> Optional[Goal]:
        if not self.active_goal:
            self.active_goal = self.store.load_active_goal()
        if self.active_goal:
            self.active_goal.status = "active"
            self.store.save_goal(self.active_goal)
            if self.bus is not None:
                self.bus.emit("goal.resumed", goal_id=self.active_goal.goal_id)
        return self.active_goal

    def advance_step(self, evidence: str = "") -> Optional[Goal]:
        if not self.active_goal:
            return None
        curr = self.active_goal.current_step
        if curr:
            curr.state = "completed"
            curr.evidence = evidence
        self.active_goal.current_step_index += 1
        nxt = self.active_goal.current_step
        if nxt:
            nxt.state = "current"
        else:
            self.active_goal.status = "completed"
        self.store.save_goal(self.active_goal)
        if self.bus is not None:
            self.bus.emit("goal.step_advanced", goal_id=self.active_goal.goal_id)
        return self.active_goal

    def create_checkpoint(self, note: str) -> None:
        if not self.active_goal:
            return
        checkpoint = {
            "timestamp": time.time(),
            "note": note,
            "step_index": self.active_goal.current_step_index,
            "context": dict(self.active_goal.context),
        }
        self.active_goal.checkpoints.append(checkpoint)
        self.store.save_goal(self.active_goal)
