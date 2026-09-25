"""The central executor — the single path from a proposed action to the machine.

Every action passes through here, and every action passes the permission engine
BEFORE it touches input. The action ladder prefers native UIA (invoke / set-value)
over keyboard over coordinates. UIA actions re-locate their target on the UIA thread
immediately before acting (revalidation), so a stale element or a focus change fails
cleanly instead of clicking the wrong place. Nothing here reports success — it only
reports that an action was executed; the Verifier decides whether it worked.

Input injection (typing, keys, clicks) uses Win32 SendInput; arbitrary text goes
through the clipboard (backup/restore), which is more reliable than per-key typing.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from relay.diagnostics import get_logger
from relay.executor import uia_actions
from relay.executor.input_backend import InputBackend, WindowsInputBackend
from relay.memory.journal import ActionJournal, ActionRecord, ExecState
from relay.perception.semantic import UIElement
from relay.safety import Action, PermissionEngine

log = get_logger("executor")
INPUT_BLOCKED = ("the window in front belongs to Windows itself or runs as administrator, "
                 "and Windows doesn't let me type or click in it. Press Alt+Tab to get "
                 "back to your own window, then ask me again")


@dataclass
class ActionOutcome:
    action_id: str
    state: ExecState
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.state in (ExecState.EXECUTED, ExecState.VERIFIED)


class Executor:
    def __init__(self, engine: PermissionEngine, worker, journal: ActionJournal,
                 task_id: str, emergency=None, confirm=None,
                 input_backend: InputBackend | None = None) -> None:
        self.engine = engine
        self.worker = worker
        self.journal = journal
        self.task_id = task_id
        self.emergency = emergency
        self._confirm = confirm  # callable(Decision) -> bool
        self._granted = False    # one-shot confirmation grant (see grant_next_confirmation)
        self.input: InputBackend = input_backend or WindowsInputBackend()
        self._n = 0

    # --- gate + journal -----------------------------------------------------
    def _new_action_id(self) -> str:
        self._n += 1
        return f"{self.task_id}.a{self._n}"

    def grant_next_confirmation(self) -> None:
        """One-shot: allow the very next confirmation-required action to proceed.
        The Session sets this only after the user has said the exact confirmation
        phrase (or completed a keyboard confirm). Consumed by a single _gate call."""
        self._granted = True

    def _gate(self, action: Action) -> tuple[bool, str]:
        if self.emergency is not None and self.emergency.is_engaged:
            return False, "emergency stop engaged"
        dec = self.engine.classify(action)
        if not dec.allowed:
            return False, f"blocked: {dec.reason}"
        if dec.requires_confirmation:
            ok = self._granted or (bool(self._confirm(dec)) if self._confirm else False)
            self._granted = False  # consume the one-shot grant regardless
            if not ok:
                return False, f"not confirmed ({dec.confirmation.value}): {dec.reason}"
        return True, ""

    def _journal(self, action_id: str, state: ExecState, proposed: str, detail: str = "") -> None:
        self.journal.append(ActionRecord(
            task_id=self.task_id, action_id=action_id, execution_state=state,
            proposed_action=proposed, verification_result=detail))

    def _run(self, action: Action, proposed: str, do) -> ActionOutcome:
        """Gate -> journal PROPOSED -> execute -> journal result."""
        aid = self._new_action_id()
        allowed, why = self._gate(action)
        self._journal(aid, ExecState.PROPOSED, proposed)
        if not allowed:
            self._journal(aid, ExecState.CANCELLED, proposed, why)
            return ActionOutcome(aid, ExecState.CANCELLED, why)
        try:
            ok, detail = do()
        except Exception as e:  # execution failure is reported, never hidden
            self._journal(aid, ExecState.FAILED, proposed, str(e))
            return ActionOutcome(aid, ExecState.FAILED, str(e))
        state = ExecState.EXECUTED if ok else ExecState.FAILED
        self._journal(aid, state, proposed, detail)
        return ActionOutcome(aid, state, detail)

    # --- primitives ---------------------------------------------------------
    def launch_app(self, command: str, args: str = "") -> ActionOutcome:
        action = Action(kind="launch_app", target_app=command)

        def do():
            try:
                if args:
                    subprocess.Popen([command, args])
                else:
                    os.startfile(command)  # type: ignore[attr-defined]
            except FileNotFoundError:
                subprocess.Popen([command] + ([args] if args else []))
            return True, f"launched {command}"
        return self._run(action, f"launch_app {command}", do)

    def invoke_element(self, el: UIElement) -> ActionOutcome:
        action = Action(kind="invoke", target_app=el.window_title,
                        target_label=el.name, target_role=el.role)

        def do():
            present, ok = self.worker.run(
                lambda: uia_actions.exists(el.name, el.role, el.bbox), timeout=3)
            if not ok or not present:
                return False, "target not present at execution time (revalidation failed)"
            done, ok2 = self.worker.run(
                lambda: uia_actions.invoke(el.name, el.role, el.bbox), timeout=3)
            return bool(ok2 and done), ("invoked" if done else "invoke pattern unavailable")
        return self._run(action, f"invoke {el.role} {el.name!r}", do)

    def set_element_text(self, el: UIElement, text: str) -> ActionOutcome:
        action = Action(kind="set_value", target_app=el.window_title,
                        target_label=el.name, target_role=el.role, text=text)

        def do():
            done, ok = self.worker.run(
                lambda: uia_actions.set_value(el.name, el.role, el.bbox, text), timeout=3)
            if ok and done:
                return True, "set via UIA ValuePattern"
            # fallback: focus the element then type via keyboard
            self.worker.run(lambda: uia_actions.focus(el.name, el.role, el.bbox), timeout=3)
            self.input.type_text(text)
            return True, "set via keyboard fallback"
        return self._run(action, f"set_value {el.name!r}", do)

    def _input_blocked(self) -> bool:
        """Windows silently drops injected input to an elevated window (UIPI) and
        SendInput doesn't report it, so check first rather than claim a key was pressed."""
        from relay.executor.input_backend import WindowsInputBackend
        if not isinstance(self.input, WindowsInputBackend):
            return False                     # test / recording backends
        from relay.system.windows import foreground_blocks_input
        return foreground_blocks_input()

    def type_text(self, text: str) -> ActionOutcome:
        action = Action(kind="type", text=text)

        def do():
            if self._input_blocked():
                return False, INPUT_BLOCKED
            self.input.type_text(text)
            return True, f"typed {len(text)} chars"
        return self._run(action, "type", do)

    def press(self, key: str, count: int = 1) -> ActionOutcome:
        action = Action(kind="key", text=key)

        def do():
            if self._input_blocked():
                return False, INPUT_BLOCKED
            for _ in range(max(1, count)):
                self.input.press(key)
            return True, f"pressed {key}" + (f" x{count}" if count > 1 else "")
        return self._run(action, f"press {key}", do)

    def hotkey(self, *keys: str, count: int = 1) -> ActionOutcome:
        combo = "+".join(keys)
        action = Action(kind="key", text=combo)

        def do():
            if self._input_blocked():
                return False, INPUT_BLOCKED
            for _ in range(max(1, count)):
                self.input.hotkey(*keys)
            return True, f"hotkey {combo}"
        return self._run(action, f"hotkey {combo}", do)

    def click_coord(self, x: int, y: int, label: str = "") -> ActionOutcome:
        # Last-resort coordinate click. Target label (if known) drives risk.
        action = Action(kind="click", target_label=label)

        def do():
            if self._input_blocked():
                return False, INPUT_BLOCKED
            self.input.click(x, y)
            return True, f"clicked ({x},{y})"
        return self._run(action, f"click ({x},{y})", do)

    # --- everyday system actions (same gate + journal as everything else) ------
    def launch_entry(self, entry, launcher=None) -> ActionOutcome:
        """Launch an installed app from the Start-menu catalog (classic or Store)."""
        action = Action(kind="launch_app", target_app=entry.name)

        def do():
            (launcher or _catalog_launch)(entry)
            return True, f"launched {entry.name}"
        return self._run(action, f"launch_app {entry.name}", do)

    def open_uri(self, uri: str, label: str = "", opener=None) -> ActionOutcome:
        """Open a website, folder or file with its default handler."""
        kind = "open_url" if uri.startswith(("http://", "https://")) else "open_path"
        action = Action(kind=kind, target_app=label)

        def do():
            (opener or os.startfile)(uri)  # type: ignore[attr-defined]
            return True, f"opened {label or uri}"
        return self._run(action, f"{kind} {label or uri}", do)

    def window_op(self, hwnd: int, op: str, label: str = "", ops=None) -> ActionOutcome:
        """activate / minimize / maximize / restore / close (close = the window's own
        X button, so unsaved work triggers the app's save prompt; never a kill)."""
        action = Action(kind=f"window_{op}", target_app=label)

        def do():
            from relay.system import windows as w
            table = ops or {"activate": w.activate, "minimize": w.minimize,
                            "maximize": w.maximize, "restore": w.restore,
                            "close": w.request_close}
            ok = table[op](hwnd)
            return True, f"{op} {'accepted' if ok else 'sent'}"
        return self._run(action, f"window_{op} {label}", do)

    def system(self, what: str, fn, label: str = "") -> ActionOutcome:
        """A system setting change such as volume; ``fn()`` returns True on success."""
        action = Action(kind=f"system_{what}", target_app=label or what)

        def do():
            ok = bool(fn())
            return ok, f"{what} {'changed' if ok else 'unchanged'}"
        return self._run(action, f"system_{what}", do)


def _catalog_launch(entry) -> None:
    from relay.system.apps import AppCatalog
    AppCatalog.launch(entry)
