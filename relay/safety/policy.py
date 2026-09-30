"""Risk classification and the permission engine.

This is the safety-critical core and is deliberately a pure, deterministic
function of the proposed action — no LLM, no network, no side effects. The
planner proposes; this engine classifies; only the executor acts, and only after
this engine (and, for higher tiers, an accessible confirmation) allows it.

Risk tiers (adapted from clacky's MIT four-tier model, extended per the RELAY
spec §8):

  SAFE       read-only / navigation                     -> run
  REVERSIBLE undoable mutation (journaled file move)     -> run (+journal)
  CAUTION    irreversible but routine, identified target -> run, but NARRATE first
  CONFIRM    unidentified click / ambiguous target       -> simple spoken confirm
  ELEVATED   high-stakes, irreversible/external          -> action-specific PHRASE
  BLOCKED    forbidden (bypass security, captcha, …)      -> never

Key honesty rules encoded here:
  * Danger is a property of the TARGET control, not of typed text. Typing the
    word "delete" is not dangerous; clicking a control labelled "Delete" is.
  * A click whose target we could not identify is treated as needing confirmation
    (default-deny) — we do not act on what we cannot reason about.
  * A bare "yes" is never sufficient for ELEVATED actions (see ConfirmationStrength).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Risk(str, Enum):
    SAFE = "safe"
    REVERSIBLE = "reversible"
    CAUTION = "caution"
    CONFIRM = "confirm"
    ELEVATED = "elevated"
    BLOCKED = "blocked"


class ConfirmationStrength(str, Enum):
    NONE = "none"  # run
    NARRATE = "narrate"  # announce, then run (no undo)
    SIMPLE = "simple"  # spoken yes/no is acceptable
    PHRASE = "phrase"  # action-specific spoken phrase required (not a bare "yes")
    KEYBOARD = "keyboard"  # trusted keyboard confirmation / Windows auth flow


# Read-only / navigational action kinds — no state change.
READONLY_KINDS = frozenset(
    {
        "screenshot",
        "observe",
        "read",
        "read_element",
        "read_screen",
        "focus",
        "cursor_position",
        "mouse_move",
        "move",
        "scroll",
        "hover",
        "wait",
        "narrate",
        "say",
        "point",
        "list_elements",
        "get_value",
    }
)

# Mutating actions that act at/through a specific target element.
TARGETED_KINDS = frozenset(
    {
        "click",
        "left_click",
        "double_click",
        "right_click",
        "invoke",
        "toggle",
        "select",
        "set_value",
        "type",
        "key",
        "expand",
        "collapse",
        "drag",
    }
)

# Kinds that are always high-stakes regardless of the target label.
ELEVATED_KINDS = frozenset(
    {
        "delete_file",
        "send_message",
        "send_email",
        "purchase",
        "pay",
        "transfer",
        "install",
        "uninstall",
        "run_downloaded",
        "share_personal",
        "change_security_setting",
    }
)

# The most sensitive kinds require a keyboard / Windows auth confirmation, not voice.
KEYBOARD_CONFIRM_KINDS = frozenset(
    {
        "purchase",
        "pay",
        "transfer",
        "install",
        "run_downloaded",
        "change_security_setting",
    }
)

# Kinds RELAY refuses outright.
BLOCKED_KINDS = frozenset(
    {
        "bypass_captcha",
        "solve_captcha",
        "disable_security",
        "bypass_uac",
        "secure_desktop_input",
    }
)

# Substrings in a target control's name/role marking an irreversible, high-stakes
# control. Case-insensitive. Conservative + additive: a false ELEVATED costs one
# confirmation; a false SAFE could send an email or delete a file.
DANGER_LABELS = (
    "send",
    "delete",
    "remove",
    "discard",
    "trash",
    "erase",
    "wipe",
    "empty",
    "buy",
    "purchase",
    "pay",
    "checkout",
    "place order",
    "order now",
    "subscribe",
    "submit",
    "confirm",
    "publish",
    "post",
    "share",
    "uninstall",
    "install",
    "format",
    "permanent",
    "delete forever",
    "unsubscribe",
    "deactivate",
    "close account",
    "delete account",
    "transfer",
    "withdraw",
    "sign out",
    "log out",
)

# Field-name / role hints for protected (never-read, never-store) content.
_PROTECTED_HINTS = (
    "password",
    "passwd",
    "pwd",
    "otp",
    "one-time",
    "pin",
    "cvv",
    "security code",
    "secret",
    "token",
    "passcode",
)


@dataclass(frozen=True)
class Action:
    """A proposed action, before execution. Target fields come from the UIA
    element under the action point (P4). Empty target on a targeted kind means
    'unidentified' -> default-deny."""

    kind: str
    target_app: str = ""
    target_label: str = ""
    target_role: str = ""
    text: str = ""  # payload for type/set_value (NOT danger-scanned)
    is_password_field: bool = False  # from UIA IsPassword, when known
    reversible: bool = False  # e.g. a journaled file move
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    risk: Risk
    confirmation: ConfirmationStrength
    reason: str
    allowed: bool  # False only for BLOCKED
    spoken_summary: str = ""  # what to announce for confirmation

    @property
    def requires_confirmation(self) -> bool:
        return self.confirmation in (
            ConfirmationStrength.SIMPLE,
            ConfirmationStrength.PHRASE,
            ConfirmationStrength.KEYBOARD,
        )


def is_protected_field(role: str = "", name: str = "", is_password_field: bool = False) -> bool:
    """Detect password/OTP/token fields whose value must never be read aloud,
    logged or stored."""
    if is_password_field:
        return True
    hay = f"{role} {name}".lower()
    return any(h in hay for h in _PROTECTED_HINTS)


class PermissionEngine:
    """Classifies actions and produces permission Decisions. Pure and stateless."""

    def classify(self, action: Action) -> Decision:
        kind = action.kind.strip().lower()

        if kind in BLOCKED_KINDS:
            return Decision(
                Risk.BLOCKED,
                ConfirmationStrength.NONE,
                f"'{kind}' is not permitted",
                allowed=False,
                spoken_summary="",
            )

        if kind in READONLY_KINDS:
            return Decision(Risk.SAFE, ConfirmationStrength.NONE, "read-only", allowed=True)

        label = (action.target_label or "").lower()
        role = (action.target_role or "").lower()
        haystack = f"{label} {role}"
        target_desc = action.target_label or action.target_role or "an unlabelled control"
        app = action.target_app or "the current app"

        # Always-high-stakes kinds.
        if kind in ELEVATED_KINDS:
            strength = (
                ConfirmationStrength.KEYBOARD
                if kind in KEYBOARD_CONFIRM_KINDS
                else ConfirmationStrength.PHRASE
            )
            return Decision(
                Risk.ELEVATED,
                strength,
                f"'{kind}' is irreversible/high-stakes",
                allowed=True,
                spoken_summary=self._summary(kind, target_desc, app, high=True),
            )

        # Danger-labelled target control -> elevated.
        if any(p in haystack for p in DANGER_LABELS):
            return Decision(
                Risk.ELEVATED,
                ConfirmationStrength.PHRASE,
                f"target control looks high-stakes: {target_desc!r}",
                allowed=True,
                spoken_summary=self._summary(kind, target_desc, app, high=True),
            )

        # Journaled reversible mutation.
        if action.reversible:
            return Decision(
                Risk.REVERSIBLE, ConfirmationStrength.NONE, "reversible (journaled)", allowed=True
            )

        # Targeted action with no identified target -> default-deny (confirm).
        if kind in TARGETED_KINDS and not label and kind not in ("type", "key"):
            return Decision(
                Risk.CONFIRM,
                ConfirmationStrength.SIMPLE,
                "target could not be identified",
                allowed=True,
                spoken_summary=self._summary(kind, target_desc, app, high=False),
            )

        # Routine, identified GUI mutation (or typing/keys) -> run, narrate first.
        return Decision(
            Risk.CAUTION,
            ConfirmationStrength.NARRATE,
            "routine identified mutation",
            allowed=True,
            spoken_summary=self._summary(kind, target_desc, app, high=False),
        )

    @staticmethod
    def _summary(kind: str, target: str, app: str, high: bool) -> str:
        verb = {
            "invoke": "click",
            "set_value": "change",
            "key": "press",
            "delete_file": "delete",
            "launch_app": "open",
        }.get(kind, kind.replace("_", " "))
        if high:
            return f"I am about to {verb} {target} in {app}. This can't be undone."
        return f"{verb} {target} in {app}."
