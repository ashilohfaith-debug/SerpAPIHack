"""Narration policy — how much to say, and what to prioritise.

Four modes (spec §9):
  quick     essentials only (the default) — actions + task-relevant changes, briefly
  detailed  fuller descriptions, including the available controls
  guided    detailed + a next-step hint, for unfamiliar apps
  quiet     only critical errors, confirmations, and things you explicitly asked for

Announcement priority orders what matters when several things happen: critical
errors first, then required confirmations, then task changes, focus, requested
content, and background last. RELAY's OWN actions are always announced (the
transparency contract); modes tune the surrounding description and whether
background changes are spoken.
"""

from __future__ import annotations

from relay.perception.semantic import ScreenSnapshot

QUICK, DETAILED, GUIDED, QUIET = "quick", "detailed", "guided", "quiet"
MODES = (QUICK, DETAILED, GUIDED, QUIET)


class Priority:
    CRITICAL = 0  # errors that block the user
    CONFIRMATION = 1  # a confirmation is required
    TASK = 2  # a change relevant to the current task
    FOCUS = 3  # focus moved
    REQUESTED = 4  # the user asked for this
    BACKGROUND = 5  # unrelated background activity


def should_speak(priority: int, mode: str) -> bool:
    if mode == QUIET:
        return priority in (Priority.CRITICAL, Priority.CONFIRMATION, Priority.REQUESTED)
    if mode == QUICK:
        return priority <= Priority.REQUESTED  # everything except pure background
    return True  # detailed / guided: say it all


def describe(snap: ScreenSnapshot | None, mode: str, context=None, query: str = "") -> str:
    """Describe the screen with meaningful, task-relevant content first.
    Filters out window-frame chrome (Minimize/Maximize/Close) and boilerplate,
    reading the actual content, answers, or active fields relevant to the conversation.
    """
    if snap is None:
        return "I can't read the screen right now."
    if not snap.uia_available:
        return snap.summary()

    from relay.narration.delta import meaningful
    from relay.safety import is_protected_field

    app = snap.foreground_app or ""
    title = snap.foreground_title or ""
    if app and title and title != app:
        parts = [f"In {app}, window '{title}'."]
    elif app:
        parts = [f"In {app}."]
    elif title:
        parts = [f"In {title}."]
    else:
        parts = []

    if snap.dialogs:
        d = snap.dialogs[0]
        btns = f" Options: {', '.join(d.buttons)}." if d.buttons else ""
        return f"A dialog is open: {d.title}.{btns}"

    items = meaningful(snap.elements)

    # Keywords from query or context
    keywords = []
    if query:
        keywords.extend(query.lower().split())
    if context and hasattr(context, "recent_query") and context.recent_query:
        keywords.extend(context.recent_query.lower().split())
    if context and hasattr(context, "goal") and context.goal:
        keywords.extend(context.goal.lower().split())
    stopwords = {"the", "a", "an", "and", "or", "to", "in", "on", "for", "with", "what", "whats", "describe", "screen", "my"}
    keywords = [w for w in keywords if len(w) > 2 and w not in stopwords]

    matched_content = []
    content_items = []
    action_items = []

    for e in items:
        name = (e.name or "").strip()
        val = (e.value or "").strip()
        is_pwd = is_protected_field(
            role=e.role,
            name=name,
            is_password_field=bool(e.states.get("is_password") or e.states.get("protected")),
        )
        if is_pwd:
            val = "[protected]"
        text = f"{name}: {val}" if name and val and name != val else (val or name)
        if not text:
            continue
        low = text.lower()
        if keywords and any(kw in low for kw in keywords):
            matched_content.append(text)
        elif e.role in ("Document", "Text", "ListItem") and len(text) > 3:
            content_items.append(text)
        elif e.role in ("Button", "Hyperlink", "MenuItem", "Edit"):
            desc = f"{e.role} '{name}'" if name else e.role
            if val and not is_pwd:
                desc += f" ('{val}')"
            action_items.append(desc)

    if matched_content:
        # Perplexity / search match: read the answer/content matching the user query
        parts.append(f"Content: {matched_content[0]}.")
        if len(matched_content) > 1:
            parts.append(f"Also: {matched_content[1]}.")
    elif content_items:
        parts.append(f"Content: {content_items[0]}.")
        if len(content_items) > 1 and mode in (DETAILED, GUIDED):
            parts.append(f"{content_items[1]}.")
    elif snap.focus and (snap.focus.value or snap.focus.name):
        f = snap.focus
        is_pwd = is_protected_field(
            role=f.role,
            name=f.name or "",
            is_password_field=bool(f.states.get("is_password") or f.states.get("protected")),
        )
        f_val = "[password protected]" if is_pwd else (f.value or f.name)
        parts.append(
            f"Focus is on {f.role} '{f.name}': {f_val}."
            if f.name and f.value and not is_pwd
            else f"Focus is on {f.role} '{f_val}'."
        )

    if mode in (DETAILED, GUIDED) and action_items:
        parts.append("Controls include: " + ", ".join(action_items[:8]) + ".")

    if mode == GUIDED:
        if snap.focus and snap.focus.role in ("Edit", "Document"):
            parts.append("You can start typing, or say read the page.")
        elif action_items and items:
            parts.append(f"Say click {items[0].name} to choose it.")

    return " ".join(parts)


def spell(text: str) -> str:
    """Spell out text, letter by letter, for unambiguous reading (names, codes)."""
    if not text:
        return "There's nothing to spell."
    out = []
    for ch in text.strip():
        if ch == " ":
            out.append("space")
        else:
            out.append(ch.upper())
    return ", ".join(out)
