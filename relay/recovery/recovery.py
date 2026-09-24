"""Basic recovery signals (P5 scope).

Turns a before/after observation pair into a named problem so the assistant can
explain it and choose a safe next step — instead of blindly retrying. Full stuck-
classification and recovery strategies land in P7/P9; here we cover the cases the
first real workflow needs: an unexpected dialog, an action that changed nothing, a
target that vanished, and a lost observation.
"""

from __future__ import annotations

from dataclasses import dataclass

from relay.perception.semantic import ScreenSnapshot


@dataclass(frozen=True)
class Issue:
    kind: str      # unexpected_dialog | no_effect | target_missing | no_observation
    detail: str
    spoken: str    # plain-language explanation for the user


def detect(prev: ScreenSnapshot | None, cur: ScreenSnapshot | None,
           action_ok: bool) -> Issue | None:
    if cur is None:
        return Issue("no_observation", "could not observe the result",
                     "I couldn't read the screen after that, so I'm not sure what happened.")
    if cur.dialogs and (prev is None or not prev.dialogs):
        d = cur.dialogs[0]
        btns = ", ".join(d.buttons) if d.buttons else "no labelled buttons"
        return Issue("unexpected_dialog", f"{d.title} [{btns}]",
                     f"A dialog appeared: {d.title}. Its options are: {btns}. "
                     f"How would you like to proceed?")
    if prev is not None and action_ok and prev.fingerprint() == cur.fingerprint():
        return Issue("no_effect", "screen unchanged after action",
                     "That didn't seem to change anything on screen. "
                     "I won't just try again — do you want me to try a different way?")
    return None


def target_missing(label: str) -> Issue:
    return Issue("target_missing", f"target not present: {label}",
                 f"I couldn't find {label} on the screen any more. "
                 "The window may have changed. Should I look again?")
