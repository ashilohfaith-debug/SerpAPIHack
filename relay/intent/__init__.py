"""Deterministic intent understanding (no LLM)."""

from .grammar import Intent, Kind, parse

__all__ = ["Intent", "Kind", "parse"]
