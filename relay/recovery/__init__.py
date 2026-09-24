"""Recovery: turn a before/after observation into a named, explainable problem so
the assistant offers a safe next step instead of blindly retrying."""

from .recovery import Issue, detect, target_missing

__all__ = ["Issue", "detect", "target_missing"]
