"""Transparent step runner — RELAY's core interaction contract.

RELAY is NOT an autonomous agent. It runs the steps the user asked for, ONE at a
time, and for every action it:
  1. ANNOUNCES what it is about to do, before doing it;
  2. does the single action through the central executor (gated + verified);
  3. re-observes and ANNOUNCES the result plus every task-relevant CHANGE on screen.
Between steps it checks for cancel / emergency-stop and stops immediately. Idle when
the plan is done — no background loop.

Each step kind has its own real postcondition: an app's window appeared, the page
title shows the site, a window is minimised / gone, the volume reads the new level,
the clipboard holds the copied text. When a result genuinely can't be observed (a
media key), RELAY says exactly what it did ("I pressed play/pause") and never claims
more.

High-risk clicks (a control whose label is dangerous, or an elevated action) do not
run automatically: the runner asks the Session to obtain an accessible spoken
confirmation first, via ``on_confirm_needed``. Narration verbosity follows the
current mode (quick / detailed / guided / quiet).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from relay.diagnostics import get_logger
from relay.intent.grammar import Kind
from relay.memory.journal import ExecState
from relay.memory.task_context import TaskContext, resolve_reference
from relay.narration import delta as delta_mod
from relay.narration import policy as pol
from relay.recovery import detect as recovery_detect
from relay.safety import Action

log = get_logger("runner")

_APP_EXE = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
    "paint": "mspaint.exe",
    "wordpad": "write.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "chrome": "chrome.exe",
    "brave": "brave.exe",
    "settings": "ms-settings:",
}

_REF_ERROR_SPEECH = {
    "no_screen": "I can't read the screen right now.",
    "out_of_range": "There aren't that many options.",
    "no_prior_reference": "I'm not sure what you mean by that yet.",
    "reference_stale": "That has changed since I last saw it — let me look again.",
    "not_found": "I couldn't find that on the screen.",
    "no_target": "I'm not sure what to act on.",
}

SPOKEN_KEYS = {
    "ctrl": "Control",
    "alt": "Alt",
    "shift": "Shift",
    "win": "Windows",
    "esc": "Escape",
    "pageup": "Page Up",
    "pagedown": "Page Down",
    "backspace": "Backspace",
    "delete": "Delete",
    "enter": "Enter",
    "tab": "Tab",
    "space": "Space",
    "=": "plus",
    "-": "minus",
    "up": "Up arrow",
    "down": "Down arrow",
    "left": "Left arrow",
    "right": "Right arrow",
    "home": "Home",
    "end": "End",
    "playpause": "play/pause",
    "nexttrack": "next track",
    "prevtrack": "previous track",
    "stop": "stop",
}


def spoken_keys(keys) -> str:
    return " ".join(SPOKEN_KEYS.get(k, k.upper() if len(k) == 1 else k.capitalize()) for k in keys)


@dataclass
class StepResult:
    description: str
    # verified | uncertain | failed | cancelled | answered | awaiting_confirmation
    state: str
    detail: str = ""
    deltas: list[str] = field(default_factory=list)


def _wait(cond, timeout: float, interval: float = 0.25) -> bool:
    end = time.monotonic() + timeout
    while True:
        try:
            if cond():
                return True
        except Exception:
            pass
        if time.monotonic() >= end:
            return False
        time.sleep(interval)


class TransparentRunner:
    def __init__(
        self,
        executor,
        worker,
        verifier,
        ctx: TaskContext,
        speak=None,
        emergency=None,
        bus=None,
        engine=None,
        on_confirm_needed=None,
        mode: str = "quick",
        ocr=None,
    ) -> None:
        self.ex = executor
        self.worker = worker
        self.vf = verifier
        self.ctx = ctx
        self._speak = speak
        self.emergency = emergency
        self.bus = bus
        self.engine = engine
        self._on_confirm_needed = on_confirm_needed
        self.mode = mode
        self.ocr = ocr
        self.last_said = ""
        # when NVDA/JAWS/Narrator is running it already announces focus moves; saying
        # them again would talk over it (RELAY still reports everything else)
        self.screen_reader = False

    def say(
        self,
        text: str,
        priority: int = pol.Priority.TASK,
        wait: bool = False,
        timeout: float = 10.0,
    ) -> None:
        if not text or not pol.should_speak(priority, self.mode):
            return
        self.last_said = text
        done_evt = threading.Event() if wait else None

        def _on_done(_completed: bool = True) -> None:
            if done_evt is not None:
                done_evt.set()

        if self._speak is not None:
            try:
                import inspect

                sig = None
                try:
                    sig = inspect.signature(self._speak)
                except (ValueError, TypeError):
                    pass
                if sig and "on_done" in sig.parameters:
                    self._speak(text, on_done=_on_done)
                else:
                    self._speak(text)
                    if done_evt is not None:
                        done_evt.set()
            except Exception:
                if done_evt is not None:
                    done_evt.set()
        else:
            if done_evt is not None:
                done_evt.set()

        if self.bus is not None:
            self.bus.emit("narration.say", text=text)

        if wait and done_evt is not None:
            end_t = time.monotonic() + timeout
            while time.monotonic() < end_t:
                if done_evt.wait(timeout=0.05):
                    break
                if self.emergency is not None and self.emergency.is_engaged:
                    break

    def _stopped(self, cancel) -> bool:
        if self.emergency is not None and self.emergency.is_engaged:
            return True
        return bool(cancel is not None and cancel.is_set())

    def _emit_task(self, state: str) -> None:
        if self.bus is not None:
            self.bus.emit("task.state", to=state)

    def run(self, steps, cancel=None) -> list[StepResult]:
        results: list[StepResult] = []
        if steps:
            self._emit_task("acting")
        for step in steps:
            if self._stopped(cancel):
                self.say("Stopping.", pol.Priority.CONFIRMATION)
                results.append(StepResult(step.description, "cancelled"))
                self._emit_task("cancelled")
                break
            r = self._run_step(step)
            results.append(r)
            if r.state in ("failed", "awaiting_confirmation", "cancelled"):
                self._emit_task(
                    "waiting_for_confirmation" if r.state == "awaiting_confirmation" else r.state
                )
                break  # stop the sequence; the user decides / confirms
        else:
            if steps:
                self._emit_task("completed")
        return results

    # --- per-step ---
    def _run_step(self, step) -> StepResult:
        if step.kind == "answer":
            return self._answer(step)

        prev = self.ctx.last_narrated or self.worker.observe(3.0)
        announce = step.payload.get("announce", f"I'm going to {step.description}.")
        if announce:
            self.say(announce, wait=True)  # announce before acting (wait)
        outcome, detail = self._act(step)
        if outcome == "AWAIT":  # needs spoken confirmation first
            return StepResult(step.description, "awaiting_confirmation", detail)
        new = self.worker.observe(3.0)
        # system settings (volume, media keys) don't change the screen: anything that
        # moved meanwhile is unrelated background, not a result of this action
        deltas = [] if step.payload.get("no_delta") else delta_mod.diff(prev, new)
        if self.screen_reader:
            deltas = [d for d in deltas if not d.startswith("Focus is now on")]
        self.ctx.last_narrated = new
        result = self._narrate_outcome(step, outcome, detail, deltas)
        # surface an UNEXPECTED dialog and offer to help (a save step expects one)
        if step.kind not in ("save", "save_as", "window"):
            issue = recovery_detect(prev, new, result.state in ("verified", "uncertain"))
            if issue is not None and issue.kind == "unexpected_dialog":
                self.say(issue.spoken, pol.Priority.CONFIRMATION)
        return result

    def _narrate_outcome(self, step, outcome, detail, deltas) -> StepResult:
        desc = step.description if hasattr(step, "description") else str(step)
        p = getattr(step, "payload", {}) or {}
        if outcome is None:
            self.say(f"I couldn't do that. {detail}", pol.Priority.CRITICAL)
            return StepResult(desc, "failed", detail, deltas)
        if outcome.state == ExecState.VERIFIED:
            self.say(
                outcome.detail
                if p.get("speak_detail") and outcome.detail
                else f"Done. {desc[:1].upper() + desc[1:]}."
            )
            state = "verified"
        elif outcome.state == ExecState.EXECUTED:
            # ran, but the result isn't observable (a key press, a media key): say
            # exactly what was done — never "done" as if it were verified
            if "done_text" in p:  # "" = the announcement already said it
                if p["done_text"]:
                    self.say(p["done_text"])
                state = "executed"
            else:
                self.say("I did that, but I couldn't fully confirm it.")
                state = "uncertain"
        elif outcome.state == ExecState.UNCERTAIN:
            self.say(
                p.get("uncertain_text")
                or (
                    f"I did that, but I couldn't confirm it: {outcome.detail}."
                    if outcome.detail
                    else "I did that, but I couldn't fully confirm it."
                )
            )
            state = "uncertain"
        elif outcome.state == ExecState.CANCELLED:
            self.say(f"I didn't do that: {_human(outcome.detail)}.", pol.Priority.CONFIRMATION)
            state = "cancelled"
        else:
            self.say(f"That didn't work: {_human(outcome.detail)}.", pol.Priority.CRITICAL)
            state = "failed"
        for d in deltas:  # tell the user every change
            self.say(d)
        return StepResult(desc, state, outcome.detail if outcome else detail, deltas)

    # --- actions ---
    def _act(self, step):
        kind, p = step.kind, step.payload
        if kind == "open":
            app = p["app"].lower().strip()
            exe = _APP_EXE.get(app, app if app.endswith((".exe", ":")) else f"{app}.exe")
            o = self.ex.launch_app(exe)
            time.sleep(1.6)
            # bring the app's window forward — it may not have grabbed the foreground
            self.worker.activate_app(app)
            running = self.vf.app_running(exe) if exe.endswith(".exe") else True
            present = self.vf.window_present(app) or (
                running and self.vf.window_present(exe.replace(".exe", ""))
            )
            return self.vf.verify(
                o, present, "app is on screen" if present else "could not confirm the app opened"
            ), ""
        if kind == "launch":
            return self._act_launch(p), ""
        if kind == "open_uri":
            return self._act_open_uri(p), ""
        if kind == "window":
            return self._act_window(p), ""
        if kind == "type":
            o = self.ex.type_text(p["text"])
            time.sleep(0.4)
            txt = p["text"].strip()
            check_txt = txt if len(txt) <= 20 else txt[:20]
            seen = self.vf.focus_value_contains(check_txt)
            return self.vf.verify(
                o, seen, "the text is there" if seen else "couldn't confirm the text"
            ), ""
        if kind == "save":
            o = self.ex.hotkey("ctrl", "s")
            time.sleep(1.0)
            dlg = self.vf.dialog_present()
            return self.vf.verify(
                o, dlg, "a save dialog opened" if dlg else "no save dialog appeared"
            ), ""
        if kind == "save_as":
            return self._act_save_as(p), ""
        if kind in ("press", "scroll"):
            return self.ex.press(p["key"], count=p.get("count", 1)), ""
        if kind == "hotkey":
            return self._act_hotkey(p), ""
        if kind == "system":
            return self._act_system(p), ""
        if kind == "activate":
            return self._act_activate(step)
        if kind == "new_folder":
            o = self.ex.create_folder(p["target"])
            ok = self.vf.file_exists(str(p["target"]))
            msg = p.get("ok_text", f"The {p.get('name', '')} folder is in {p.get('label', '')}.")
            return self.vf.verify(o, ok, msg), ""
        if kind == "file_op":
            o = self.ex.file_op(p["op"], p["src"], p["dest"])
            ok = self.vf.file_exists(str(p["dest"]))
            return self.vf.verify(o, ok, p.get("ok_text", "")), ""
        if kind == "recycle":
            from pathlib import Path

            o = self.ex.recycle(p["paths"])
            all_removed = not any(Path(path).exists() for path in p["paths"])
            return self.vf.verify(o, all_removed, p.get("ok_text", "moved to the Recycle Bin")), ""
        return None, "unsupported step"

    def _act_launch(self, p):
        o = (
            self.ex.launch_entry(p["entry"])
            if p.get("entry") is not None
            else self.ex.launch_app(p["exe"])
        )
        finder = p.get("find_window")
        win = None
        if finder is not None:
            found = {}

            def seen():
                found["w"] = finder()
                return found["w"] is not None

            _wait(seen, p.get("timeout", 8.0), 0.4)
            win = found.get("w")
            if win is not None and p.get("activate") is not None:
                p["activate"](win.hwnd)
            if win is not None:
                time.sleep(p.get("settle", 1.0))  # let it finish drawing before we look
        ok = win is not None
        return self.vf.verify(
            o,
            ok,
            f"{p.get('label', 'The app')} is open." if ok else "I couldn't see its window yet",
        )

    def _act_open_uri(self, p):
        o = self.ex.open_uri(p["uri"], p.get("label", ""))
        check = p.get("check")
        ok = _wait(check, p.get("timeout", 8.0), 0.4) if check is not None else False
        return self.vf.verify(
            o,
            ok,
            p.get("ok_text", "it opened")
            if ok
            else p.get("fail_text", "I couldn't confirm it opened"),
        )

    def _act_window(self, p):
        from relay.system import windows as w

        op, hwnd = p["op"], p["hwnd"]
        o = self.ex.window_op(hwnd, op, p.get("label", ""))
        if op == "close":
            gone = _wait(lambda: not w.exists(hwnd), 3.0, 0.25)
            if gone:
                done = f"{p.get('label', 'The window')} is closed."
                if w.foreground_blocks_input():
                    done += (
                        " Windows has put one of its own invisible windows in front; "
                        "press Alt+Tab to get back to your other windows."
                    )
                return self.vf.verify(o, True, done)
            # still there: most likely the app is asking to save — narrate, don't force
            snap = self.worker.observe(3.0)
            if snap is not None and snap.dialogs:
                d = snap.dialogs[0]
                btns = f" Options: {', '.join(d.buttons)}." if d.buttons else ""
                return self.vf.verify(o, False, f"It's asking: {d.title}.{btns}")
            return self.vf.verify(o, False, "the window is still open")
        checks = {
            "minimize": lambda: w.user32.IsIconic(hwnd),
            "maximize": lambda: w.user32.IsZoomed(hwnd),
            "restore": lambda: not w.user32.IsIconic(hwnd),
            "activate": lambda: (
                w.user32.GetForegroundWindow() == hwnd
                or (w.foreground() is not None and w.foreground().hwnd == hwnd)
            ),
        }
        ok = _wait(checks[op], 2.0, 0.2)
        if not ok and op == "activate" and w.foreground_blocks_input():
            # an invisible Windows/system window holds focus: only a real key press frees it
            return self.vf.verify(
                o,
                False,
                "Windows is keeping one of its own windows in "
                "front. Press Alt+Tab once, then ask me again",
            )
        return self.vf.verify(o, ok, p.get("ok_text", "") if ok else "")

    def _act_hotkey(self, p):
        keys = p["keys"]
        before = p["before"]() if p.get("before") else None
        if p.get("sequence"):
            o = None
            for k in keys:
                o = self.ex.press(k)
                if o.state != ExecState.EXECUTED:
                    break
        else:
            o = self.ex.hotkey(*keys, count=p.get("count", 1))
        check = p.get("check")
        if check is None or o.state != ExecState.EXECUTED:
            return o
        time.sleep(p.get("settle", 0.35))
        try:
            ok, text = check(before)
        except Exception as e:
            log.debug("hotkey check failed: %s", e)
            ok, text = False, ""
        return self.vf.verify(o, ok, text)

    def _act_system(self, p):
        o = self.ex.system(p["what"], p["do"], p.get("label", ""))
        if o.state != ExecState.EXECUTED:
            return o
        ok, text = p["check"]()
        return self.vf.verify(o, ok, text)

    def _act_save_as(self, p):
        """Save As <name>: open the app's Save As dialog, type the name, press Enter,
        then check the dialog closed and the title shows the new name. An overwrite
        question is narrated, never answered automatically."""
        keys = p.get("keys") or ("ctrl", "shift", "s")
        o = self.ex.hotkey(*keys)
        if o.state != ExecState.EXECUTED:
            return o
        if not _wait(self.vf.dialog_present, 4.0, 0.3):
            return self.vf.verify(o, False, "the Save As dialog didn't open")
        o2 = self.ex.type_text(p["name"])
        time.sleep(0.3)
        o3 = self.ex.press("enter")
        if o2.state != ExecState.EXECUTED or o3.state != ExecState.EXECUTED:
            return o3 if o3.state != ExecState.EXECUTED else o2
        time.sleep(1.2)
        snap = self.worker.observe(3.0)
        if snap is not None and snap.dialogs:
            d = snap.dialogs[0]
            btns = f" Options: {', '.join(d.buttons)}." if d.buttons else ""
            return self.vf.verify(o3, False, f"It's asking: {d.title}.{btns}")
        stem = p["name"].rsplit(".", 1)[0].lower()
        titled = bool(snap and stem[:20] in (snap.foreground_title or "").lower())
        return self.vf.verify(
            o3,
            titled,
            f"Saved as {p['name']}."
            if titled
            else "the dialog closed but I couldn't see the new name",
        )

    def _act_activate(self, step):
        p = step.payload
        snap = self.worker.observe(3.0)
        el, err = resolve_reference(
            self.ctx, snap, target=p.get("target"), ordinal=p.get("ordinal"), role=p.get("role")
        )
        if el is None and p.get("deep_find") is not None and err in ("not_found", "out_of_range"):
            el = p["deep_find"]()
            if el is not None:
                err = None
        if el is None and self.ocr is not None and p.get("target"):
            el = self._find_via_ocr(p.get("target"), ordinal=p.get("ordinal"))
            if el is not None:
                err = None
        if el is None:
            return None, _REF_ERROR_SPEECH.get(err, "I couldn't do that.")
        if self.engine is not None and self._on_confirm_needed is not None:
            is_pwd = bool(el.states.get("is_password") or el.states.get("protected"))
            dec = self.engine.classify(
                Action(
                    kind="invoke",
                    target_app=el.window_title,
                    target_label=el.name,
                    target_role=el.role,
                    is_password_field=is_pwd,
                )
            )
            if dec.requires_confirmation:
                self._on_confirm_needed(
                    dec,
                    el.name,
                    lambda e=el, s=snap, d=step.description: self._confirmed_activate(d, e, s),
                )
                return "AWAIT", dec.spoken_summary
        if p.get("ordinal") is not None:  # say WHICH one an ordinal resolved to
            role = el.role.lower() if el.role else "control"
            self.say(f"That's the {role} {el.name}.", pol.Priority.FOCUS)
        return self._invoke_verify(el, snap), ""

    def _invoke_verify(self, el, prev_snap):
        o = self.ex.invoke_element(el)
        time.sleep(0.6)
        after = self.worker.observe(3.0)
        changed = bool(delta_mod.diff(prev_snap, after)) or (
            after is not None
            and prev_snap is not None
            and after.fingerprint() != prev_snap.fingerprint()
        )
        return self.vf.verify(o, changed, "it responded" if changed else "nothing seemed to change")

    def _confirmed_activate(self, desc, el, prev_snap) -> StepResult:
        """Run an activation the user has just confirmed by phrase, and narrate it."""
        self.ex.grant_next_confirmation()
        outcome = self._invoke_verify(el, prev_snap)
        new = self.worker.observe(3.0)
        deltas = delta_mod.diff(self.ctx.last_narrated, new)
        self.ctx.last_narrated = new

        class _S:
            description = desc
            payload: dict = {}

        return self._narrate_outcome(_S, outcome, "", deltas)

    def _find_via_ocr(self, target: str, ordinal: int | None = None) -> UIElement | None:
        if not target or self.ocr is None:
            return None
        import re
        raw_target = (target or "").strip()
        cleaned = re.sub(
            r"\b(?:the|button|link|icon|tab|menu|field|result|on|named|called)\b",
            " ",
            raw_target,
            flags=re.I,
        ).strip()
        cleaned = " ".join(cleaned.split()).lower()
        if not cleaned:
            cleaned = raw_target.lower()

        from relay.system import windows
        import ctypes
        from ctypes import wintypes
        fg = windows.foreground()
        region = None
        hwnd = None
        if fg is not None:
            try:
                hwnd = fg.hwnd
                r = wintypes.RECT()
                if ctypes.windll.user32.GetWindowRect(fg.hwnd, ctypes.byref(r)):
                    region = (max(0, r.left), max(0, r.top), r.right, r.bottom)
            except Exception:
                pass

        try:
            regions = self.ocr.read_screen(region=region, hwnd=hwnd)
            if not regions and region is not None:
                regions = self.ocr.read_screen()
        except Exception as e:
            log.debug("OCR find in runner failed: %s", e)
            return None

        if not regions:
            return None

        candidates = []
        for e in regions:
            name = (e.name or "").strip().lower()
            if not name:
                continue
            score = 0
            if name == cleaned:
                score = 100
            elif cleaned in name:
                score = 80
            elif name in cleaned:
                score = 75
            else:
                target_words = cleaned.split()
                name_words = name.split()
                overlap = sum(1 for w in target_words if w in name_words or any(w in nw for nw in name_words))
                if overlap > 0:
                    score = 50 + int(20 * (overlap / len(target_words)))
            if score > 0:
                candidates.append((score, e))

        if not candidates:
            return None

        if ordinal is not None and ordinal > 0:
            top_score = max(c[0] for c in candidates)
            pool = [c[1] for c in candidates if c[0] >= top_score - 20]
            pool.sort(key=lambda el: (el.bbox[1], el.bbox[0]))
            idx = ordinal - 1
            if 0 <= idx < len(pool):
                return pool[idx]
            return pool[0] if pool else None

        candidates.sort(key=lambda c: (c[0], c[1].states.get("ocr_confidence", 0)), reverse=True)
        return candidates[0][1]

    # --- answering intents (no OS action) ---
    def _answer(self, step) -> StepResult:
        ak = step.payload.get("answer_kind")
        snap = self.worker.observe(3.0)
        if ak == Kind.WHAT_CHANGED:
            deltas = delta_mod.diff(self.ctx.last_narrated, snap)
            self.ctx.last_narrated = snap
            self.say(
                "Nothing has changed." if not deltas else " ".join(deltas), pol.Priority.REQUESTED
            )
            return StepResult("what changed", "answered", deltas=deltas)
        if snap is None:
            self.say("I can't read the screen right now.", pol.Priority.REQUESTED)
            return StepResult("answer", "answered")
        if ak == Kind.WHERE_AM_I:
            self.say(pol.describe(snap, self.mode), pol.Priority.REQUESTED)
        elif ak == Kind.LIST_OPTIONS:
            names = [e.name for e in _reading_order(delta_mod.meaningful(snap.elements)) if e.name][
                :10
            ]
            self.say(
                "Your options include: " + ", ".join(names) + "."
                if names
                else "I don't see any labelled controls to choose from.",
                pol.Priority.REQUESTED,
            )
        elif ak == Kind.READ_FOCUS:
            if snap.selection:
                self.say(f"Selected text: {snap.selection}", pol.Priority.REQUESTED)
            elif snap.focus and (snap.focus.value or snap.focus.name):
                self.say(
                    f"{snap.focus.role}: {snap.focus.value or snap.focus.name}",
                    pol.Priority.REQUESTED,
                )
            else:
                self.say("Nothing is focused right now.", pol.Priority.REQUESTED)
        elif ak == Kind.HELP:
            self.say(
                "You can say: what's on my screen, open an app, click something, "
                "type text, save, what changed, next, spell that, quiet mode, "
                "stop, or cancel.",
                pol.Priority.REQUESTED,
            )
        else:  # DESCRIBE_SCREEN
            self.say(pol.describe(snap, self.mode), pol.Priority.REQUESTED)
        self.ctx.last_narrated = snap
        return StepResult("answer", "answered")


def _reading_order(elements):
    return sorted(elements, key=lambda e: (e.bbox[1] // 12, e.bbox[0]))


_HUMAN = [
    ("winerror 2", "Windows couldn't find that program"),
    ("the system cannot find the file", "Windows couldn't find that"),
    ("emergency stop engaged", "the emergency stop is on — say continue to clear it"),
    ("not confirmed", "it needs your confirmation first"),
    ("blocked", "that action isn't allowed"),
    ("revalidation failed", "that control disappeared before I could use it"),
    ("invoke pattern unavailable", "that control doesn't respond to activation"),
]


def _human(detail: str) -> str:
    """Plain words instead of raw exception text."""
    low = (detail or "").lower()
    for needle, words in _HUMAN:
        if needle in low:
            return words
    return detail or "something went wrong"
