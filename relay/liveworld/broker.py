"""LiveWorldBroker orchestrator for Relay.

Central boundary for all live-world operations.
Coordinates routing, multi-engine search planning, SerpApi execution, normalization,
evidence storing, grounded decision making, action provenance generation, and EventBus trace streaming.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from relay.diagnostics import get_logger
from relay.liveworld.evidence import EvidenceStore
from relay.liveworld.normalizers import normalize_serp_response
from relay.liveworld.planner import SearchPlanner
from relay.liveworld.provenance import ProvenanceGenerator
from relay.liveworld.ranking import GroundedDecisionEngine
from relay.liveworld.router import LiveWorldRouter
from relay.liveworld.serpapi import SerpApiClient, SerpApiUnavailableError
from relay.liveworld.speculative import SpeculativeSearchManager
from relay.liveworld.types import EvidenceItem, RelayDecision, RelayIntent, SearchPlan, SearchTelemetry

log = get_logger("liveworld.broker")


class LiveWorldBroker:
    """Master orchestrator for grounded live-world search and decision making."""

    def __init__(self, api_client: SerpApiClient | None = None) -> None:
        self.client = api_client or SerpApiClient()
        self.router = LiveWorldRouter()
        self.planner = SearchPlanner()
        self.store = EvidenceStore()
        self.decision_engine = GroundedDecisionEngine(self.store)
        self.provenance_gen = ProvenanceGenerator()
        self.speculative_mgr = SpeculativeSearchManager(self.client, self.store)
        self._executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="liveworld_broker")

    def process(self, utterance: str, bus: Any = None) -> tuple[RelayIntent, RelayDecision, SearchTelemetry]:
        """Main execution loop for a user query.

        Args:
            utterance: Natural speech utterance from user
            bus: Optional EventBus for streaming real-time trace events to UI

        Returns:
            Tuple of (RelayIntent, RelayDecision, SearchTelemetry)
        """
        t_start = time.perf_counter()
        telemetry = SearchTelemetry()

        def emit_trace(stage: str, event_type: str, data: dict[str, Any]) -> None:
            if bus is not None:
                bus.publish(
                    "liveworld.trace",
                    {
                        "stage": stage,
                        "type": event_type,
                        "data": data,
                        "timestamp": time.strftime("%H:%M:%S"),
                    },
                )

        emit_trace("UNDERSTANDING", "intent_started", {"utterance": utterance})

        # Step 1: Classify intent
        t0 = time.perf_counter()
        intent = self.router.classify(utterance)
        telemetry.intent_latency_ms = (time.perf_counter() - t0) * 1000.0

        emit_trace(
            "UNDERSTANDING",
            "intent_classified",
            {
                "intent": intent.to_dict(),
                "requiresLiveData": intent.requires_live_data,
                "category": intent.category,
            },
        )

        # Fail closed if query requires live data but SerpApi is unavailable or disconnected
        if intent.requires_live_data and not self.client.is_available():
            log.warning("Fail-closed triggered: live world access requested but SerpApi unavailable.")
            emit_trace("ERROR", "serpapi_unavailable", {"reason": "SerpApi connection unavailable"})

            refusal_decision = RelayDecision(
                answer="I understood the request, but live-world access is unavailable, so I can't verify current results.",
                confidence=0.0,
                evidence_ids=[],
                action={"type": "none", "target": "", "label": ""},
                provenance={"why": ["SerpApi connection unavailable or disabled"], "sources": [], "freshness": "Unavailable"},
            )
            telemetry.total_latency_ms = (time.perf_counter() - t_start) * 1000.0
            return intent, refusal_decision, telemetry

        # Step 2: Create search plan
        emit_trace("PLANNING", "plan_started", {"objective": intent.objective})
        plan = self.planner.create_search_plan(intent)
        emit_trace("PLANNING", "plan_created", {"plan": plan.to_dict(), "searchCount": len(plan.searches)})

        # Step 3: Check speculative cache reuse
        speculative_items = self.speculative_mgr.consume_speculative(intent)
        evidence_items: list[EvidenceItem] = []
        if speculative_items:
            evidence_items.extend(speculative_items)
            emit_trace("SEARCHING", "speculative_reused", {"count": len(speculative_items)})

        # Step 4: Execute multi-engine searches concurrently
        emit_trace("SEARCHING", "search_execution_started", {"engines": [s.engine for s in plan.searches]})
        telemetry.time_to_first_search_ms = (time.perf_counter() - t_start) * 1000.0

        futures = {}
        for search_item in plan.searches:
            # Check cache
            cached = self.store.get_cached(search_item.engine, search_item.params)
            if cached:
                evidence_items.extend(cached)
                emit_trace(
                    "SEARCHING",
                    "search_cache_hit",
                    {"engine": search_item.engine, "resultCount": len(cached)},
                )
            else:
                emit_trace("SEARCHING", "engine_request_sent", {"engine": search_item.engine, "reason": search_item.reason})
                f = self._executor.submit(self._execute_single_search, search_item.engine, search_item.params)
                futures[f] = search_item

        for future in as_completed(futures):
            search_item = futures[future]
            try:
                engine, duration_ms, items = future.result()
                telemetry.search_durations_ms[engine] = duration_ms
                evidence_items.extend(items)
                self.store.store(engine, search_item.params, items)
                emit_trace(
                    "SEARCHING",
                    "engine_search_completed",
                    {
                        "engine": engine,
                        "resultCount": len(items),
                        "durationMs": round(duration_ms, 1),
                    },
                )
            except Exception as e:
                log.error("Engine search failed for %s: %s", search_item.engine, e)
                emit_trace("SEARCHING", "engine_search_failed", {"engine": search_item.engine, "error": str(e)})

        telemetry.total_searches = len(plan.searches)
        telemetry.candidate_count = len(evidence_items)

        emit_trace("VERIFYING", "evidence_normalized", {"candidateCount": len(evidence_items)})

        # Step 5: Grounded Decision Making
        emit_trace("DECIDING", "decision_started", {"candidateCount": len(evidence_items)})
        t_decide = time.perf_counter()
        decision = self.decision_engine.decide(intent, evidence_items)
        telemetry.decision_latency_ms = (time.perf_counter() - t_decide) * 1000.0

        # Step 6: Generate Action Provenance
        provenance = self.provenance_gen.build_provenance(decision, evidence_items)
        decision.provenance = provenance

        emit_trace(
            "READY",
            "decision_completed",
            {
                "answer": decision.answer,
                "evidenceIds": decision.evidence_ids,
                "action": decision.action,
                "provenance": provenance,
            },
        )

        telemetry.total_latency_ms = (time.perf_counter() - t_start) * 1000.0

        if bus is not None:
            bus.publish("liveworld.decision", decision.to_dict())
            bus.publish("liveworld.telemetry", telemetry.to_dict())

        return intent, decision, telemetry

    def _execute_single_search(self, engine: str, params: dict[str, Any]) -> tuple[str, float, list[EvidenceItem]]:
        t0 = time.perf_counter()
        raw = self.client.search(engine, params)
        duration_ms = (time.perf_counter() - t0) * 1000.0
        items = normalize_serp_response(engine, raw)
        return engine, duration_ms, items
