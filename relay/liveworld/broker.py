"""LiveWorldBroker orchestrator for Relay.

Central boundary for all live-world operations.
Coordinates routing, multi-engine search planning, SerpApi execution, normalization,
evidence storing, grounded decision making, action provenance generation, and EventBus trace streaming.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from relay.diagnostics import get_logger
from relay.liveworld.evidence import EvidenceStore
from relay.liveworld.normalizers import normalize_flight_booking_options, normalize_serp_response
from relay.liveworld.planner import SearchPlanner
from relay.liveworld.provenance import ProvenanceGenerator
from relay.liveworld.ranking import GroundedDecisionEngine
from relay.liveworld.router import LiveWorldRouter
from relay.liveworld.serpapi import SerpApiClient
from relay.liveworld.speculative import SpeculativeSearchManager
from relay.liveworld.types import (
    EvidenceItem,
    RelayDecision,
    RelayIntent,
    SearchTelemetry,
)

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
        self._last_intent: RelayIntent | None = None
        self._last_decision: RelayDecision | None = None
        self._pending_intent: RelayIntent | None = None

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
                bus.emit(
                    "liveworld.trace",
                    stage=stage,
                    type=event_type,
                    data=data,
                    timestamp=time.strftime("%H:%M:%S"),
                )

        emit_trace("UNDERSTANDING", "intent_started", {"utterance": utterance})

        # Step 1: Classify intent
        t0 = time.perf_counter()
        intent = self.classify(utterance)
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
            if bus is not None:
                bus.emit("liveworld.status", connected=False)

            refusal_decision = RelayDecision(
                answer="I understood the request, but live-world access is unavailable, so I can't verify current results.",
                confidence=0.0,
                evidence_ids=[],
                action={"type": "none", "target": "", "label": ""},
                provenance={"why": ["SerpApi connection unavailable or disabled"], "sources": [], "freshness": "Unavailable"},
            )
            telemetry.total_latency_ms = (time.perf_counter() - t_start) * 1000.0
            if bus is not None:
                bus.emit("liveworld.decision", **refusal_decision.to_dict(), evidence=[])
                bus.emit("liveworld.telemetry", **telemetry.to_dict())
            self._last_intent, self._last_decision = intent, refusal_decision
            return intent, refusal_decision, telemetry

        missing = self.planner.missing_travel_details(intent)
        if missing:
            labels = {
                "origin": "departure city",
                "destination": "destination",
                "date": "travel date",
                "origin_airport": "departure airport or three-letter code",
                "destination_airport": "destination airport or three-letter code",
            }
            needed = ", ".join(labels[item] for item in missing)
            clarification = RelayDecision(
                answer=f"Before I search live travel options, tell me the {needed}.",
                confidence=0.0,
                evidence_ids=[],
                action={"type": "none", "target": "", "label": ""},
            )
            telemetry.total_latency_ms = (time.perf_counter() - t_start) * 1000.0
            emit_trace("PLANNING", "clarification_required", {"missing": missing})
            if bus is not None:
                bus.emit("liveworld.decision", **clarification.to_dict(), evidence=[])
                bus.emit("liveworld.telemetry", **telemetry.to_dict())
            self._last_intent, self._last_decision = intent, clarification
            self._pending_intent = intent
            return intent, clarification, telemetry
        self._pending_intent = None

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

        evidence_items = list({item.id: item for item in evidence_items}.values())
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
            cited = [self.store.get_by_id(item_id) for item_id in decision.evidence_ids]
            bus.emit(
                "liveworld.decision",
                **decision.to_dict(),
                evidence=[item.to_dict() for item in cited if item is not None],
            )
            bus.emit("liveworld.telemetry", **telemetry.to_dict())

        self._last_intent, self._last_decision = intent, decision
        return intent, decision, telemetry

    def classify(self, utterance: str) -> RelayIntent:
        """Classify a request with prior live-result context when applicable."""
        return self._intent_with_follow_up(utterance)

    def _intent_with_follow_up(self, utterance: str) -> RelayIntent:
        """Keep live context for short alternatives such as "find a cheaper one"."""
        intent = self.router.classify(utterance)
        low = utterance.lower()
        date_reply = bool(re.fullmatch(
            r"(?:on\s+)?(?:today|tomorrow|tonight|next\s+week|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})[.!?]?",
            low.strip(),
        ))
        if (
            self._pending_intent
            and (intent.category == "general" or date_reply)
            and len(low.split()) <= 8
        ):
            previous = self._pending_intent
            missing = self.planner.missing_travel_details(previous)
            fragment = utterance.strip().strip(".!?")
            if len(missing) == 1 and missing[0] in ("origin", "origin_airport"):
                if not re.search(r"\bfrom\b", low):
                    fragment = f"from {fragment}"
            elif len(missing) == 1 and missing[0] in ("destination", "destination_airport"):
                if not re.search(r"\bto\b", low):
                    fragment = f"to {fragment}"
            elif len(missing) == 1 and missing[0] == "date":
                if not re.search(r"\b(?:today|tomorrow|tonight|next\s+week|on\b)", low):
                    fragment = f"on {fragment}"
            updates, constraints = self.router._extract_entities_and_constraints(
                fragment, fragment.lower(), "travel"
            )
            if date_reply and "date" in missing:
                updates["date"] = re.sub(r"^on\s+", "", fragment.lower())
            if updates:
                return RelayIntent(
                    True,
                    previous.category,
                    previous.objective,
                    entities={**previous.entities, **updates},
                    constraints={**previous.constraints, **constraints},
                    confidence=previous.confidence,
                )
        is_follow_up = bool(
            self._last_intent
            and intent.category != "local_action"
            and not intent.entities
            and re.search(r"\b(?:cheaper|another|alternative|different|earlier|later)\b", low)
            and len(low.split()) <= 10
        )
        if not is_follow_up:
            return intent
        previous = self._last_intent
        constraints = {**previous.constraints, **intent.constraints}
        if "cheap" in low:
            constraints["prefer"] = "cheapest"
        if self._last_decision:
            constraints["exclude_evidence_ids"] = list(self._last_decision.evidence_ids)
            from relay.liveworld.evidence import evidence_fingerprint

            prior_items = [self.store.get_by_id(item_id) for item_id in self._last_decision.evidence_ids]
            constraints["exclude_evidence_fingerprints"] = [
                evidence_fingerprint(item) for item in prior_items if item is not None
            ]
        return RelayIntent(
            requires_live_data=True,
            category=previous.category,
            objective=f"{previous.objective} Follow-up: {utterance}",
            entities=dict(previous.entities),
            constraints=constraints,
            confidence=min(previous.confidence, 0.95),
        )

    def selected_action(self, engine: str | None = None) -> dict[str, Any] | None:
        """Return an action backed by the current decision's cited evidence."""
        decision = self._last_decision
        if decision is None:
            return None
        if engine is None:
            action = decision.action or {}
            item = self.store.get_by_id(str(action.get("evidenceId") or ""))
            if item and item.id in decision.evidence_ids and item.url == action.get("target"):
                return dict(action)
            return None
        for item_id in decision.evidence_ids:
            item = self.store.get_by_id(item_id)
            if item and item.engine == engine and item.url:
                return {
                    "type": "open_url",
                    "target": item.url,
                    "label": item.title,
                    "evidenceId": item.id,
                    "postData": item.metadata.get("post_data", ""),
                }
        return None

    def prepare_flight_booking(
        self, evidence_id: str | None = None, bus: Any = None
    ) -> RelayDecision:
        """Resolve provider options for a selected flight without purchasing it."""
        if not self.client.is_available():
            return RelayDecision(
                answer="Live-world access is unavailable, so I can't verify booking options.",
                confidence=0.0,
                evidence_ids=[],
                action={"type": "none", "target": "", "label": ""},
            )
        selected_id = evidence_id
        if not selected_id and self._last_decision:
            for item_id in self._last_decision.evidence_ids:
                item = self.store.get_by_id(item_id)
                if item is not None and item.engine == "google_flights":
                    selected_id = item_id
                    break
        flight = self.store.get_by_id(selected_id or "")
        if flight is None or flight.engine != "google_flights":
            return RelayDecision(
                answer="I don't have a selected live flight yet. Ask me to find a flight first.",
                confidence=0.0,
                evidence_ids=[],
                action={"type": "none", "target": "", "label": ""},
            )
        token = str(flight.metadata.get("booking_token") or "")
        if not token:
            return RelayDecision(
                answer=(
                    "That flight did not include a SerpApi booking token. I can open its "
                    "verified Google Flights result, but I can't claim a provider is selected."
                ),
                confidence=0.55,
                evidence_ids=[flight.id],
                action={
                    "type": "open_url" if flight.url else "none",
                    "target": flight.url,
                    "label": "Open verified flight result" if flight.url else "",
                    "evidenceId": flight.id,
                },
            )
        if bus is not None:
            bus.emit(
                "liveworld.trace",
                stage="BOOKING",
                type="booking_options_started",
                data={"evidenceId": flight.id},
            )
        try:
            raw = self.client.search(
                "google_flights",
                {"booking_token": token, "currency": "INR", "hl": "en", "gl": "in"},
            )
            options = normalize_flight_booking_options(raw, flight)
        except Exception as exc:
            log.warning("Booking option lookup failed: %s", exc)
            return RelayDecision(
                answer="I couldn't verify a booking provider for that flight. Nothing was purchased.",
                confidence=0.0,
                evidence_ids=[flight.id],
                action={"type": "none", "target": "", "label": ""},
            )
        for option in options:
            self.store.store("google_flights", {"booking_token": token}, [option])
        usable = [option for option in options if option.url]
        if not usable:
            return RelayDecision(
                answer="SerpApi returned no provider handoff for that flight. Nothing was purchased.",
                confidence=0.0,
                evidence_ids=[flight.id],
                action={"type": "none", "target": "", "label": ""},
            )
        best = min(
            usable,
            key=lambda option: option.price if option.price is not None else float("inf"),
        )
        price = f" for ₹{best.price:,.0f}" if best.price is not None else ""
        decision = RelayDecision(
            answer=(
                f"I verified {best.sourceName} as a booking option{price}. I'll open the "
                "provider handoff. Review passenger details and confirm payment with the keyboard; "
                "Relay has not purchased anything."
            ),
            confidence=0.95,
            evidence_ids=[flight.id, best.id],
            recommendation={
                "title": best.title,
                "price": price.strip() or "Price not returned",
                "source": best.sourceName,
            },
            action={
                "type": "open_booking",
                "target": best.url,
                "postData": best.metadata.get("post_data", ""),
                "label": f"Continue with {best.sourceName}",
                "evidenceId": best.id,
            },
        )
        if bus is not None:
            bus.emit(
                "liveworld.decision",
                **decision.to_dict(),
                evidence=[flight.to_dict(), best.to_dict()],
            )
        self._last_decision = decision
        return decision

    def _execute_single_search(self, engine: str, params: dict[str, Any]) -> tuple[str, float, list[EvidenceItem]]:
        t0 = time.perf_counter()
        raw = self.client.search(engine, params)
        duration_ms = (time.perf_counter() - t0) * 1000.0
        items = normalize_serp_response(engine, raw)
        for item in items:
            item.metadata.setdefault("search_params", dict(params))
        return engine, duration_ms, items
