"""Optional conversational AI through an OpenAI-compatible router (e.g. FreeLLMAPI):
streaming client with persistent connections, latency-first hedged routing with
failover, and an assistant that speaks answers sentence by sentence. RELAY's offline
commands keep working when the network or the router is unavailable."""

from __future__ import annotations

import os

from .assistant import Assistant, validate_command
from .client import LLMClient, Route, RouteError
from .router import NoRoute, Router

__all__ = [
    "Assistant",
    "LLMClient",
    "NoRoute",
    "Route",
    "RouteError",
    "Router",
    "routes_from_config",
    "validate_command",
]


def routes_from_config(cfg) -> list[Route]:
    """Routes from config.toml / environment / DPAPI secrets. RELAY_LLM_URL and RELAY_LLM_KEY
    (or FREELLMAPI_KEY/URL, GROQ_API_KEY, OPENAI_API_KEY) override the file. Multiple providers
    and backup endpoints are supported with automatic racing and failover. Empty URL = assistant off."""
    from relay.envfile import offline_forced
    from relay.memory.secrets import get_secret

    key = (
        os.environ.get("RELAY_LLM_KEY", "").strip()
        or get_secret("RELAY_LLM_KEY", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
        or get_secret("GEMINI_API_KEY", "").strip()
        or os.environ.get("FREELLMAPI_KEY", "").strip()
        or get_secret("FREELLMAPI_KEY", "").strip()
        or os.environ.get("GROQ_API_KEY", "").strip()
        or get_secret("GROQ_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
        or get_secret("OPENAI_API_KEY", "").strip()
        or (cfg.llm_key or "").strip()
    )
    url = (
        os.environ.get("RELAY_LLM_URL", "").strip()
        or get_secret("RELAY_LLM_URL", "").strip()
        or os.environ.get("FREELLMAPI_URL", "").strip()
        or get_secret("FREELLMAPI_URL", "").strip()
        or (cfg.llm_url or "").strip()
    )
    if key.startswith("#") or "REDACTED" in key:
        key = ""
    if url.startswith("#") or "REDACTED" in url:
        url = ""
    if (not url or url.startswith("http://127.0.0.1:31415")) and key:
        if key.startswith(("AIzaSy", "AQ.")):
            url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        elif key.startswith("gsk_"):
            url = "https://api.groq.com/openai/v1"
        elif key.startswith("sk-"):
            url = "https://api.openai.com/v1"
        else:
            url = "http://127.0.0.1:31415/v1"
    if not url or offline_forced():
        return []
    url = _local_router(url)
    models = [m for m in (cfg.llm_models or []) if m]
    if not models or models == ["auto:fast", "auto"]:
        if "googleapis.com" in url.lower():
            models = ["gemini-3.8-flash", "gemini-flash-latest"]
        elif "groq.com" in url.lower():
            models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
        elif "openai.com" in url.lower():
            models = ["gpt-4o-mini", "gpt-3.5-turbo"]
        else:
            models = ["auto:fast", "auto"]
    hints: dict[str, float] = {}
    if models == ["auto:fast", "auto"]:  # default: use the tuned ranking
        from relay.llm.tune import best_models

        fastest = best_models(url, 3)  # e.g. gemini-3.5-flash-lite 1.6 s
        if fastest:
            hints = dict(fastest)
            hints["auto:fast"] = max(hints.values()) + 1.0  # the router's own pick: last
            models = [m for m, _t in fastest] + ["auto:fast"]
    headers = {"X-Relay-Device": _device_id()}
    routes = [
        Route(
            name=f"{m}",
            base_url=url,
            api_key=key,
            model=m,
            timeout=float(cfg.llm_timeout),
            extra_headers=headers,
            ttft_hint=hints.get(m, 0.0),
        )
        for m in models
    ]

    # Check for backup provider endpoint
    backup_url = (
        os.environ.get("RELAY_BACKUP_LLM_URL", "").strip()
        or get_secret("RELAY_BACKUP_LLM_URL", "").strip()
    )
    backup_key = (
        os.environ.get("RELAY_BACKUP_LLM_KEY", "").strip()
        or get_secret("RELAY_BACKUP_LLM_KEY", "").strip()
        or key
    )
    if backup_url and backup_url != url:
        backup_url = _local_router(backup_url)
        for m in ["auto:fast", "auto"]:
            routes.append(
                Route(
                    name=f"backup:{m}",
                    base_url=backup_url,
                    api_key=backup_key,
                    model=m,
                    timeout=float(cfg.llm_timeout),
                    extra_headers=headers,
                    ttft_hint=hints.get(m, 0.0) + 2.0,  # try primary first
                )
            )
    gemini_k = os.environ.get("GEMINI_API_KEY", "").strip() or get_secret("GEMINI_API_KEY", "").strip()
    if gemini_k and "googleapis.com" not in url.lower():
        for gm in ["gemini-3.8-flash", "gemini-flash-latest"]:
            routes.append(
                Route(
                    name=f"gemini-{gm}",
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    api_key=gemini_k,
                    model=gm,
                    timeout=float(cfg.llm_timeout),
                    extra_headers=headers,
                    ttft_hint=1.2,
                )
            )
    groq_k = os.environ.get("GROQ_API_KEY", "").strip() or get_secret("GROQ_API_KEY", "").strip()
    if groq_k and "groq.com" not in url.lower():
        routes.append(
            Route(
                name="groq-fast",
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_k,
                model="qwen/qwen3.8-27b",
                timeout=float(cfg.llm_timeout),
                extra_headers=headers,
                ttft_hint=0.8,
            )
        )
    return routes


_LOCAL_PORTS = (31415, 3001)  # FreeLLMAPI desktop app, then Docker / source


def _listening(host: str, port: int) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _local_router(url: str) -> str:
    """A router on THIS computer at the wrong port (the FreeLLMAPI desktop app uses
    31415, Docker and source installs 3001): use the port that is actually open."""
    from urllib.parse import urlparse

    u = urlparse(url)
    host = u.hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1") or not u.port:
        return url
    if _listening(host, u.port):
        return url
    for port in _LOCAL_PORTS:
        if port != u.port and _listening("127.0.0.1", port):
            return url.replace(f"{host}:{u.port}", f"127.0.0.1:{port}", 1)
    return url


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
