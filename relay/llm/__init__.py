"""Optional conversational AI through an OpenAI-compatible router (e.g. FreeLLMAPI):
streaming client with persistent connections, latency-first hedged routing with
failover, and an assistant that speaks answers sentence by sentence. RELAY's offline
commands keep working when the network or the router is unavailable."""

from __future__ import annotations

import os

from .assistant import Assistant, validate_command
from .client import LLMClient, Route, RouteError
from .router import NoRoute, Router

__all__ = ["Assistant", "LLMClient", "NoRoute", "Route", "RouteError", "Router",
           "routes_from_config", "validate_command"]


def routes_from_config(cfg) -> list[Route]:
    """Routes from config.toml / environment. RELAY_LLM_URL and RELAY_LLM_KEY override
    the file. The key belongs to the developer's router or gateway — users never need
    one of their own. Empty URL = assistant off (offline commands only)."""
    from relay.envfile import offline_forced
    url = os.environ.get("RELAY_LLM_URL", "").strip() or (cfg.llm_url or "").strip()
    key = os.environ.get("RELAY_LLM_KEY", "").strip() or (cfg.llm_key or "").strip()
    if not url or offline_forced():
        return []
    models = [m for m in (cfg.llm_models or []) if m] or ["auto:fast"]
    headers = {"X-Relay-Device": _device_id()}
    return [Route(name=f"{m}", base_url=url, api_key=key, model=m,
                  timeout=float(cfg.llm_timeout), extra_headers=headers) for m in models]


def _device_id() -> str:
    """A random, anonymous per-install id (lets a gateway rate-limit fairly per device;
    contains nothing about the user)."""
    import uuid

    from relay.config import user_data_dir
    p = user_data_dir() / "device_id"
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        did = uuid.uuid4().hex
        try:
            p.write_text(did, encoding="utf-8")
        except OSError:
            pass
        return did
