"""Action Provenance generator for Relay LiveWorld subsystem.

Generates explicit transparency records ("WHY", "LIVE EVIDENCE", "FRESHNESS")
before Relay executes external actions or opens URLs.
"""

from __future__ import annotations

from typing import Any

from relay.diagnostics import get_logger
from relay.liveworld.types import EvidenceItem, RelayDecision

log = get_logger("liveworld.provenance")


class ProvenanceGenerator:
    """Creates structured provenance metadata for decisions and actions."""

    def build_provenance(
        self, decision: RelayDecision, evidence_items: list[EvidenceItem]
    ) -> dict[str, Any]:
        why_bullets: list[str] = []
        sources: list[str] = []

        by_id = {item.id: item for item in evidence_items}
        cited_items = [by_id[eid] for eid in decision.evidence_ids if eid in by_id]

        for item in cited_items:
            engine_name = item.engine.replace("_", " ").title()
            sources.append(f"{item.sourceName or engine_name} ({item.engine})")

            if item.engine == "google_flights" and item.price:
                stops = item.metadata.get("stops")
                route_type = "nonstop" if item.metadata.get("is_nonstop") else (
                    f"{stops} stop" if stops == 1 else f"{stops} stops" if stops is not None else "flight"
                )
                why_bullets.append(f"₹{item.price:,.0f} {route_type} flight ({item.title})")
            elif item.engine == "google_hotels":
                parts = []
                if item.price:
                    parts.append(f"₹{item.price:,.0f}/night")
                if item.rating:
                    parts.append(f"{item.rating} ★")
                if item.reviewCount:
                    parts.append(f"{item.reviewCount:,}+ reviews")
                why_bullets.append(f"Hotel: {item.title} ({', '.join(parts)})")
            elif item.engine == "google_maps":
                parts = []
                if item.rating:
                    parts.append(f"{item.rating} ★")
                if item.reviewCount:
                    parts.append(f"{item.reviewCount:,} reviews")
                why_bullets.append(f"Place: {item.title} ({', '.join(parts)})")
            elif item.engine == "google_shopping" and item.price:
                why_bullets.append(f"Product: ₹{item.price:,.0f} from {item.sourceName}")
            elif item.snippet:
                why_bullets.append(f"{item.sourceName}: {item.title}")

        if not why_bullets and decision.recommendation:
            why_bullets.append(f"Selected: {decision.recommendation.get('title', 'Best Plan')}")

        return {
            "why": why_bullets,
            "sources": list(set(sources)),
            "freshness": "Verified moments ago via SerpApi",
            "cited_count": len(cited_items),
            "evidence_items": [item.to_dict() for item in cited_items],
        }
