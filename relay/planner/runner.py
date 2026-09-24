"""Transparent step runner — RELAY's core interaction contract.

RELAY is NOT an autonomous agent. It runs the steps the user asked for, ONE at a
time, and for every action it:
  1. ANNOUNCES what it is about to do, before doing it;
  2. does the single action through the central executor (gated + verified);
  3. re-observes and ANNOUNCES the result plus every task-relevant CHANGE on screen.
Between steps it checks for cancel / emergency-stop and stops immediately. Idle when
the plan is done — no background loop.

High-risk clicks (a control whose label is dangerous, or an elevated action) do not
run automatically: the runner asks the Session to obtain an accessible spoken
confirmation first, via ``on_confirm_needed``. Narration verbosity follows the
current mode (quick / detailed / guided / quiet).
"""

from __future__ import annotations

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
    "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe",
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "files": "explorer.exe",
    "paint": "mspaint.exe", "wordpad": "write.exe", "edge": "msedge.exe",
    "microsoft edge": "msedge.exe", "chrome": "chrome.exe", "brave": "brave.exe",
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


@dataclass
class StepResult:
    description: str
    # verified | uncertain | failed | cancelled | answered | awaiting_confirmation
    state: str
    detail: str = ""
    deltas: list[str] = field(default_factory=list)


