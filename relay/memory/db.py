"""SQLite connection + schema bootstrap.

Persistent memory is a single per-user SQLite database (WAL mode for concurrent
read while writing, durable writes for the action journal). This module owns
connection setup and the schema; higher layers (journal now; L3/L4/L5 in P7) add
tables. FTS5 availability is checked so text search can be enabled in P7.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from relay.config import user_data_dir


def default_db_path() -> Path:
    return user_data_dir() / "relay.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the RELAY database with safe pragmas.

    Pass ``":memory:"`` for tests. WAL is skipped for in-memory databases (not
    supported there).
    """
    target = ":memory:" if path == ":memory:" else str(path or default_db_path())
    conn = sqlite3.connect(target, isolation_level=None)  # autocommit; we manage txns
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=FULL;")  # durability for the action journal
    init_schema(conn)
    return conn


def has_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x);")
        conn.execute("DROP TABLE IF EXISTS _fts_probe;")
        return True
    except sqlite3.OperationalError:
        return False


def init_schema(conn: sqlite3.Connection) -> None:
    """Create P2 tables if absent. Additive; safe to call repeatedly.

    Full five-layer schema (preferences, application_profiles, workflow_templates,
    learned_control_labels, episodic_memories, memory_permissions, FTS5) is added
    in P7.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS task_sessions (
            task_id      TEXT PRIMARY KEY,
            goal         TEXT NOT NULL DEFAULT '',
            created      REAL NOT NULL,
            updated      REAL NOT NULL,
            state        TEXT NOT NULL DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS action_journal (
            seq                INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id            TEXT NOT NULL,
            action_id          TEXT NOT NULL,
            target_identity    TEXT NOT NULL DEFAULT '',
            proposed_action    TEXT NOT NULL DEFAULT '',
            permission_decision TEXT NOT NULL DEFAULT '',
            execution_state    TEXT NOT NULL,
            verification_result TEXT NOT NULL DEFAULT '',
            ts                 REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_journal_task ON action_journal(task_id, seq);

        CREATE TABLE IF NOT EXISTS task_checkpoints (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id   TEXT NOT NULL,
            goal      TEXT NOT NULL DEFAULT '',
            state     TEXT NOT NULL DEFAULT '',
            data_json TEXT NOT NULL DEFAULT '{}',
            ts        REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_ckpt_task ON task_checkpoints(task_id, id);
        """
    )
