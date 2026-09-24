"""Change narration — tell the user exactly what changed on screen.

Core to RELAY's transparency contract: after anything RELAY does (and on any task-
relevant screen change), the user must hear the delta versus what they were last
told — a new dialog, focus moving, a control appearing/disappearing, a value
changing, the app switching. This module diffs two snapshots into short spoken
lines. It is bounded (a handful of the most important changes) so it informs
without overwhelming, and it never silently drops a change the user asks about.
"""

from __future__ import annotations

from relay.perception.semantic import ScreenSnapshot

_MAX_LISTED = 3


def diff(old: ScreenSnapshot | None, new: ScreenSnapshot | None) -> list[str]:
    """Human-readable change lines from ``old`` to ``new``. Empty list = nothing
    task-relevant changed. ``old is None`` returns [] (first observation — the
    caller narrates the full screen instead)."""
    if new is None:
        return ["I can't read the screen right now."]
    if old is None:
        return []

    changes: list[str] = []

    if (old.foreground_app, old.foreground_title) != (new.foreground_app, new.foreground_title):
        where = new.foreground_title or new.foreground_app or "a different window"
        changes.append(f"You're now in {where}.")

    old_dlg = {d.title for d in old.dialogs}
    new_dlg = {d.title for d in new.dialogs}
    for t in sorted(new_dlg - old_dlg):
        dlg = next((d for d in new.dialogs if d.title == t), None)
        btns = f" Options: {', '.join(dlg.buttons)}." if dlg and dlg.buttons else ""
        changes.append(f"A dialog opened: {t}.{btns}")
    for t in sorted(old_dlg - new_dlg):
        changes.append(f"The {t} dialog closed.")

    of = (old.focus.name, old.focus.role) if old.focus else None
    nf = (new.focus.name, new.focus.role) if new.focus else None
    if nf and nf != of:
        name, role = nf
        changes.append(f"Focus is now on {role} '{name}'." if name
                       else f"Focus is now on a {role}.")

    old_named = {(e.name, e.role) for e in old.elements if e.name}
    new_named = {(e.name, e.role) for e in new.elements if e.name}
    appeared = [n for (n, _) in sorted(new_named - old_named)][:_MAX_LISTED]
    if appeared:
        changes.append("New: " + ", ".join(appeared) + ".")
    disappeared = [n for (n, _) in sorted(old_named - new_named)][:_MAX_LISTED]
    if disappeared:
        changes.append("No longer there: " + ", ".join(disappeared) + ".")

    # value change on the focused element (e.g. text field content)
    if old.focus and new.focus and old.focus.name == new.focus.name \
            and (old.focus.value or "") != (new.focus.value or ""):
        changes.append("The text there changed.")

    return changes
