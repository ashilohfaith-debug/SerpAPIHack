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
# window-frame controls and browser navigation clutter — not worth a blind user's attention
CHROME_NAMES = {
    "minimize",
    "maximize",
    "restore",
    "close",
    "system",
    "system menu bar",
    "application",
    "title bar",
    "restore down",
    "minimise",
    "maximise",
    # Browser and window navigation chrome
    "back",
    "forward",
    "reload",
    "refresh",
    "home",
    "address and search bar",
    "search or enter web address",
    "address bar",
    "new tab",
    "tab",
    "close tab",
    "app bar",
    "navigation",
    "menu bar",
    "extensions",
    "downloads",
    "settings and more",
    "customize and control",
    # Web noise & cookie notices
    "accept cookies",
    "accept all cookies",
    "reject cookies",
    "cookie policy",
    "privacy policy",
    "terms of service",
    "skip to main content",
}
_GENERIC_ROLES = {"Pane", "Window", "Group", "Custom", "TitleBar", "ToolBar", "MenuBar", "ScrollBar", ""}


def meaningful(elements):
    """Elements minus window-frame controls, toolbars, and navigation chrome."""
    filtered = []
    for e in elements:
        name = (e.name or "").strip().lower()
        if not name and e.role in _GENERIC_ROLES:
            continue
        if name in CHROME_NAMES:
            continue
        if any(
            name.startswith(c) and len(name) <= len(c) + 6
            for c in ("close", "minimize", "maximize", "restore")
        ):
            continue
        filtered.append(e)
    return filtered


def _score_element_relevance(el, keywords: list[str]) -> int:
    """Score an element's importance: keyword match -> role priority -> content length."""
    score = 0
    name_low = (el.name or "").lower()
    val_low = (el.value or "").lower()
    for kw in keywords:
        if kw in name_low or kw in val_low:
            score += 10
    if el.role in ("Document", "Text", "Edit"):
        score += 5
    elif el.role in ("ListItem", "Hyperlink"):
        score += 3
    elif el.role in ("Button", "MenuItem"):
        score += 2
    if len(el.name) > 15:
        score += 2
    return score


def diff(
    old: ScreenSnapshot | None,
    new: ScreenSnapshot | None,
    context=None,
    activity: str = "",
) -> list[str]:
    """Human-readable change lines from ``old`` to ``new``. Empty list = nothing
    task-relevant changed. ``old is None`` returns [] (first observation — the
    caller narrates the full screen instead).
    
    Grounds changes in the user's ongoing conversation/activity context, highlighting
    what appeared or changed on screen as a direct consequence of the user's request.
    """
    if new is None:
        return ["I can't read the screen right now."]
    if old is None:
        return []

    changes: list[str] = []
    switched = (old.foreground_app, old.foreground_title) != (
        new.foreground_app,
        new.foreground_title,
    )

    if switched:
        if new.foreground_title:
            changes.append(f"You're now in {new.foreground_title}.")
        else:  # a background/system window took focus: don't read out a process name
            changes.append(
                "No window is in focus right now. Say what windows are open, or switch to one."
            )

    old_dlg = {d.title for d in old.dialogs}
    new_dlg = {d.title for d in new.dialogs}
    for t in sorted(new_dlg - old_dlg):
        dlg = next((d for d in new.dialogs if d.title == t), None)
        btns = f" Options: {', '.join(dlg.buttons)}." if dlg and dlg.buttons else ""
        next_step = f" Say click {dlg.buttons[0]} to proceed." if dlg and dlg.buttons else " Say what you'd like to do."
        changes.append(f"A dialog opened: {t}.{btns}{next_step}")
    for t in sorted(old_dlg - new_dlg):
        changes.append(f"The {t} dialog closed.")

    of = (old.focus.name, old.focus.role) if old.focus else None
    nf = (new.focus.name, new.focus.role) if new.focus else None
    if nf and nf != of:
        name, role = nf
        if name and not (switched and name == new.foreground_title):
            action_hint = ""
            if role in ("Edit", "Document"):
                action_hint = " You can start typing."
            elif role in ("Button", "MenuItem", "TabItem", "Hyperlink"):
                action_hint = f" Say click {name} to select it."
            changes.append(f"Focus is now on {role} '{name}'.{action_hint}")
        elif not name and role not in _GENERIC_ROLES:
            changes.append(f"Focus is now on a {role}.")

    # value change on the focused element (concrete, informative narration)
    if (
        old.focus
        and new.focus
        and old.focus.name == new.focus.name
        and (old.focus.value or "") != (new.focus.value or "")
    ):
        v_new = (new.focus.value or "").strip()
        v_old = (old.focus.value or "").strip()
        from relay.safety import is_protected_field
        is_pwd = is_protected_field(
            role=new.focus.role,
            name=new.focus.name or "",
            is_password_field=bool(new.focus.states.get("is_password") or new.focus.states.get("protected")),
        )
        if is_pwd:
            if not v_new and v_old:
                changes.append("The password was cleared.")
            else:
                changes.append("Password text updated.")
        elif not v_new and v_old:
            changes.append("The text was cleared.")
        elif v_new and len(v_new) <= 60:
            changes.append(f"The text is now '{v_new}'.")
        elif v_new:
            changes.append(f"The text updated: '{v_new[:60]}...'.")
        else:
            changes.append("The text there changed.")

    # Content-level diff: newly appeared or changed elements
    old_meaningful = meaningful(old.elements)
    new_meaningful = meaningful(new.elements)
    old_map = {(e.name.strip().lower(), e.role): e for e in old_meaningful if e.name}
    new_map = {(e.name.strip().lower(), e.role): e for e in new_meaningful if e.name}

    added_keys = [k for k in new_map if k not in old_map]
    if added_keys and not switched:
        # Extract keywords from activity / context to rank new content
        keywords = []
        if activity:
            keywords.extend(activity.lower().split())
        if context and hasattr(context, "goal") and context.goal:
            keywords.extend(context.goal.lower().split())
        stopwords = {"the", "a", "an", "and", "or", "to", "in", "on", "for", "with", "open", "type", "click"}
        keywords = [w for w in keywords if len(w) > 2 and w not in stopwords]

        added_elements = [new_map[k] for k in added_keys]
        added_elements.sort(key=lambda e: _score_element_relevance(e, keywords), reverse=True)

        top_items = [e.name for e in added_elements[:2] if len(e.name.strip()) > 1]
        if top_items:
            prefix = "On screen: "
            if any(_score_element_relevance(e, keywords) >= 10 for e in added_elements[:2]):
                prefix = "Result: "
            changes.append(f"{prefix}{', '.join(top_items)}.")

    return changes
