"""Streaming client for any OpenAI-compatible /v1 endpoint (e.g. FreeLLMAPI).

Latency matters more than anything here — a blind user is waiting in silence — so:
  * responses are streamed (Server-Sent Events) and consumed token by token;
  * each route keeps one persistent HTTP(S) connection, so repeated requests skip the
    TCP/TLS handshake (often 100-300 ms to a remote server);
  * a request can be cancelled mid-stream (the router cancels the slower of two
    racing routes) by closing its connection.
Stdlib only (http.client) — no SDK dependency.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator
from urllib.parse import urlparse


class RouteError(Exception):
    def __init__(self, route: str, status: int, message: str, retry_after: float = 0.0):
        super().__init__(f"{route}: HTTP {status} {message}")
        self.route = route
        self.status = status
        self.message = message
        self.retry_after = retry_after


@dataclass
class Route:
    """One way to reach a model: an endpoint + key + model name. FreeLLMAPI's own
    router models ("auto:fast", "auto") make good separate routes to race."""

    name: str
    base_url: str  # e.g. http://localhost:3001/v1
    api_key: str = ""
    model: str = "auto:fast"
    timeout: float = 20.0
    extra_headers: dict = field(default_factory=dict)
    ttft_hint: float = 0.0  # measured first-token time (seeds the router's order)

    def __repr__(self) -> str:  # never print the key
        return f"Route({self.name!r}, {self.base_url!r}, model={self.model!r})"


class _Conn:
    """One persistent connection per route (reconnects transparently)."""

    def __init__(self, base_url: str, timeout: float) -> None:
        u = urlparse(base_url)
        self.https = u.scheme == "https"
        self.host = u.hostname or "localhost"
        self.port = u.port or (443 if self.https else 80)
        self.prefix = u.path.rstrip("/")
        self.timeout = timeout
        self._c: http.client.HTTPConnection | None = None
        self.lock = threading.Lock()

    def get(self) -> http.client.HTTPConnection:
        if self._c is None:
            cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
            self._c = cls(self.host, self.port, timeout=self.timeout)
        return self._c

    def drop(self) -> None:
        if self._c is not None:
            try:
                self._c.close()
            except Exception:
                pass
            self._c = None

    def abort(self) -> None:
        """From ANOTHER thread: unblock a read waiting on this socket right now (a
        cancelled stream must not hold the connection until its timeout)."""
        c = self._c
        self._c = None  # the next request opens a fresh connection
        sock = getattr(c, "sock", None) if c is not None else None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class LLMClient:
    def __init__(self) -> None:
        self._conns: dict[str, _Conn] = {}
        self._lock = threading.Lock()

    def _conn(self, route: Route) -> _Conn:
        with self._lock:
            c = self._conns.get(route.name)
            if c is None:
                c = self._conns[route.name] = _Conn(route.base_url, route.timeout)
            return c

    def abort(self, route: Route) -> None:
        """Stop a stream on ``route`` immediately (used with its cancel event)."""
        with self._lock:
            c = self._conns.get(route.name)
        if c is not None:
            c.abort()

    def warm(self, route: Route) -> None:
        """Open the connection early (DNS + TCP + TLS) with a cheap request."""
        conn = self._conn(route)
        with conn.lock:
            try:
                c = conn.get()
                c.request("GET", conn.prefix + "/models", headers=self._headers(route))
                c.getresponse().read()
            except Exception:
                conn.drop()

    @staticmethod
    def _headers(route: Route) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "RELAY/0.3",
            **route.extra_headers,
        }
        if route.api_key:
            h["Authorization"] = f"Bearer {route.api_key}"
        return h

    def stream_chat(
        self,
        route: Route,
        messages: list[dict],
        max_tokens: int = 300,
        temperature: float = 0.3,
        cancel: threading.Event | None = None,
    ) -> Iterator[str]:
        """Yield text deltas as the model produces them."""
        conn = self._conn(route)
        body = json.dumps(
            {
                "model": route.model,
                "messages": messages,
                "stream": True,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        conn.lock.acquire()
        try:
            for attempt in (0, 1):  # one retry if a kept-alive socket went stale
                try:
                    c = conn.get()
                    c.request(
                        "POST",
                        conn.prefix + "/chat/completions",
                        body=body,
                        headers=self._headers(route),
                    )
                    resp = c.getresponse()
                    break
                except (
                    http.client.RemoteDisconnected,
                    ConnectionResetError,
                    ConnectionAbortedError,
                    BrokenPipeError,
                    http.client.CannotSendRequest,
                ):
                    conn.drop()  # a stale kept-alive socket: retry once
                    if attempt:
                        raise RouteError(route.name, 0, "connection lost") from None
                except (OSError, http.client.HTTPException) as e:
                    conn.drop()
                    raise RouteError(route.name, 0, f"unreachable ({type(e).__name__})") from None
            if resp.status != 200:
                text = resp.read().decode("utf-8", "replace")[:300]
                retry = float(resp.headers.get("Retry-After") or 0) if resp.status == 429 else 0.0
                if resp.headers.get("Connection", "").lower() == "close":
                    conn.drop()
                raise RouteError(route.name, resp.status, text, retry)
            yield from self._sse(resp, cancel, conn)
        finally:
            conn.lock.release()

    @staticmethod
    def _sse(resp, cancel, conn) -> Iterator[str]:
        buf = b""
        while True:
            if cancel is not None and cancel.is_set():
                conn.drop()  # abandon the stream; free the socket
                return
            try:
                chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
            except (OSError, http.client.HTTPException):
                conn.drop()
                if cancel is not None and cancel.is_set():
                    return  # we aborted it ourselves
                raise
            if not chunk:
                conn.drop()  # ended without [DONE]: don't reuse
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    resp.read()  # drain so the socket can be reused
                    return
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0].get("delta") or {}
                    text = delta.get("content") or ""
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
                if text:
                    yield text


def now() -> float:
    return time.monotonic()
