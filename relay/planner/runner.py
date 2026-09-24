"""Transparent step runner — RELAY's core interaction contract.

RELAY is NOT an autonomous agent. It runs the steps the user asked for, ONE at a
time, and for every action it:
  1. ANNOUNCES what it is about to do, before doing it;
  2. does the single action through the central executor (gated + verified);
  3. re-observes and ANNOUNCES the result plus every task-relevant CHANGE on screen
     (the delta versus what the user was last told).
Between steps it checks for cancel / emergency-stop and stops immediately. It never
runs silently to completion, and it goes idle when the plan is done — no background
loop. Answering intents ("what's on my screen", "what changed") never touch the OS.

Narration is emitted through an injected ``speak`` callable (real = the Piper speech
queue) and on the event bus, so both the ear and the optional UI stay in sync.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from relay.diagnostics import get_logger
from relay.intent.grammar import Kind
from relay.memory.journal import ExecState
from relay.memory.task_context import TaskContext, resolve_reference
from relay.narration import delta as delta_mod

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
    state: str            # verified | executed | uncertain | failed | cancelled | answered
    detail: str = ""
    deltas: list[str] = field(default_factory=list)


class TransparentRunner:
    def __init__(self, executor, worker, verifier, ctx: TaskContext,
                 speak=None, emergency=None, bus=None) -> None:
        self.ex = executor
        self.worker = worker
        self.vf = verifier
        self.ctx = ctx
        self._speak = speak
        self.emergency = emergency
        self.bus = bus

    def say(self, text: str) -> None:
        if not text:
            return
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

    def run(self, steps, cancel=None) -> list[StepResult]:
        results: list[StepResult] = []
        for step in steps:
            if self._stopped(cancel):
                self.say("Stopping.")
                results.append(StepResult(step.description, "cancelled"))
                break
            r = self._run_step(step)
            results.append(r)
            if r.state == "failed":
                # do not blindly continue a sequence after a failure; the user decides
                break
        return results

    # --- per-step ---
    def _run_step(self, step) -> StepResult:
        if step.kind == "answer":
            return self._answer(step)

        self.say(f"I'm going to {step.description}.")   # announce BEFORE acting
        outcome, ok = self._act(step)
        new = self.worker.observe(3.0)
        deltas = delta_mod.diff(self.ctx.last_narrated, new)
        self.ctx.last_narrated = new

        if outcome is None:                       # could not even attempt (e.g. bad ref)
            return StepResult(step.description, "failed", ok, deltas)
        if outcome.state == ExecState.VERIFIED:
            self.say(f"Done. {step.description.capitalize()}.")
            state = "verified"
        elif outcome.state == ExecState.EXECUTED:
            self.say("I did that, but I couldn't fully confirm it.")
            state = "uncertain"
        elif outcome.state == ExecState.CANCELLED:
            self.say(f"I didn't do that: {outcome.detail}.")
            state = "cancelled"
        else:
            self.say(f"That didn't work: {outcome.detail}.")
            state = "failed"
        for d in deltas:                          # tell the user every change
            self.say(d)
        return StepResult(step.description, state, outcome.detail, deltas)

    def _act(self, step):
        kind = step.kind
        p = step.payload
        if kind == "open" or kind == "switch":
            app = p["app"].lower().strip()
            exe = _APP_EXE.get(app, app if app.endswith((".exe", ":")) else f"{app}.exe")
            o = self.ex.launch_app(exe)
            time.sleep(1.6)
            running = self.vf.app_running(exe) if exe.endswith(".exe") else True
            present = running or self.vf.window_present(app)
            return self.vf.verify(o, present, "app is on screen" if present
                                  else "could not confirm the app opened"), ""
        if kind == "type":
            o = self.ex.type_text(p["text"])
            time.sleep(0.4)
            snippet = p["text"].split()[0] if p["text"].split() else p["text"]
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
            o = self.ex.press(p["key"])
            return o, ""   # generic key press: executed (no universal postcondition)
        if kind == "activate":
            snap = self.worker.observe(3.0)
            el, err = resolve_reference(self.ctx, snap, target=p.get("target"),
                                        ordinal=p.get("ordinal"))
            if el is None:
                return None, _REF_ERROR_SPEECH.get(err, "I couldn't do that.")
            o = self.ex.invoke_element(el)
            time.sleep(0.6)
            after = self.worker.observe(3.0)
            changed = bool(delta_mod.diff(snap, after))
            return self.vf.verify(o, changed, "it responded" if changed
                                  else "nothing seemed to change"), ""
        return None, "unsupported step"

    # --- answering intents (no OS action) ---
    def _answer(self, step) -> StepResult:
        ak = step.payload.get("answer_kind")
        snap = self.worker.observe(3.0)
        if ak == Kind.WHAT_CHANGED:
            deltas = delta_mod.diff(self.ctx.last_narrated, snap)
            self.ctx.last_narrated = snap
            self.say("Nothing has changed." if not deltas else " ".join(deltas))
            return StepResult("what changed", "answered", deltas=deltas)
        if snap is None:
            self.say("I can't read the screen right now.")
            return StepResult("answer", "answered")
        if ak == Kind.WHERE_AM_I:
            self.say(snap.summary())
        elif ak == Kind.LIST_OPTIONS:
            names = [e.name for e in snap.elements if e.name][:8]
            self.say("Your options include: " + ", ".join(names) + "." if names
                     else "I don't see any labelled controls to choose from.")
        elif ak == Kind.READ_FOCUS:
            if snap.selection:
                self.say(f"Selected text: {snap.selection}")
            elif snap.focus and (snap.focus.value or snap.focus.name):
                self.say(f"{snap.focus.role}: {snap.focus.value or snap.focus.name}")
            else:
                self.say("Nothing is focused right now.")
        elif ak == Kind.HELP:
            self.say("You can say: what's on my screen, open an app, click something, "
                     "type text, save, what changed, stop, or cancel.")
        else:  # DESCRIBE_SCREEN
            self.say(snap.summary())
        self.ctx.last_narrated = snap
        return StepResult("answer", "answered")
