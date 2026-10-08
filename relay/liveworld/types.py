"""Type definitions for the Relay LiveWorld subsystem."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

Category = Literal[
    "travel",
    "shopping",
    "local",
    "news",
    "research",
    "general",
    "local_action",
]

EngineType = Literal[
    "google",
    "google_shopping",
    "google_maps",
    "google_flights",
    "google_hotels",
    "google_news",
]


@dataclass
class RelayIntent:
    requires_live_data: bool
    category: Category
    objective: str
    entities: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "requiresLiveData": self.requires_live_data,
            "category": self.category,
            "objective": self.objective,
            "entities": self.entities,
            "constraints": self.constraints,
            "confidence": self.confidence,
        }


@dataclass
class SearchItem:
    engine: EngineType
    params: dict[str, str | int | float | bool]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "params": self.params,
            "reason": self.reason,
        }


@dataclass
class SearchPlan:
    id: str
    objective: str
    searches: list[SearchItem]
    max_requests: int = 6

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "objective": self.objective,
            "searches": [s.to_dict() for s in self.searches],
            "maxRequests": self.max_requests,
        }


@dataclass
class EvidenceItem:
    id: str
    engine: EngineType
    title: str
    sourceName: str = ""
    url: str = ""
    snippet: str = ""
    price: float | None = None
    currency: str | None = None
    rating: float | None = None
    reviewCount: int | None = None
    address: str | None = None
    distance: str | None = None
    departureTime: str | None = None
    arrivalTime: str | None = None
    fetchedAt: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "engine": self.engine,
            "sourceName": self.sourceName,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "price": self.price,
            "currency": self.currency,
            "rating": self.rating,
            "reviewCount": self.reviewCount,
            "address": self.address,
            "distance": self.distance,
            "departureTime": self.departureTime,
            "arrivalTime": self.arrivalTime,
            "fetchedAt": self.fetchedAt,
            "metadata": self.metadata,
        }


@dataclass
class RelayDecision:
    answer: str
    confidence: float
    evidence_ids: list[str]
    recommendation: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "evidenceIds": self.evidence_ids,
            "action": self.action,
            "provenance": self.provenance,
        }


@dataclass
class SearchTelemetry:
    intent_latency_ms: float = 0.0
    time_to_first_search_ms: float = 0.0
    search_durations_ms: dict[str, float] = field(default_factory=dict)
    total_searches: int = 0
    candidate_count: int = 0
    decision_latency_ms: float = 0.0
    total_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "intentLatencyMs": round(self.intent_latency_ms, 1),
            "timeToFirstSearchMs": round(self.time_to_first_search_ms, 1),
            "searchDurationsMs": {k: round(v, 1) for k, v in self.search_durations_ms.items()},
            "totalSearches": self.total_searches,
            "candidateCount": self.candidate_count,
            "decisionLatencyMs": round(self.decision_latency_ms, 1),
            "totalLatencyMs": round(self.total_latency_ms, 1),
        }
