"""SerpApi integration client for Relay LiveWorld subsystem.

Features:
  - Official SerpApi JSON integration (https://serpapi.com/search.json)
  - Zero third-party library dependencies (stdlib urllib/json)
  - Supports engines: google, google_shopping, google_maps, google_flights, google_hotels, google_news
  - Redacts API key in logs, exceptions, and string representations
  - Developer disconnect/reconnect toggle mode for live hackathon demo
  - Strict error handling & fail-closed behavior
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from relay.diagnostics import get_logger

log = get_logger("liveworld.serpapi")

BASE_SERPAPI_URL = "https://serpapi.com/search.json"


def _usable_api_key(value: str) -> bool:
    key = (value or "").strip()
    if not key:
        return False
    marker = key.casefold().replace("-", "_")
    return not any(
        placeholder in marker
        for placeholder in ("your_serpapi_key", "replace_me", "change_me", "placeholder")
    )


class SerpApiUnavailableError(Exception):
    """Raised when SerpApi is disconnected, unconfigured, or unreachable."""
    pass


class SerpApiClient:
    """Client for SerpApi multi-engine searches."""

    _disconnected_override: bool = False  # Global demo disconnect toggle

    def __init__(self, api_key: str | None = None, timeout: float = 25.0) -> None:
        self.api_key = api_key or os.getenv("SERPAPI_API_KEY", "").strip()
        self.timeout = timeout

    @classmethod
    def set_disconnected(cls, disconnected: bool) -> None:
        """Toggle developer disconnect mode for demo purposes."""
        cls._disconnected_override = disconnected
        log.info("SerpApi developer disconnect state set to: %s", disconnected)

    @classmethod
    def is_disconnected(cls) -> bool:
        return cls._disconnected_override

    def is_available(self) -> bool:
        """Check if SerpApi key is set and developer mode is not disconnected."""
        if self.is_disconnected():
            return False
        key = self.api_key or os.getenv("SERPAPI_API_KEY", "").strip()
        return _usable_api_key(key)

    def search(
        self,
        engine: str,
        params: dict[str, str | int | float | bool],
    ) -> dict[str, Any]:
        """Execute a single search query against SerpApi.

        Args:
            engine: SerpApi engine (google, google_shopping, google_maps, google_flights, google_hotels, google_news)
            params: Parameters specific to the target engine

        Returns:
            Decoded JSON dictionary from SerpApi.
        """
        if self.is_disconnected():
            raise SerpApiUnavailableError("SerpApi live-world access disabled by developer override.")

        key = self.api_key or os.getenv("SERPAPI_API_KEY", "").strip()
        if not _usable_api_key(key):
            raise SerpApiUnavailableError("SERPAPI_API_KEY environment variable is not configured.")

        query_params: dict[str, str] = {
            "engine": engine,
            "api_key": key,
            "output": "json",
        }

        # Convert parameters to string format for URL encoding
        for k, v in params.items():
            if v is not None and v != "":
                query_params[k] = str(v)

        url = f"{BASE_SERPAPI_URL}?{urllib.parse.urlencode(query_params)}"
        
        # Redact API key for logging
        safe_url = url.replace(urllib.parse.quote_plus(key), "[REDACTED_API_KEY]")
        t0 = time.perf_counter()
        log.info("SerpApi request: engine=%s url=%s", engine, safe_url)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Relay-LiveWorld/1.0 (Hackathon; Windows Voice OS)",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status_code = resp.getcode()
                raw_bytes = resp.read()
                duration = time.perf_counter() - t0
                log.info("SerpApi response: engine=%s HTTP %d in %.2fs (%d bytes)", engine, status_code, duration, len(raw_bytes))
                
                if status_code != 200:
                    raise SerpApiUnavailableError(f"SerpApi HTTP error {status_code}")
                
                data = json.loads(raw_bytes.decode("utf-8"))
                if not isinstance(data, dict):
                    raise SerpApiUnavailableError("SerpApi returned an invalid response object.")
                
                # Check for SerpApi top-level error message
                if "error" in data:
                    err_msg = str(data["error"])
                    safe_err = err_msg.replace(key, "[REDACTED]")
                    raise SerpApiUnavailableError(f"SerpApi returned error: {safe_err}")

                return data

        except urllib.error.HTTPError as e:
            duration = time.perf_counter() - t0
            log.warning("SerpApi HTTP error: engine=%s code=%s in %.2fs", engine, e.code, duration)
            raise SerpApiUnavailableError(f"SerpApi request failed with HTTP status {e.code}")
        except urllib.error.URLError as e:
            duration = time.perf_counter() - t0
            reason = str(e.reason).replace(key, "[REDACTED]").replace(urllib.parse.quote_plus(key), "[REDACTED]")
            log.warning("SerpApi URL error: engine=%s reason=%s in %.2fs", engine, reason, duration)
            raise SerpApiUnavailableError(f"SerpApi network connection error: {reason}")
        except Exception as e:
            duration = time.perf_counter() - t0
            safe_err = str(e).replace(key, "[REDACTED]")
            log.warning("SerpApi failure: engine=%s err=%s in %.2fs", engine, safe_err, duration)
            raise SerpApiUnavailableError(f"SerpApi execution failed: {safe_err}")
