"""Tests are hermetic: they never use the developer's real keys from .env or the shell."""

from __future__ import annotations

import pytest

_ONLINE = ("SARVAM_API_KEY", "SARVAM_BASE_URL", "SARVAM_STT", "SARVAM_SPEAKER",
           "SARVAM_LANGUAGE", "SARVAM_TTS_MODEL", "RELAY_LLM_URL", "RELAY_LLM_KEY")


@pytest.fixture(autouse=True)
def _no_online_services(monkeypatch):
    for k in _ONLINE:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RELAY_OFFLINE", "1")        # relay.__main__ won't load .env
    import relay.llm  # never find a real local router
    monkeypatch.setattr(relay.llm, "_LOCAL_PORTS", ())
