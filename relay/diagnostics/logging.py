"""Structured, privacy-preserving logging.

Logs go to the per-user data dir, never the source tree. A redaction filter drops
values that look like secrets (passwords, OTPs, tokens) so sensitive screen or
input content never lands in a log file. RELAY must never log what it must not
speak.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from relay.config import user_data_dir

_CONFIGURED = False

# Conservative redaction: mask the VALUE after a sensitive key. Additive only —
# a false mask costs nothing; a missed secret is a privacy breach.
_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|pwd|otp|pin|cvv|token|secret|api[_-]?key)\b\s*[:=]\s*\S+"),
    re.compile(r"\b\d{4,8}\b(?=\s*(otp|code|pin))", re.IGNORECASE),
    re.compile(r"<untrusted_screen_content>[\s\S]*?</untrusted_screen_content>", re.IGNORECASE),
]


class _RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for pat in _SECRET_PATTERNS:
            msg = pat.sub("[REDACTED]", msg)
        record.msg = msg
        record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once: rotating file in the per-user dir + stderr."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    log_path = user_data_dir() / "relay.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_h = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_h.setFormatter(fmt)
    file_h.addFilter(_RedactionFilter())

    stream_h = logging.StreamHandler()
    stream_h.setFormatter(fmt)
    stream_h.addFilter(_RedactionFilter())

    root = logging.getLogger("relay")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(file_h)
    root.addHandler(stream_h)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced RELAY logger (``relay.<name>``)."""
    return logging.getLogger(f"relay.{name}")
