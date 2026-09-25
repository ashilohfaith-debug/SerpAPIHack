"""Spoken notes — "take a note: buy milk", "read my notes".

Notes are the user's own words, stored locally in the RELAY database. Like every
other memory layer, anything that looks like a password, OTP or PIN is refused so a
credential is never written to disk by accident.
"""

from __future__ import annotations

import sqlite3
import time

from relay.memory.store import looks_sensitive


class NotesStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, text: str) -> bool:
        text = (text or "").strip()
        if not text or looks_sensitive(text):
            return False
        self.conn.execute("INSERT INTO notes (text, created) VALUES (?, ?)", (text, time.time()))
        return True

    def list(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, text, created FROM notes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]      # oldest first when read aloud

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) c FROM notes").fetchone()["c"]

    def delete_last(self) -> bool:
        row = self.conn.execute("SELECT id FROM notes ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return False
        self.conn.execute("DELETE FROM notes WHERE id=?", (row["id"],))
        return True

    def delete_all(self) -> int:
        return self.conn.execute("DELETE FROM notes").rowcount

    def spoken(self, limit: int = 20) -> str:
        notes = self.list(limit)
        if not notes:
            return "You don't have any notes yet. Say, take a note, then what to write."
        n = self.count()
        head = f"You have {n} note{'s' if n != 1 else ''}."
        body = " ".join(f"Note {i}: {r['text'].rstrip('.')}." for i, r in enumerate(notes, 1))
        return f"{head} {body}"
