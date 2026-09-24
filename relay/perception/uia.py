"""Windows UI Automation reading.

Everything here runs on the dedicated UIA worker thread (see worker.py) — never
call it from the core or audio threads. It turns the live accessibility tree into a
ScreenSnapshot: the foreground app/window, focused element, interactive controls
with their native patterns/states, and dialogs. Enumeration is bounded (element,
depth and node budgets) so a huge Chromium/Electron tree can't take seconds.

Native patterns are preferred over coordinates: an element's available_actions are
derived from the UIA patterns it actually exposes (Invoke/Value/Toggle/…), which is
what lets the executor act semantically and verify. Protected fields (passwords,
OTPs) are detected and their values are never read.
"""

from __future__ import annotations

import ctypes

from relay.perception.semantic import Dialog, ScreenSnapshot, UIElement
from relay.safety import is_protected_field

MAX_ELEMENTS = 120
MAX_DEPTH = 12
MAX_VISITED = 2500

_INTERACTIVE = {
    "ButtonControl", "EditControl", "ComboBoxControl", "CheckBoxControl",
    "RadioButtonControl", "MenuItemControl", "ListItemControl", "TreeItemControl",
    "TabItemControl", "HyperlinkControl", "SliderControl", "SplitButtonControl",
    "DocumentControl", "TextControl",
}

_dpi_done = False


def ensure_dpi_aware() -> None:
    """Per-process DPI awareness so BoundingRectangle is physical pixels (matches
    screenshot/click coordinates)."""
    global _dpi_done
    if _dpi_done:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    _dpi_done = True


def _role(ctrl) -> str:
    try:
        return (ctrl.ControlTypeName or "").replace("Control", "")
    except Exception:
        return ""


def _app_name(ctrl) -> str:
    try:
        import psutil
        return psutil.Process(ctrl.ProcessId).name()
    except Exception:
        return ""


def _actions_and_value(ctrl, role: str, name: str) -> tuple[tuple[str, ...], str, dict]:
    """Derive available high-level actions, a readable value, and states from the
    UIA patterns the control exposes. Never returns a protected field's value."""
    actions: list[str] = []
    value = ""
    states: dict = {}
    protected = is_protected_field(role=role, name=name)

    def has(getter: str) -> bool:
        try:
            return getattr(ctrl, getter)() is not None
        except Exception:
            return False

    if has("GetInvokePattern"):
        actions.append("invoke")
    if has("GetValuePattern"):
        actions.append("set_value")
        if not protected:
            try:
                value = ctrl.GetValuePattern().Value or ""
            except Exception:
                value = ""
    if has("GetTogglePattern"):
        actions.append("toggle")
        try:
            states["toggled"] = int(ctrl.GetTogglePattern().ToggleState) == 1
        except Exception:
            pass
    if has("GetExpandCollapsePattern"):
        actions.append("expand")
    if has("GetSelectionItemPattern"):
        actions.append("select")
        try:
            states["selected"] = bool(ctrl.GetSelectionItemPattern().IsSelected)
        except Exception:
            pass
    if not value and not protected and role in ("Text", "Document"):
        try:
            tp = ctrl.GetTextPattern()
            if tp is not None:
                value = tp.DocumentRange.GetText(200)
        except Exception:
            pass
    if protected:
        states["protected"] = True
    return tuple(actions), (value or "").strip(), states


def _valid(ctrl) -> bool:
    try:
        if ctrl.IsOffscreen:
            return False
        r = ctrl.BoundingRectangle
        return r.width() > 0 and r.height() > 0
    except Exception:
        return False


def _enumerate(root, window_title: str, screen_area: int) -> list[UIElement]:
    elements: list[UIElement] = []
    visited = [0]

    def walk(ctrl, depth: int) -> None:
        if visited[0] >= MAX_VISITED or depth > MAX_DEPTH or len(elements) >= MAX_ELEMENTS:
            return
        visited[0] += 1
        role_full = ""
        try:
            role_full = ctrl.ControlTypeName or ""
        except Exception:
            pass
        if role_full in _INTERACTIVE and _valid(ctrl):
            r = ctrl.BoundingRectangle
            area = (r.right - r.left) * (r.bottom - r.top)
            if area < screen_area * 0.95:  # skip near-fullscreen containers
                role = role_full.replace("Control", "")
                name = ""
                try:
                    name = (ctrl.Name or "").strip()
                except Exception:
                    pass
                actions, value, states = _actions_and_value(ctrl, role, name)
                try:
                    states["enabled"] = bool(ctrl.IsEnabled)
                    states["focused"] = bool(ctrl.HasKeyboardFocus)
                except Exception:
                    pass
                elements.append(UIElement(
                    uid=0, name=name, role=role,
                    bbox=(int(r.left), int(r.top), int(r.right), int(r.bottom)),
                    value=value, actions=actions, states=states,
                    window_title=window_title,
                ))
        try:
            children = ctrl.GetChildren()
        except Exception:
            children = []
        for c in children:
            walk(c, depth + 1)

    walk(root, 0)
    return elements


