"""Latency-first routing across several LLM routes.

Free-tier endpoints have no SLA: the same model can answer in 150 ms or 4 s. So:
  * routes are tried fastest-first, by a learned moving average of time-to-first-token;
  * HEDGING — if the first route hasn't produced a token within ``hedge_after``
    (about 1.5x its usual first-token time, at least 0.5 s), the next route is started
    in parallel; whichever speaks first wins and the other is cancelled. This cuts the
    slow tail dramatically at the cost of an occasional duplicate request;
  * a route that errors or rate-limits (429) is skipped for a cool-down (Retry-After
    when given), so one bad provider can't keep adding delay;
  * if every route fails, NoRoute is raised and RELAY falls back to its offline
    commands — it never hangs waiting on the network.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Iterator

from relay.diagnostics import get_logger
from relay.llm.client import LLMClient, Route, RouteError

log = get_logger("llm.router")


class NoRoute(Exception):
    pass


@dataclass
class _Health:
    ttft: float = 0.8              # learned seconds to first token (EWMA)
    failures: int = 0
    cool_until: float = 0.0


class Router:
    def __init__(self, routes: list[Route], client: LLMClient | None = None,
                 min_hedge: float = 0.5, first_token_timeout: float = 6.0) -> None:
        self.routes = list(routes)
        self.client = client or LLMClient()
        self.min_hedge = min_hedge
        self.first_token_timeout = first_token_timeout
        self.health = {r.name: _Health() for r in self.routes}
        self.last_route = ""
        self.last_ttft = 0.0

    # ---- bookkeeping ----
    def ordered(self) -> list[Route]:
        now = time.monotonic()
        live = [r for r in self.routes if self.health[r.name].cool_until <= now]
        return sorted(live, key=lambda r: self.health[r.name].ttft)

    def _ok(self, name: str, ttft: float) -> None:
        h = self.health[name]
        h.ttft = 0.7 * h.ttft + 0.3 * ttft
        h.failures = 0

    def _fail(self, name: str, err: Exception) -> None:
        h = self.health[name]
        h.failures += 1
        retry = getattr(err, "retry_after", 0.0) or 0.0
        if isinstance(err, RouteError) and err.status == 429:
            h.cool_until = time.monotonic() + max(retry, 20.0)
        elif h.failures >= 2:
            h.cool_until = time.monotonic() + min(120.0, 15.0 * h.failures)
        log.warning("route %s failed: %s", name, err)

    def warm(self) -> None:
        for r in self.routes:
            threading.Thread(target=self.client.warm, args=(r,), daemon=True).start()

    # ---- streaming with hedging ----
    def stream(self, messages: list[dict], max_tokens: int = 300,
               temperature: float = 0.3, cancel: threading.Event | None = None
               ) -> Iterator[str]:
        routes = self.ordered()
        if not routes:
            raise NoRoute("every route is cooling down after errors")
        events: "queue.Queue[tuple]" = queue.Queue()
        cancels: dict[str, threading.Event] = {}
        started: list[str] = []
        t0 = time.monotonic()

        by_name = {r.name: r for r in routes}

        def run(route: Route, ev: threading.Event) -> None:
            try:
                for delta in self.client.stream_chat(route, messages, max_tokens,
                                                     temperature, cancel=ev):
                    events.put(("delta", route.name, delta, time.monotonic()))
                events.put(("done", route.name, None, time.monotonic()))
            except Exception as e:                     # route error, timeout, parse error
                events.put(("error", route.name, e, time.monotonic()))

        def start(route: Route) -> None:
            started.append(route.name)
            ev = cancels[route.name] = threading.Event()   # before the thread runs
            threading.Thread(target=run, args=(route, ev), name=f"llm-{route.name}",
                             daemon=True).start()

        def stop(name: str) -> None:
            cancels[name].set()
            self.client.abort(by_name[name])           # unblock its read right now

        pending = list(routes)
        start(pending.pop(0))
        winner = None
        ended: set[str] = set()                        # routes whose stream is over
        hedge_at = t0 + max(self.min_hedge, 1.5 * self.health[started[0]].ttft)
        deadline = t0 + self.first_token_timeout
        try:
            while winner is None:
                if cancel is not None and cancel.is_set():
                    return
                now = time.monotonic()
                if pending and now >= hedge_at:
                    nxt = pending.pop(0)
                    log.info("hedging: %s slow, also trying %s", started[-1], nxt.name)
                    start(nxt)
                    hedge_at = now + max(self.min_hedge, 1.5 * self.health[nxt.name].ttft)
                if now >= deadline:
                    for name in started:
                        if name not in ended:
                            self._fail(name, TimeoutError("no first token"))
                    raise NoRoute("no route answered in time")
                wait = min(0.1, max(0.005, min(hedge_at if pending else deadline,
                                               deadline) - now))
                try:
                    kind, name, payload, at = events.get(timeout=wait)
                except queue.Empty:
                    continue
                if kind == "delta":
                    winner = name
                    self._ok(name, at - t0)
                    self.last_route, self.last_ttft = name, at - t0
                    for other in list(cancels):        # the loser stops streaming
                        if other != name and other not in ended:
                            stop(other)
                    yield payload
                    continue
                ended.add(name)
                if kind == "error":
                    self._fail(name, payload)
                if pending:                            # fail over at once
                    start(pending.pop(0))
                    hedge_at = time.monotonic() + max(
                        self.min_hedge, 1.5 * self.health[started[-1]].ttft)
                elif ended >= set(started):
                    raise NoRoute(str(payload) if kind == "error" else "empty response")
            # stream the rest of the winner
            last_at = time.monotonic()
            while True:
                if cancel is not None and cancel.is_set():
                    return
                try:
                    kind, name, payload, at = events.get(timeout=0.1)
                except queue.Empty:
                    if time.monotonic() - last_at > self.first_token_timeout:
                        return                          # the stream stalled
                    continue
                if name != winner:
                    continue
                last_at = time.monotonic()
                if kind == "delta":
                    yield payload
                    continue
                ended.add(name)
                if kind == "error":
                    self._fail(name, payload)
                return                                  # keep what was already spoken
        finally:        # stop any stream still running (loser, or caller stopped early)
            for name in list(cancels):
                if name not in ended and not cancels[name].is_set():
                    stop(name)
