"""Speculative Voice Search manager for Relay LiveWorld subsystem.

Reduces voice-to-decision latency by launching background searches during partial speech streaming
as soon as intent and key constraints (origin, destination, date, budget) become stable.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from relay.diagnostics import get_logger
from relay.liveworld.evidence import EvidenceStore
from relay.liveworld.normalizers import normalize_serp_response
from relay.liveworld.planner import SearchPlanner
from relay.liveworld.router import LiveWorldRouter
from relay.liveworld.serpapi import SerpApiClient
from relay.liveworld.types import EvidenceItem, RelayIntent, SearchPlan

log = get_logger("liveworld.speculative")


class SpeculativeSearchManager:
    """Manages speculative background searches for streaming partial speech transcripts."""

    def __init__(self, api_client: SerpApiClient, store: EvidenceStore) -> None:
        self.client = api_client
        self.store = store
        self.router = LiveWorldRouter()
        self.planner = SearchPlanner()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="speculative_search")
        self._lock = threading.Lock()
        self._active_cancel_event: threading.Event | None = None
        self._last_partial_text: str = ""
        self._last_speculative_plan: SearchPlan | None = None
        self._speculative_items: list[EvidenceItem] = []
        self._speculative_intent: RelayIntent | None = None
        self._debounce: threading.Timer | None = None

    def on_partial_transcript(self, partial_text: str, on_speculative_event: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        """Called as STT streams partial recognition results."""
        text = partial_text.strip()
        if not text or text == self._last_partial_text:
            return

        self._last_partial_text = text
        intent = self.router.classify(text)

        if not intent.requires_live_data:
            self.cancel()
            return

        # Check if we have sufficient constraint completeness to speculate
        entities = intent.entities
        has_travel_spec = intent.category == "travel" and ("destination" in entities or "origin" in entities)
        has_shopping_spec = intent.category == "shopping" and len(text.split()) >= 3
        has_local_spec = intent.category in ("local", "news", "research") and len(text.split()) >= 3

        if not (has_travel_spec or has_shopping_spec or has_local_spec):
            return

        with self._lock:
            # Cancel any previous speculative search if text/intent evolved
            if self._active_cancel_event is not None:
                self._active_cancel_event.set()
            if self._debounce is not None:
                self._debounce.cancel()
            self._speculative_items = []

            cancel_event = threading.Event()
            self._active_cancel_event = cancel_event
            self._speculative_intent = intent

        # Create speculative search plan
        plan = self.planner.create_search_plan(intent)
        self._last_speculative_plan = plan
        if not plan.searches:
            return

        if on_speculative_event:
            on_speculative_event("speculative_started", {"text": text, "searches": len(plan.searches)})

        # Launch speculative searches in background
        timer = threading.Timer(
            0.35,
            lambda: self._executor.submit(self._run_speculative, plan, cancel_event, on_speculative_event)
            if not cancel_event.is_set() else None,
        )
        timer.daemon = True
        with self._lock:
            self._debounce = timer
        timer.start()

    def _run_speculative(
        self,
        plan: SearchPlan,
        cancel_event: threading.Event,
        on_event: Callable[[str, dict[str, Any]], None] | None,
    ) -> None:
        if cancel_event.is_set() or not self.client.is_available():
            return

        items: list[EvidenceItem] = []
        for search_item in plan.searches[:3]:
            if cancel_event.is_set():
                log.info("Speculative search cancelled mid-flight for engine=%s", search_item.engine)
                return

            try:
                # Check cache first
                cached = self.store.get_cached(search_item.engine, search_item.params)
                if cached:
                    items.extend(cached)
                    continue

                raw = self.client.search(search_item.engine, search_item.params)
                if cancel_event.is_set():
                    return

                norm = normalize_serp_response(search_item.engine, raw)
                for item in norm:
                    item.metadata["search_params"] = dict(search_item.params)
                self.store.store(search_item.engine, search_item.params, norm)
                items.extend(norm)
            except Exception as e:
                log.warning("Speculative search failed for engine=%s: %s", search_item.engine, e)

        if not cancel_event.is_set():
            with self._lock:
                if cancel_event.is_set() or cancel_event is not self._active_cancel_event:
                    return
                self._speculative_items = items
            log.info("Speculative search completed with %d items", len(items))
            if on_event:
                on_event("speculative_completed", {"itemCount": len(items)})

    def consume_speculative(self, final_intent: RelayIntent) -> list[EvidenceItem] | None:
        """Reuses speculative results if final intent matches speculative intent."""
        plan = self.planner.create_search_plan(final_intent)
        with self._lock:
            if self._active_cancel_event:
                self._active_cancel_event.set()
            if self._debounce:
                self._debounce.cancel()
            items = [
                item for item in self._speculative_items
                if any(
                    item.engine == search.engine
                    and item.metadata.get("search_params") == search.params
                    for search in plan.searches
                )
            ]
            self._speculative_items = []
            self._speculative_intent = None
            return items or None

    def cancel(self) -> None:
        with self._lock:
            if self._active_cancel_event:
                self._active_cancel_event.set()
                self._active_cancel_event = None
            if self._debounce:
                self._debounce.cancel()
                self._debounce = None
            self._speculative_items = []
            self._speculative_intent = None