def _detect_dialogs(fg) -> list[Dialog]:
    """Detect classic Win32 dialogs (#32770) — save/open/message boxes — by class,
    collecting their button labels."""
    dialogs: list[Dialog] = []
    try:
        candidates = [fg] + list(fg.GetChildren())
    except Exception:
        candidates = [fg]
    for w in candidates:
        try:
            if getattr(w, "ClassName", "") == "#32770":
                buttons = []
                for c in w.GetChildren():
                    try:
                        if c.ControlTypeName == "ButtonControl" and c.Name:
                            buttons.append(c.Name.strip())
                    except Exception:
                        pass
                dialogs.append(Dialog(title=(w.Name or "Dialog").strip(),
                                      buttons=tuple(buttons)))
        except Exception:
            continue
    return dialogs


def list_top_windows() -> list[dict]:
    """All visible top-level windows (title + owning app + hwnd). Runs on the UIA
    thread. Lets RELAY find a just-launched app that didn't grab the foreground."""
    import uiautomation as auto
    ensure_dpi_aware()
    out: list[dict] = []
    try:
        root = auto.GetRootControl()
        children = root.GetChildren()
    except Exception:
        return out
    for w in children:
        try:
            if w.ControlTypeName != "WindowControl" or w.IsOffscreen:
                continue
            r = w.BoundingRectangle
            if r.width() <= 0 or r.height() <= 0:
                continue
            out.append({"title": (w.Name or "").strip(), "app": _app_name(w),
                        "hwnd": int(w.NativeWindowHandle)})
        except Exception:
            continue
    return out


def activate_window(hwnd: int) -> bool:
    """Best-effort bring a window to the foreground (restore if minimised). Windows
    can refuse a foreground change from a background process (a documented OS lock),
    so this is best-effort and the caller must still verify."""
    import time
    user32 = ctypes.windll.user32
    try:
        user32.ShowWindow(hwnd, 9)       # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        return int(user32.GetForegroundWindow()) == hwnd
    except Exception:
        return False


def find_and_activate(app_or_title: str) -> bool:
    """Find a top-level window whose app/title matches and bring it forward."""
    t = app_or_title.lower().replace(".exe", "").strip()
    for wd in list_top_windows():
        if t and (t in wd["app"].lower() or t in wd["title"].lower()):
            return activate_window(wd["hwnd"])
    return False


def observe(observation_version: int) -> ScreenSnapshot:
    """Read the current foreground window into a ScreenSnapshot. Runs on the UIA
    worker thread. Returns a snapshot with ``uia_available=False`` when the tree
    yields nothing (candidate for OCR), never a fabricated element."""
    import uiautomation as auto

    ensure_dpi_aware()
    user32 = ctypes.windll.user32
    screen_area = user32.GetSystemMetrics(0) * user32.GetSystemMetrics(1)

    fg = auto.GetForegroundControl()
    if fg is None:
        return ScreenSnapshot(observation_version, uia_available=False)

    title = ""
    try:
        title = (fg.Name or "").strip()
    except Exception:
        pass
    app = _app_name(fg)

    focus_el = None
    try:
        fc = auto.GetFocusedControl()
        if fc is not None:
            role = _role(fc)
            name = (fc.Name or "").strip()
            actions, value, states = _actions_and_value(fc, role, name)
            r = fc.BoundingRectangle
            focus_el = UIElement(
                uid=-1, name=name, role=role,
                bbox=(int(r.left), int(r.top), int(r.right), int(r.bottom)),
                value=value, actions=actions, states={**states, "focused": True},
                window_title=title,
            )
    except Exception:
        focus_el = None

    elements = _enumerate(fg, title, screen_area)
    # small-first (more specific), de-dup, assign stable uids
    elements.sort(key=lambda e: (e.bbox[2] - e.bbox[0]) * (e.bbox[3] - e.bbox[1]))
    seen: set[tuple] = set()
    unique: list[UIElement] = []
    for e in elements:
        key = (e.name, e.role, e.bbox)
        if key not in seen:
            seen.add(key)
            unique.append(e)
    numbered = [UIElement(uid=i, name=e.name, role=e.role, bbox=e.bbox, value=e.value,
                          actions=e.actions, states=e.states, window_title=e.window_title,
                          provenance=e.provenance)
                for i, e in enumerate(unique, start=1)]

    dialogs = _detect_dialogs(fg)
    selection = ""
    try:
        fc = auto.GetFocusedControl()
        if fc is not None:
            tp = fc.GetTextPattern()
            if tp is not None:
                sel = tp.GetSelection()
                if sel:
                    selection = " ".join(s.GetText(200) for s in sel).strip()
    except Exception:
        selection = ""

    return ScreenSnapshot(
        observation_version=observation_version,
        foreground_app=app, foreground_title=title,
        focus=focus_el, elements=numbered, dialogs=dialogs, selection=selection,
        uia_available=bool(numbered or focus_el or title),
    )
