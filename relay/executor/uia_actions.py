"""UIA actions that run ON the UIA worker thread.

These re-locate the target element in the CURRENT foreground tree (never reusing a
cached control object from an old observation) and act through native patterns. Re-
locating here is the "revalidate the target immediately before executing" rule made
concrete: if the element is gone, the action fails cleanly instead of clicking a
stale coordinate.

Matching is by (name, role) with a tie-break on proximity to the last-known bbox
centre, so the right control is picked even when several share a name.
"""

from __future__ import annotations

_MAX_VISITED = 2500
_MAX_DEPTH = 12


def _walk_find(name: str, role: str, bbox: tuple[int, int, int, int] | None):
    import uiautomation as auto
    fg = auto.GetForegroundControl()
    if fg is None:
        return None
    want_name = (name or "").strip().lower()
    want_role = (role or "").strip().lower()
    target_cx = (bbox[0] + bbox[2]) // 2 if bbox else None
    target_cy = (bbox[1] + bbox[3]) // 2 if bbox else None

    best = None
    best_dist = None
    visited = [0]

    def walk(ctrl, depth):
        nonlocal best, best_dist
        if visited[0] >= _MAX_VISITED or depth > _MAX_DEPTH:
            return
        visited[0] += 1
        try:
            n = (ctrl.Name or "").strip().lower()
            r = (ctrl.ControlTypeName or "").replace("Control", "").lower()
        except Exception:
            n, r = "", ""
        name_ok = (n == want_name) if want_name else True
        role_ok = (r == want_role) if want_role else True
        if name_ok and role_ok and (want_name or want_role):
            try:
                rect = ctrl.BoundingRectangle
                if rect.width() > 0 and rect.height() > 0:
                    if target_cx is None:
                        return_ctrl(ctrl, 0)
                    else:
                        cx = (rect.left + rect.right) // 2
                        cy = (rect.top + rect.bottom) // 2
                        dist = abs(cx - target_cx) + abs(cy - target_cy)
                        return_ctrl(ctrl, dist)
            except Exception:
                pass
        try:
            for c in ctrl.GetChildren():
                walk(c, depth + 1)
        except Exception:
            pass

    def return_ctrl(ctrl, dist):
        nonlocal best, best_dist
        if best is None or dist < best_dist:
            best, best_dist = ctrl, dist

    walk(fg, 0)
    return best


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
        return True
    except Exception:
        return False


def exists(name: str, role: str, bbox) -> bool:
    return _walk_find(name, role, bbox) is not None
