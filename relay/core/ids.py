"""Unique identifiers for sessions, tasks and actions.

Every session, task and action carries a stable, unique id so the event bus,
action journal and crash-recovery can correlate them unambiguously. Ids are
sortable-ish (time prefix) to aid log reading, but correlation relies on the
random suffix, not the time.
"""

from __future__ import annotations

import time
import uuid


def _new_id(prefix: str) -> str:
    # milliseconds base36-ish time prefix for rough ordering, + random suffix.
    ms = int(time.time() * 1000)
    return f"{prefix}_{ms:x}_{uuid.uuid4().hex[:8]}"


def new_session_id() -> str:
    return _new_id("ses")


def new_task_id() -> str:
    return _new_id("task")


def new_action_id() -> str:
    return _new_id("act")
