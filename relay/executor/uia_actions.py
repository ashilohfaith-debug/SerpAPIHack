"""UIA actions that run ON the UIA worker thread.

These re-locate the target element in the CURRENT foreground tree (never reusing a
cached control object from an old observation) and act through native patterns. Re-
locating here is the "revalidate the target immediately before executing" rule made
concrete: if the element is gone, the action fails cleanly instead of clicking a
stale coordinate.

Re-location uses a native UIA search (FindAll by control type, then name match),
which reaches controls deep inside web pages that a bounded Python walk would miss,
with a tie-break on proximity to the last-known bbox centre so the right control is
picked when several share a name.
"""

from __future__ import annotations

TS_DESCENDANTS = 4


def _ua():
    from uiautomation.uiautomation import _AutomationClient

    return _AutomationClient.instance().IUIAutomation


def _walk_find(name: str, role: str, bbox: tuple[int, int, int, int] | None):
    import uiautomation as auto

    fg = auto.GetForegroundControl()
    if fg is None:
        try:
            fg = auto.GetRootControl()
        except Exception:
            fg = None
    if fg is None:
        return None
    want_name = " ".join((name or "").split()).lower()
    want_role = (role or "").strip()
    ua = _ua()
    ct = getattr(auto.ControlType, f"{want_role}Control", None) if want_role else None
    if ct is not None:
        cond = ua.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, ct)
    elif want_name:
        cond = ua.CreatePropertyConditionEx(auto.PropertyId.NameProperty, name.strip(), 1)
    else:
        return None
    try:
        arr = fg.Element.FindAll(TS_DESCENDANTS, cond)
    except Exception:
        return None
    tx = (bbox[0] + bbox[2]) // 2 if bbox else None
    ty = (bbox[1] + bbox[3]) // 2 if bbox else None
    best, best_dist = None, None
    for i in range(arr.Length):
        e = arr.GetElement(i)
        try:
            n = " ".join((e.CurrentName or "").split()).lower()
            if want_name and n != want_name:
                continue
            r = e.CurrentBoundingRectangle
            if r.right - r.left <= 0 or r.bottom - r.top <= 0:
                continue
            dist = (
                0
                if tx is None
                else abs((r.left + r.right) // 2 - tx) + abs((r.top + r.bottom) // 2 - ty)
            )
        except Exception:
            continue
        if best is None or dist < best_dist:
            best, best_dist = e, dist
    return auto.Control.CreateControlFromElement(best) if best is not None else None


def invoke(name: str, role: str, bbox) -> bool:
    ctrl = _walk_find(name, role, bbox)
    if ctrl is None:
        return False
    try:
        ip = ctrl.GetInvokePattern()
        if ip is not None:
            ip.Invoke()
            return True
    except Exception:
        pass
    # some controls (list items, tabs) expose selection instead of invoke
    try:
        sp = ctrl.GetSelectionItemPattern()
        if sp is not None:
            sp.Select()
            return True
    except Exception:
        pass
    try:  # check boxes / toggle buttons
        tp = ctrl.GetTogglePattern()
        if tp is not None:
            tp.Toggle()
            return True
    except Exception:
        pass
    return False


def set_value(name: str, role: str, bbox, text: str) -> bool:
    ctrl = _walk_find(name, role, bbox)
    if ctrl is None:
        return False
    try:
        vp = ctrl.GetValuePattern()
        if vp is not None and not vp.IsReadOnly:
            vp.SetValue(text)
            return True
    except Exception:
        pass
    return False


def focus(name: str, role: str, bbox) -> bool:
    ctrl = _walk_find(name, role, bbox)
    if ctrl is None:
        return False
    try:
        ctrl.SetFocus()
        import time

        time.sleep(0.1)
        import uiautomation as auto

        fc = auto.GetFocusedControl()
        if fc is not None and (
            fc.Element == ctrl.Element or getattr(ctrl, "HasKeyboardFocus", False)
        ):
            return True
        return bool(getattr(ctrl, "HasKeyboardFocus", False))
    except Exception:
        return False


def exists(name: str, role: str, bbox) -> bool:
    return _walk_find(name, role, bbox) is not None
