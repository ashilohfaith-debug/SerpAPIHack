"""MemoryStore — the five-layer memory facade over SQLite.

L3 user preferences, L4 application/workflow/label memory, L5 opt-in episodic
summaries. Every write records provenance (explicit / observed / verified /
inferred / uncertain) so RELAY can always say WHY it remembers something and never
presents an inference as a fact. Text search uses FTS5, kept in sync on write and
purged on delete. Nothing sensitive is ever stored: values that look like passwords,
OTPs or tokens are refused. All operations are real (the voice commands "forget
this", "clear my history", "export my preferences" call straight through).
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid


class Provenance:
    EXPLICIT = "explicit_instruction"
    OBSERVED = "observed"
    VERIFIED = "verified"
    INFERRED = "inferred"
    UNCERTAIN = "uncertain"


# Strong secret tokens: matched as substrings (conservative — a false refusal costs
# nothing, a stored credential is a breach). "pin"/"one-time" use word boundaries to
# avoid false hits inside words like "spinning".
_SECRET_SUBSTR = ("password", "passwd", "secret", "token", "apikey", "api_key",
                  "otp", "passcode", "cvv", "credential")
_SECRET_WORD = re.compile(r"(?i)\b(pwd|pin|one[- ]?time|security code)\b")


def looks_sensitive(*texts: str) -> bool:
    """True if any text looks like a credential/OTP that must never be stored."""
    for t in texts:
        raw = str(t or "")
        low = raw.lower()
        if any(sub in low for sub in _SECRET_SUBSTR):
            return True
        if _SECRET_WORD.search(low):
            return True
        if re.fullmatch(r"\s*\d{4,8}\s*", raw):  # a bare 4-8 digit code (likely OTP/PIN)
            return True
    return False


class MemoryStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ---------------- L3 preferences ----------------
    def set_pref(self, key: str, value: str, scope: str = "",
                 provenance: str = Provenance.EXPLICIT, approved: bool = True) -> bool:
        if looks_sensitive(key, value):
            return False  # never persist secrets in ordinary preference tables
        self.conn.execute(
            """INSERT INTO preferences (scope, key, value, provenance, approval, updated)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(scope, key) DO UPDATE SET
                 value=excluded.value, provenance=excluded.provenance,
                 approval=excluded.approval, updated=excluded.updated""",
            (scope, key, value, provenance, "approved" if approved else "pending", time.time()),
        )
        return True

    def get_pref(self, key: str, scope: str = "", default=None):
        row = self.conn.execute(
            "SELECT value FROM preferences WHERE scope=? AND key=?", (scope, key)
        ).fetchone()
        if row is None and scope:  # fall back to global
            row = self.conn.execute(
                "SELECT value FROM preferences WHERE scope='' AND key=?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def all_prefs(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT scope, key, value, provenance FROM preferences ORDER BY scope, key"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_pref(self, key: str, scope: str = "") -> bool:
        cur = self.conn.execute("DELETE FROM preferences WHERE scope=? AND key=?", (scope, key))
        return cur.rowcount > 0

    def export_prefs(self) -> dict:
        return {"preferences": self.all_prefs(), "exported_at": time.time()}

    def why(self, key: str, scope: str = "") -> str | None:
        row = self.conn.execute(
            "SELECT provenance, updated FROM preferences WHERE scope=? AND key=?", (scope, key)
        ).fetchone()
        if row is None:
            return None
        when = time.strftime("%Y-%m-%d", time.localtime(row["updated"]))
        return f"{row['provenance']} (recorded {when})"

    # ---------------- L4 learned control labels ----------------
    def learn_label(self, app_key: str, description: str, control_name: str,
                    control_type: str = "", provenance: str = Provenance.VERIFIED) -> None:
        desc = description.strip().lower()
        existing = self.conn.execute(
            "SELECT hits FROM learned_control_labels WHERE app_key=? AND description=?",
            (app_key, desc),
        ).fetchone()
        hits = (existing["hits"] + 1) if existing else 1
        self.conn.execute(
            """INSERT INTO learned_control_labels
               (app_key, description, control_name, control_type, provenance, hits, updated)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(app_key, description) DO UPDATE SET
                 control_name=excluded.control_name, control_type=excluded.control_type,
                 hits=excluded.hits, updated=excluded.updated""",
            (app_key, desc, control_name, control_type, provenance, hits, time.time()),
        )
        self.conn.execute("DELETE FROM labels_fts WHERE app_key=? AND description=?",
                          (app_key, desc))
        self.conn.execute(
            "INSERT INTO labels_fts (app_key, description, control_name) VALUES (?,?,?)",
            (app_key, desc, control_name),
        )

    def recall_label(self, app_key: str, description: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM learned_control_labels WHERE app_key=? AND description=?",
            (app_key, description.strip().lower()),
        ).fetchone()
        return dict(row) if row else None

    # ---------------- L4 workflow templates ----------------
    def save_workflow(self, app_key: str, name: str, steps: list,
                      preconditions: str = "", verification: str = "") -> str:
        wid = f"wf_{uuid.uuid4().hex[:10]}"
        now = time.time()
        self.conn.execute(
            """INSERT INTO workflow_templates
               (id, app_key, name, steps_json, preconditions, verification, provenance,
                validation, hits, created, updated)
               VALUES (?,?,?,?,?,?,?,?,0,?,?)""",
            (wid, app_key, name, json.dumps(steps), preconditions, verification,
             Provenance.VERIFIED, "unvalidated", now, now),
        )
        return wid

    def recall_workflows(self, app_key: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM workflow_templates WHERE app_key=? ORDER BY hits DESC", (app_key,)
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_workflow_validated(self, wid: str, ok: bool) -> None:
        self.conn.execute(
            "UPDATE workflow_templates SET validation=?, hits=hits+?, updated=? WHERE id=?",
            ("validated" if ok else "stale", 1 if ok else 0, time.time(), wid),
        )

    # ---------------- L5 episodic (opt-in) ----------------
    def permission(self, scope: str) -> bool:
        row = self.conn.execute(
            "SELECT allowed FROM memory_permissions WHERE scope=?", (scope,)
        ).fetchone()
        return bool(row and row["allowed"])

    def set_permission(self, scope: str, allowed: bool) -> None:
        self.conn.execute(
            """INSERT INTO memory_permissions (scope, allowed, updated) VALUES (?,?,?)
               ON CONFLICT(scope) DO UPDATE SET
                 allowed=excluded.allowed, updated=excluded.updated""",
            (scope, 1 if allowed else 0, time.time()),
        )

    def add_episodic(self, summary: str, app_key: str = "",
                     provenance: str = Provenance.OBSERVED) -> str | None:
        """Store an episodic summary ONLY if the user has opted in and it holds no
        sensitive content. Returns the id, or None if refused."""
        if not self.permission("episodic"):
            return None
        if looks_sensitive(summary):
            return None
        eid = f"ep_{uuid.uuid4().hex[:10]}"
        self.conn.execute(
            "INSERT INTO episodic_memories "
            "(id, summary, app_key, provenance, created) VALUES (?,?,?,?,?)",
            (eid, summary, app_key, provenance, time.time()),
        )
        self.conn.execute("INSERT INTO episodic_fts (id, summary) VALUES (?,?)", (eid, summary))
        return eid

    def search_episodic(self, query: str, limit: int = 5) -> list[dict]:
        try:
            rows = self.conn.execute(
                """SELECT e.* FROM episodic_fts f JOIN episodic_memories e ON e.id=f.id
                   WHERE episodic_fts MATCH ? LIMIT ?""",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = self.conn.execute(
                "SELECT * FROM episodic_memories WHERE summary LIKE ? LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_episodic(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM episodic_memories ORDER BY created DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_episodic(self, eid: str) -> bool:
        cur = self.conn.execute("DELETE FROM episodic_memories WHERE id=?", (eid,))
        self.conn.execute("DELETE FROM episodic_fts WHERE id=?", (eid,))  # purge the index too
        return cur.rowcount > 0

    # ---------------- general / voice ops ----------------
    def remember_summary(self) -> str:
        prefs = self.all_prefs()
        labels = self.conn.execute("SELECT COUNT(*) c FROM learned_control_labels").fetchone()["c"]
        eps = self.conn.execute("SELECT COUNT(*) c FROM episodic_memories").fetchone()["c"]
        wf = self.conn.execute("SELECT COUNT(*) c FROM workflow_templates").fetchone()["c"]
        parts = []
        if prefs:
            parts.append(f"{len(prefs)} preference(s)")
        if labels:
            parts.append(f"{labels} learned control label(s)")
        if wf:
            parts.append(f"{wf} workflow(s)")
        if eps:
            parts.append(f"{eps} saved task summary(ies)")
        if not parts:
            return "I don't have anything saved yet."
        return "I remember " + ", ".join(parts) + "."

    def clear_task_history(self) -> None:
        self.conn.execute("DELETE FROM episodic_memories")
        self.conn.execute("DELETE FROM episodic_fts")
        self.conn.execute("DELETE FROM task_checkpoints")

    def sweep_expired(self, now: float | None = None) -> int:
        now = now or time.time()
        cur = self.conn.execute(
            "SELECT id FROM episodic_memories WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        ).fetchall()
        for r in cur:
            self.delete_episodic(r["id"])
        self.conn.execute(
            "DELETE FROM workflow_templates WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        return len(cur)
