"""Accessibility: narration modes, spoken onboarding, screen-reader coexistence,
and the accessible spoken-confirmation flow."""

from .coexist import coexistence_advice, screen_reader_running
from .confirm import PendingConfirmation, confirmation_phrase, is_cancel
from .onboarding import is_first_run, mark_onboarded, onboarding_script

__all__ = [
    "screen_reader_running",
    "coexistence_advice",
    "PendingConfirmation",
    "confirmation_phrase",
    "is_cancel",
    "onboarding_script",
    "is_first_run",
    "mark_onboarded",
]
