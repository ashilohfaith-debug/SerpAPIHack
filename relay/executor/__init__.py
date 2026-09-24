"""Executor: the single central path from a proposed action to the machine,
through the permission gate, preferring native UIA over keyboard over coordinates."""

from .executor import ActionOutcome, Executor
from .input_backend import PyAutoGuiBackend, RecordingBackend

__all__ = ["ActionOutcome", "Executor", "PyAutoGuiBackend", "RecordingBackend"]
