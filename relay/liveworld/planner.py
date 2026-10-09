"""Search Planner for Relay LiveWorld subsystem.

Converts classified intent into an optimal multi-engine search plan.
Enforces search budget (max 6 calls, 2-4 typical).
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
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

        dest = str(entities.get("destination") or "").strip()
        origin = str(entities.get("origin") or "").strip()
        date_str = entities.get("date")
        travel_date = self._resolve_date(date_str)
        area = str(entities.get("location_area") or dest).strip()

        if cat == "travel":
            low = obj.lower()
            wants_flight = bool(
                re.search(r"\b(?:flight|flights|fly|flying|ticket|tickets)\b", low)
                or intent.constraints.get("wants_flight")
            )
            wants_hotel = bool(re.search(r"\b(?:hotel|hotels|stay|resort)\b", low))
            wants_dinner = bool(
                re.search(r"\b(?:dinner|restaurant|restaurants|food|lunch|breakfast)\b", low)
            )

            if wants_flight and origin and dest and travel_date:
                departure_id = self._city_code(origin)
                arrival_id = self._city_code(dest)
                if departure_id and arrival_id:
                    flight_params: dict[str, str | int | float | bool] = {
                        "departure_id": departure_id,
                        "arrival_id": arrival_id,
                        "outbound_date": travel_date,
                        "type": "2",  # one-way; round-trip requires a return_date
                        "currency": "INR",
                        "hl": "en",
                        "gl": "in",
                    }
                    if intent.constraints.get("nonstop"):
                        flight_params["stops"] = "1"
                    if intent.constraints.get("prefer") == "cheapest":
                        flight_params["sort_by"] = "2"
                    if intent.constraints.get("max_price") is not None:
                        flight_params["max_price"] = int(intent.constraints["max_price"])
                    after_hour = self._hour_24(intent.constraints.get("departure_after"))
                    if after_hour is not None:
                        flight_params["outbound_times"] = f"{after_hour},23"
                    searches.append(
                        SearchItem(
                            engine="google_flights",
                            params=flight_params,
                            reason=f"Searching live flights from {origin} to {dest}",
                        )
                    )

            if wants_hotel and dest and travel_date:
                hotel_params: dict[str, str | int | float | bool] = {
                    "q": f"hotels in {area} {dest}",
                    "check_in_date": travel_date,
                    "check_out_date": self._next_date(travel_date),
                    "currency": "INR",
                    "rating": "4",
                    "hl": "en",
                    "gl": "in",
                }
                if intent.constraints.get("max_hotel_price") is not None:
                    hotel_params["max_price"] = int(intent.constraints["max_hotel_price"])
                searches.append(
                    SearchItem(
                        engine="google_hotels",
                        params=hotel_params,
                        reason=f"Searching live hotels near {area} rated 4+ stars under budget",
                    )
                )

            if wants_dinner and dest:
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

    def _city_code(self, city_name: str) -> str | None:
        name = city_name.lower().strip()
        codes = {
            "chennai": "MAA",
            "bangalore": "BLR",
            "bengaluru": "BLR",
            "mumbai": "BOM",
            "delhi": "DEL",
            "new delhi": "DEL",
            "hyderabad": "HYD",
            "kolkata": "CCU",
            "kochi": "COK",
            "goa": "GOI",
            "ahmedabad": "AMD",
            "pune": "PNQ",
            "jaipur": "JAI",
            "lucknow": "LKO",
            "chandigarh": "IXC",
            "bhubaneswar": "BBI",
            "guwahati": "GAU",
            "indore": "IDR",
            "nagpur": "NAG",
            "patna": "PAT",
            "varanasi": "VNS",
            "visakhapatnam": "VTZ",
            "vizag": "VTZ",
            "coimbatore": "CJB",
            "madurai": "IXM",
            "mangalore": "IXE",
            "thiruvananthapuram": "TRV",
            "trivandrum": "TRV",
            "srinagar": "SXR",
            "amritsar": "ATQ",
            "ranchi": "IXR",
            "raipur": "RPR",
            "dehradun": "DED",
            "surat": "STV",
            "new york": "NYC",
            "los angeles": "LAX",
            "san francisco": "SFO",
            "chicago": "CHI",
            "washington": "WAS",
            "london": "LON",
            "paris": "PAR",
            "dubai": "DXB",
            "singapore": "SIN",
            "tokyo": "TYO",
            "sydney": "SYD",
        }
        if re.fullmatch(r"[A-Za-z]{3}", city_name.strip()):
            return city_name.strip().upper()
        # SerpApi requires an IATA code or KGMID. Never send arbitrary city text.
        return codes.get(name)

    def _hour_24(self, value: Any) -> int | None:
        if not value:
            return None
        match = re.search(r"(\d{1,2})(?::\d{2})?\s*(AM|PM)?", str(value), re.I)
        if not match:
            return None
        hour = int(match.group(1))
        suffix = (match.group(2) or "").upper()
        if suffix == "PM" and hour < 12:
            hour += 12
        elif suffix == "AM" and hour == 12:
            hour = 0
        return hour if 0 <= hour <= 23 else None

    def _resolve_date(self, value: Any) -> str | None:
        text = str(value or "").strip().lower()
        today = date.today()
        if text == "today":
            return today.isoformat()
        if text == "tomorrow":
            return (today + timedelta(days=1)).isoformat()
        if text == "next week":
            return (today + timedelta(days=7)).isoformat()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError:
                return None
        weekdays = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        if text in weekdays:
            delta = (weekdays[text] - today.weekday()) % 7 or 7
            return (today + timedelta(days=delta)).isoformat()
        return None

    def missing_travel_details(self, intent: RelayIntent) -> list[str]:
        """Return details required before a requested travel engine can run."""
        if intent.category != "travel":
            return []
        low = intent.objective.lower()
        missing: list[str] = []
        wants_flight = bool(
            re.search(r"\b(?:flight|flights|fly|flying|ticket|tickets)\b", low)
            or intent.constraints.get("wants_flight")
        )
        if wants_flight:
            for key in ("origin", "destination", "date"):
                if not intent.entities.get(key):
                    missing.append(key)
            if intent.entities.get("date") and not self._resolve_date(intent.entities["date"]):
                missing.append("date")
            if intent.entities.get("origin") and not self._city_code(str(intent.entities["origin"])):
                missing.append("origin_airport")
            if intent.entities.get("destination") and not self._city_code(
                str(intent.entities["destination"])
            ):
                missing.append("destination_airport")
        if re.search(r"\b(?:hotel|hotels|stay|resort)\b", low):
            for key in ("destination", "date"):
                if not intent.entities.get(key) and key not in missing:
                    missing.append(key)
            if intent.entities.get("date") and not self._resolve_date(intent.entities["date"]) and "date" not in missing:
                missing.append("date")
        if re.search(r"\b(?:dinner|restaurant|restaurants|food|lunch|breakfast)\b", low):
            if not intent.entities.get("destination") and "destination" not in missing:
                missing.append("destination")
        return missing

    def _next_date(self, iso_date: str) -> str:
        try:
            return (date.fromisoformat(iso_date) + timedelta(days=1)).isoformat()
        except ValueError:
            return (date.today() + timedelta(days=2)).isoformat()
