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
    """Create all RELAY tables if absent. Additive; safe to call repeatedly.

    P2 tables: task_sessions, action_journal (append-only), task_checkpoints.
    P7 five-layer memory: preferences (L3), application_profiles / workflow_templates
    / learned_control_labels (L4), episodic_memories (L5), memory_permissions, plus
    FTS5 mirrors for text search. Every persistent record carries provenance and,
    where relevant, approval status, retention/expiry and validation state.
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

        -- L3: user preferences (scope='' is global, else an app key like 'notepad.exe')
        CREATE TABLE IF NOT EXISTS preferences (
            scope       TEXT NOT NULL DEFAULT '',
            key         TEXT NOT NULL,
            value       TEXT NOT NULL DEFAULT '',
            provenance  TEXT NOT NULL DEFAULT 'explicit_instruction',
            approval    TEXT NOT NULL DEFAULT 'approved',
            updated     REAL NOT NULL,
            PRIMARY KEY (scope, key)
        );

        -- L4: per-application profile blobs (verified navigation facts)
        CREATE TABLE IF NOT EXISTS application_profiles (
            app_key     TEXT PRIMARY KEY,
            data_json   TEXT NOT NULL DEFAULT '{}',
            updated     REAL NOT NULL
        );

        -- L4: reusable verified workflows (proposals, revalidated before use)
        CREATE TABLE IF NOT EXISTS workflow_templates (
            id            TEXT PRIMARY KEY,
            app_key       TEXT NOT NULL DEFAULT '',
            name          TEXT NOT NULL DEFAULT '',
            steps_json    TEXT NOT NULL DEFAULT '[]',
            preconditions TEXT NOT NULL DEFAULT '',
            verification  TEXT NOT NULL DEFAULT '',
            provenance    TEXT NOT NULL DEFAULT 'verified',
            validation    TEXT NOT NULL DEFAULT 'unvalidated',
            hits          INTEGER NOT NULL DEFAULT 0,
            created       REAL NOT NULL,
            updated       REAL NOT NULL,
            expires_at    REAL
        );
        CREATE INDEX IF NOT EXISTS ix_wf_app ON workflow_templates(app_key);

        -- L4: learned description -> control mappings (e.g. "the multiply sign" -> "Multiply")
        CREATE TABLE IF NOT EXISTS learned_control_labels (
            app_key      TEXT NOT NULL DEFAULT '',
            description  TEXT NOT NULL,
            control_name TEXT NOT NULL DEFAULT '',
            control_type TEXT NOT NULL DEFAULT '',
            provenance   TEXT NOT NULL DEFAULT 'verified',
            hits         INTEGER NOT NULL DEFAULT 1,
            updated      REAL NOT NULL,
            PRIMARY KEY (app_key, description)
        );

        -- L5: opt-in episodic summaries (never raw screens/secrets)
        CREATE TABLE IF NOT EXISTS episodic_memories (
            id          TEXT PRIMARY KEY,
            summary     TEXT NOT NULL,
            app_key     TEXT NOT NULL DEFAULT '',
            provenance  TEXT NOT NULL DEFAULT 'observed',
            approval    TEXT NOT NULL DEFAULT 'approved',
            retention   TEXT NOT NULL DEFAULT 'keep',
            created     REAL NOT NULL,
            expires_at  REAL
        );

        -- consent flags for capture (e.g. episodic capture off by default)
        CREATE TABLE IF NOT EXISTS memory_permissions (
            scope    TEXT PRIMARY KEY,
            allowed  INTEGER NOT NULL DEFAULT 0,
            updated  REAL NOT NULL
        );

        -- FTS5 mirrors for text search (kept in sync by MemoryStore)
        CREATE VIRTUAL TABLE IF NOT EXISTS episodic_fts USING fts5(id UNINDEXED, summary);
        CREATE VIRTUAL TABLE IF NOT EXISTS labels_fts
            USING fts5(app_key UNINDEXED, description, control_name);
        """
    )
