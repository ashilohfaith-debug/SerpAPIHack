"""Load the developer's settings from a `.env` file — one copy-paste, no code changes.

Looks for `.env` next to the app (the folder with RELAY.cmd, or beside relay.exe in a
packaged build) and in the user's RELAY data folder. Simple KEY=VALUE lines; `#`
comments; optional quotes. Values already set in the real environment win, so a
one-off `set SARVAM_API_KEY=...` still overrides the file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def offline_forced() -> bool:
    """RELAY_OFFLINE=1: ignore every key and online service (tests, clean-machine check,
    or a user who wants nothing to leave the PC)."""
    return os.environ.get("RELAY_OFFLINE", "").strip().lower() in ("1", "on", "true", "yes")


def candidate_files() -> list[Path]:
    if getattr(sys, "frozen", False):
        app = Path(sys.executable).resolve().parent
    else:
        app = Path(__file__).resolve().parent.parent
    files = [app / ".env"]
    try:
        from relay.config import user_data_dir
        files.append(user_data_dir() / ".env")
    except Exception:
        pass
    return files


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:                       # trailing comment
            value = value.split(" #", 1)[0].rstrip()
        if key and key.replace("_", "").isalnum():
            out[key] = value
    return out


def load_env(files: list[Path] | None = None) -> list[Path]:
    """Apply every existing .env file (first file wins per key; the real environment
    wins over files). Returns the files that were loaded."""
    loaded = []
    if offline_forced():
        return loaded
    for f in files if files is not None else candidate_files():
        try:
            values = parse(f.read_text(encoding="utf-8-sig"))
        except OSError:
            continue
        for k, v in values.items():
            if v and not os.environ.get(k):
                os.environ[k] = v
        loaded.append(f)
    return loaded
