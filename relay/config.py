"""Configuration and per-user storage paths.

All persistent RELAY data lives under a single per-user directory
(``%LOCALAPPDATA%\\RELAY`` on Windows, ``~/.local/share/RELAY`` elsewhere so the
core imports and unit-tests run on any OS). Nothing is written to the source
tree or shared between users. Config is a small, explicit TOML file; there are no
hidden or inferred settings.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path


def user_data_dir() -> Path:
    """Per-user RELAY data directory (created on first use)."""
    override = os.environ.get("RELAY_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "RELAY"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "RELAY"
    base.mkdir(parents=True, exist_ok=True)
    return base


def models_dir() -> Path:
    """Where managed model files live (gitignored). Defaults to ``<app>/models``
    (next to the package, per the RELAY spec), overridable with RELAY_MODELS_DIR.
    Models ship/are downloaded here rather than into per-user config, so a dev
    checkout and a packaged build resolve them the same way."""
    override = os.environ.get("RELAY_MODELS_DIR")
    d = Path(override) if override else Path(__file__).resolve().parent.parent / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Config:
    """Explicit, user-approved settings. Defaults are the Essential-mode profile."""

    # voice
    wake_word: str = "relay"
    push_to_talk_hotkey: str = "ctrl+alt+space"
    speech_rate: float = 1.0
    voice: str = "default"
    language: str = "en"
    # narration
    narration_mode: str = "quick"  # quick | detailed | guided | quiet
    # runtime
    mode: str = "essential"  # essential | enhanced | advanced | connected
    log_level: str = "INFO"
    custom_vocabulary: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Load config.toml from the per-user dir; missing keys fall back to
        defaults, unknown keys are ignored (forward-compatible)."""
        path = path or (user_data_dir() / "config.toml")
        if not path.exists():
            return cls()
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return cls()
        known = {f: data[f] for f in cls().__dataclass_fields__ if f in data}
        return cls(**known)

    def as_dict(self) -> dict:
        return asdict(self)
