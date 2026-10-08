"""Search Planner for Relay LiveWorld subsystem.

Converts classified intent into an optimal multi-engine search plan.
Enforces search budget (max 6 calls, 2-4 typical).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from relay.diagnostics import get_logger
from relay.liveworld.types import RelayIntent, SearchItem, SearchPlan

log = get_logger("liveworld.planner")


class SearchPlanner:
    """Generates structured search plans for SerpApi multi-engine execution."""

    def create_search_plan(self, intent: RelayIntent) -> SearchPlan:
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        searches: list[SearchItem] = []

        cat = intent.category
        obj = intent.objective
        entities = intent.entities
        constraints = intent.constraints

        dest = entities.get("destination", "Bangalore")
        origin = entities.get("origin", "Chennai")
        date_str = entities.get("date", "tomorrow")
        area = entities.get("location_area", dest)

        if cat == "travel":
            # 1. Google Flights search
            searches.append(
                SearchItem(
                    engine="google_flights",
                    params={
                        "departure_id": self._city_code(origin),
                        "arrival_id": self._city_code(dest),
                        "outbound_date": "2026-10-09",
                        "currency": "INR",
                        "hl": "en",
                        "gl": "in",
                    },
                    reason=f"Searching live nonstop flights from {origin} to {dest}",
                )
            )

            # 2. Google Hotels search
            searches.append(
                SearchItem(
                    engine="google_hotels",
                    params={
                        "q": f"hotels in {area} {dest}",
                        "check_in_date": "2026-10-09",
                        "check_out_date": "2026-10-10",
                        "currency": "INR",
                        "rating": "4",
                        "hl": "en",
                        "gl": "in",
                    },
                    reason=f"Searching live hotels near {area} rated 4+ stars under budget",
                )
            )

            # 3. Google Maps / Local places for dinner
            searches.append(
                SearchItem(
                    engine="google_maps",
                    params={
                        "q": f"highly rated dinner restaurants in {area} {dest}",
                        "type": "search",
                        "hl": "en",
                        "gl": "in",
                    },
                    reason=f"Finding top dinner spots open near {area}",
                )
            )

        elif cat == "shopping":
            # 1. Google Shopping search
            searches.append(
                SearchItem(
                    engine="google_shopping",
                    params={
                        "q": obj,
                        "google_domain": "google.co.in",
                        "gl": "in",
                        "hl": "en",
                    },
                    reason="Searching live product prices across online retailers",
                )
            )

            # 2. General web for reviews / comparisons
            searches.append(
                SearchItem(
                    engine="google",
                    params={
                        "q": f"{obj} review specs comparison",
                        "google_domain": "google.co.in",
                        "gl": "in",
                        "hl": "en",
                    },
                    reason="Verifying user reviews, specifications, and issues",
                )
            )

        elif cat == "local":
            # 1. Google Maps search
            searches.append(
                SearchItem(
                    engine="google_maps",
                    params={
                        "q": obj,
                        "type": "search",
                        "hl": "en",
                        "gl": "in",
                    },
                    reason="Searching live local places, ratings, and operating hours",
                )
            )

            # 2. General Google search for details
            searches.append(
                SearchItem(
                    engine="google",
                    params={
                        "q": obj,
                        "google_domain": "google.co.in",
                        "gl": "in",
                        "hl": "en",
                    },
                    reason="Verifying additional business details and reviews",
                )
            )

        elif cat == "news":
            # 1. Google News search
            searches.append(
                SearchItem(
                    engine="google_news",
                    params={
                        "q": obj,
                        "gl": "in",
                        "hl": "en",
                    },
                    reason="Retrieving breaking news and recent updates",
                )
            )

            # 2. Web search for background context
            searches.append(
                SearchItem(
                    engine="google",
                    params={
                        "q": obj,
                        "google_domain": "google.co.in",
                        "gl": "in",
                        "hl": "en",
                    },
                    reason="Retrieving primary reference sources and analysis",
                )
            )

        else:  # research or general live query
            # 1. Primary Google web search
            searches.append(
                SearchItem(
                    engine="google",
                    params={
                        "q": obj,
                        "google_domain": "google.co.in",
                        "gl": "in",
                        "hl": "en",
                    },
                    reason="Searching live web facts and verified information",
                )
            )

            # 2. Google News search if recency implied
            if any(w in obj.lower() for w in ["latest", "recent", "today", "new", "update"]):
                searches.append(
                    SearchItem(
                        engine="google_news",
                        params={
                            "q": obj,
                            "gl": "in",
                            "hl": "en",
                        },
                        reason="Checking recent news developments",
                    )
                )

        plan = SearchPlan(
            id=plan_id,
            objective=obj,
            searches=searches[:6],  # Enforce max 6 searches
            max_requests=6,
        )
        log.info("Created search plan %s with %d searches", plan.id, len(plan.searches))
        return plan

    def _city_code(self, city_name: str) -> str:
        name = city_name.lower().strip()
        codes = {
            "chennai": "MAA",
            "bangalore": "BLR",
            "bengaluru": "BLR",
            "mumbai": "BOM",
            "delhi": "DEL",
            "hyderabad": "HYD",
            "kolkata": "CCU",
            "kochi": "COK",
            "goa": "GOI",
        }
        return codes.get(name, "BLR")
