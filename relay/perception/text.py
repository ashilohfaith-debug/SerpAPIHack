"""Reading content through UI Automation: documents, web pages, links, headings.

Runs ON the UIA worker thread (call through ``UIAWorker.run``). Uses native UIA
searches (IUIAutomationElement.FindAll) rather than walking the tree in Python — a
web page is thousands of nodes and 20-40 levels deep, and a native search finds its
617 links in about a third of a second where a Python walk takes six. Text comes from
the TextPattern of the visible document (a web page, Word, Notepad), which reads a
whole page in well under a second. Nothing here clicks or types.
"""

from __future__ import annotations

from dataclasses import dataclass

TS_DESCENDANTS = 4
TS_SUBTREE = 7
IGNORE_CASE = 1
MAX_TEXT = 60000


def _ua():
    from uiautomation.uiautomation import _AutomationClient
    return _AutomationClient.instance().IUIAutomation


def _fg():
    import uiautomation as auto
    return auto.GetForegroundControl()


def _find_all(elem, prop, value, scope=TS_DESCENDANTS):
    ua = _ua()
    arr = elem.FindAll(scope, ua.CreatePropertyCondition(prop, value))
    return [arr.GetElement(i) for i in range(arr.Length)]


def _area(e) -> int:
    try:
        r = e.CurrentBoundingRectangle
        return max(0, r.right - r.left) * max(0, r.bottom - r.top)
    except Exception:
        return 0


def _bbox(e) -> tuple[int, int, int, int]:
    try:
        r = e.CurrentBoundingRectangle
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        return (0, 0, 0, 0)


def active_document():
    """The largest visible Document in the foreground window (the web page / the
    document being edited), or None."""
    import uiautomation as auto
    fg = _fg()
    if fg is None:
        return None
    docs = []
    for e in _find_all(fg.Element, auto.PropertyId.ControlTypeProperty,
                       auto.ControlType.DocumentControl):
        try:
            if not e.CurrentIsOffscreen and _area(e) > 0:
                docs.append(e)
        except Exception:
            continue
    return max(docs, key=_area) if docs else None


def _text_of(elem, max_chars: int) -> str:
    import uiautomation as auto
    try:
        ctrl = auto.Control.CreateControlFromElement(elem)
        tp = ctrl.GetTextPattern()
        if tp is not None:
            return (tp.DocumentRange.GetText(max_chars) or "").strip()
    except Exception:
        pass
    return ""


def document_text(max_chars: int = MAX_TEXT) -> tuple[str, str]:
    """(title, text) of what the user is reading: the visible document's full text,
    else the focused text control, else the focused field's value."""
    import uiautomation as auto

    from relay.safety import is_protected_field
    fg = _fg()
    title = ""
    try:
        title = (fg.Name or "").strip() if fg is not None else ""
    except Exception:
        pass
    doc = active_document()
    if doc is not None:
        text = _text_of(doc, max_chars)
        if text:
            return title, text
    try:
        fc = auto.GetFocusedControl()
        if fc is not None:
            role = (fc.ControlTypeName or "").replace("Control", "")
            if is_protected_field(role=role, name=fc.Name or ""):
                return title, ""
            tp = fc.GetTextPattern()
            if tp is not None:
                text = (tp.DocumentRange.GetText(max_chars) or "").strip()
                if text:
                    return title, text
            vp = fc.GetValuePattern()
            if vp is not None and (vp.Value or "").strip():
                return title, vp.Value.strip()[:max_chars]
    except Exception:
        pass
    return title, ""


def visible_text(max_items: int = 300) -> str:
    """Fallback reading for apps without a document: the names of the visible text
    labels in tree (reading) order, de-duplicated."""
    import uiautomation as auto
    fg = _fg()
    if fg is None:
        return ""
    out: list[str] = []
    seen: set[str] = set()
    for e in _find_all(fg.Element, auto.PropertyId.ControlTypeProperty,
                       auto.ControlType.TextControl)[: max_items * 2]:
        try:
            if e.CurrentIsOffscreen:
                continue
            name = (e.CurrentName or "").strip()
        except Exception:
            continue
        if name and name not in seen:
            seen.add(name)
            out.append(name)
        if len(out) >= max_items:
            break
    return "\n".join(out)


@dataclass(frozen=True)
class Item:
    name: str
    role: str                     # "link" | "heading" | "button" | ...
    bbox: tuple[int, int, int, int]
    level: int = 0                # heading level when known


def links(limit: int = 400) -> list[Item]:
    import uiautomation as auto
    root = active_document() or (_fg().Element if _fg() is not None else None)
    if root is None:
        return []
    out: list[Item] = []
    for e in _find_all(root, auto.PropertyId.ControlTypeProperty,
                       auto.ControlType.HyperlinkControl):
        try:
            name = " ".join((e.CurrentName or "").split())
        except Exception:
            continue
        if name:
            out.append(Item(name, "link", _bbox(e)))
        if len(out) >= limit:
            break
    return out


def headings(limit: int = 200) -> list[Item]:
    import uiautomation as auto
    root = active_document() or (_fg().Element if _fg() is not None else None)
    if root is None:
        return []
    out: list[Item] = []
    for e in _find_all(root, auto.PropertyId.ControlTypeProperty,
                       auto.ControlType.TextControl):
        try:
            lct = (e.CurrentLocalizedControlType or "").lower()
            if not lct.startswith("heading"):
                continue
            name = " ".join((e.CurrentName or "").split())
        except Exception:
            continue
        digits = "".join(ch for ch in lct if ch.isdigit())
        if name:
            out.append(Item(name, "heading", _bbox(e), int(digits) if digits else 0))
        if len(out) >= limit:
            break
    return out


_ROLE_TYPES = ("ButtonControl", "HyperlinkControl", "MenuItemControl", "ListItemControl",
               "TabItemControl", "CheckBoxControl", "RadioButtonControl", "TreeItemControl",
               "SplitButtonControl", "EditControl", "ComboBoxControl")


def find_named(target: str, limit: int = 12) -> list[Item]:
    """Deep search of the foreground window for interactive controls whose name
    contains ``target`` (exact matches first). Used when a control isn't in the
    shallow snapshot — typically a link or button deep inside a web page."""
    import uiautomation as auto
    fg = _fg()
    if fg is None:
        return []
    want = " ".join(target.lower().split())
    exact: list[Item] = []
    partial: list[Item] = []
    for ct_name in _ROLE_TYPES:
        ct = getattr(auto.ControlType, ct_name)
        for e in _find_all(fg.Element, auto.PropertyId.ControlTypeProperty, ct):
            try:
                name = " ".join((e.CurrentName or "").split())
            except Exception:
                continue
            if not name:
                continue
            low = name.lower()
            item = Item(name, ct_name.replace("Control", ""), _bbox(e))
            if low == want:
                exact.append(item)
            elif want in low:
                partial.append(item)
        if len(exact) >= limit:
            break
    return (exact + partial)[:limit]