class TransparentRunner:
    def __init__(self, executor, worker, verifier, ctx: TaskContext, speak=None,
                 emergency=None, bus=None, engine=None, on_confirm_needed=None,
                 mode: str = "quick") -> None:
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
        self.last_said = ""

    def say(self, text: str, priority: int = pol.Priority.TASK) -> None:
        if not text or not pol.should_speak(priority, self.mode):
            return
        self.last_said = text
        if self._speak is not None:
            try:
                self._speak(text)
            except Exception:
                pass
        if self.bus is not None:
            self.bus.emit("narration.say", text=text)

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
            if r.state in ("failed", "awaiting_confirmation"):
                self._emit_task("waiting_for_confirmation" if r.state == "awaiting_confirmation"
                                else "failed")
                break  # stop the sequence; the user decides / confirms
        else:
            if steps:
                self._emit_task("completed")
        return results

    # --- per-step ---
    def _run_step(self, step) -> StepResult:
        if step.kind == "answer":
            return self._answer(step)

        prev = self.ctx.last_narrated
        self.say(f"I'm going to {step.description}.")   # announce BEFORE acting
        outcome, detail = self._act(step)
        if outcome == "AWAIT":                          # needs spoken confirmation first
            return StepResult(step.description, "awaiting_confirmation", detail)
        new = self.worker.observe(3.0)
        deltas = delta_mod.diff(prev, new)
        self.ctx.last_narrated = new
        result = self._narrate_outcome(step.description, outcome, detail, deltas)
        # surface an UNEXPECTED dialog and offer to help (a save step expects one)
        if step.kind != "save":
            issue = recovery_detect(prev, new, result.state in ("verified", "uncertain"))
            if issue is not None and issue.kind == "unexpected_dialog":
                self.say(issue.spoken, pol.Priority.CONFIRMATION)
        return result

    def _narrate_outcome(self, desc, outcome, detail, deltas) -> StepResult:
        if outcome is None:
            self.say(f"I couldn't do that. {detail}", pol.Priority.CRITICAL)
            return StepResult(desc, "failed", detail, deltas)
        if outcome.state == ExecState.VERIFIED:
            self.say(f"Done. {desc.capitalize()}.")
            state = "verified"
        elif outcome.state == ExecState.EXECUTED:
            self.say("I did that, but I couldn't fully confirm it.")
            state = "uncertain"
        elif outcome.state == ExecState.CANCELLED:
            self.say(f"I didn't do that: {outcome.detail}.", pol.Priority.CONFIRMATION)
            state = "cancelled"
        else:
            self.say(f"That didn't work: {outcome.detail}.", pol.Priority.CRITICAL)
            state = "failed"
        for d in deltas:                                # tell the user every change
            self.say(d)
        return StepResult(desc, state, outcome.detail if outcome else detail, deltas)

    def _act(self, step):
        kind, p = step.kind, step.payload
        if kind in ("open", "switch"):
            app = p["app"].lower().strip()
            exe = _APP_EXE.get(app, app if app.endswith((".exe", ":")) else f"{app}.exe")
            o = self.ex.launch_app(exe)
            time.sleep(1.6)
            # bring the app's window forward — it may not have grabbed the foreground
            self.worker.activate_app(app)
            running = self.vf.app_running(exe) if exe.endswith(".exe") else True
            present = running or self.vf.window_present(app)
            return self.vf.verify(o, present, "app is on screen" if present
                                  else "could not confirm the app opened"), ""
        if kind == "type":
            o = self.ex.type_text(p["text"])
            time.sleep(0.4)
            snippet = (p["text"].split() or [p["text"]])[0]
            seen = self.vf.focus_value_contains(snippet[:12])
            return self.vf.verify(o, seen, "the text is there" if seen
                                  else "couldn't confirm the text"), ""
        if kind == "save":
            o = self.ex.hotkey("ctrl", "s")
            time.sleep(1.0)
            dlg = self.vf.dialog_present()
            return self.vf.verify(o, dlg, "a save dialog opened" if dlg
                                  else "no save dialog appeared"), ""
        if kind in ("press", "scroll"):
            return self.ex.press(p["key"]), ""
        if kind == "activate":
            snap = self.worker.observe(3.0)
            el, err = resolve_reference(self.ctx, snap, target=p.get("target"),
                                        ordinal=p.get("ordinal"))
            if el is None:
                return None, _REF_ERROR_SPEECH.get(err, "I couldn't do that.")
            if self.engine is not None and self._on_confirm_needed is not None:
                dec = self.engine.classify(Action(
                    kind="invoke", target_app=el.window_title,
                    target_label=el.name, target_role=el.role))
                if dec.requires_confirmation:
                    self._on_confirm_needed(
                        dec, el.name,
                        lambda e=el, s=snap, d=step.description: self._confirmed_activate(d, e, s))
                    return "AWAIT", dec.spoken_summary
            return self._invoke_verify(el, snap), ""
        return None, "unsupported step"

    def _invoke_verify(self, el, prev_snap):
        o = self.ex.invoke_element(el)
        time.sleep(0.6)
        after = self.worker.observe(3.0)
        changed = bool(delta_mod.diff(prev_snap, after))
        return self.vf.verify(o, changed, "it responded" if changed
                              else "nothing seemed to change")

    def _confirmed_activate(self, desc, el, prev_snap) -> StepResult:
        """Run an activation the user has just confirmed by phrase, and narrate it."""
        self.ex.grant_next_confirmation()
        outcome = self._invoke_verify(el, prev_snap)
        new = self.worker.observe(3.0)
        deltas = delta_mod.diff(self.ctx.last_narrated, new)
        self.ctx.last_narrated = new
        return self._narrate_outcome(desc, outcome, "", deltas)

    # --- answering intents (no OS action) ---
    def _answer(self, step) -> StepResult:
        ak = step.payload.get("answer_kind")
        snap = self.worker.observe(3.0)
        if ak == Kind.WHAT_CHANGED:
            deltas = delta_mod.diff(self.ctx.last_narrated, snap)
            self.ctx.last_narrated = snap
            self.say("Nothing has changed." if not deltas else " ".join(deltas),
                     pol.Priority.REQUESTED)
            return StepResult("what changed", "answered", deltas=deltas)
        if snap is None:
            self.say("I can't read the screen right now.", pol.Priority.REQUESTED)
            return StepResult("answer", "answered")
        if ak == Kind.WHERE_AM_I:
            self.say(pol.describe(snap, self.mode), pol.Priority.REQUESTED)
        elif ak == Kind.LIST_OPTIONS:
            names = [e.name for e in snap.elements if e.name][:8]
            self.say("Your options include: " + ", ".join(names) + "." if names
                     else "I don't see any labelled controls to choose from.",
                     pol.Priority.REQUESTED)
        elif ak == Kind.READ_FOCUS:
            if snap.selection:
                self.say(f"Selected text: {snap.selection}", pol.Priority.REQUESTED)
            elif snap.focus and (snap.focus.value or snap.focus.name):
                self.say(f"{snap.focus.role}: {snap.focus.value or snap.focus.name}",
                         pol.Priority.REQUESTED)
            else:
                self.say("Nothing is focused right now.", pol.Priority.REQUESTED)
        elif ak == Kind.HELP:
            self.say("You can say: what's on my screen, open an app, click something, "
                     "type text, save, what changed, next, spell that, quiet mode, "
                     "stop, or cancel.", pol.Priority.REQUESTED)
        else:  # DESCRIBE_SCREEN
            self.say(pol.describe(snap, self.mode), pol.Priority.REQUESTED)
        self.ctx.last_narrated = snap
        return StepResult("answer", "answered")
