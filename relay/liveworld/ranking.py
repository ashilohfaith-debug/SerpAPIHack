"""Grounded Decision Engine for Relay LiveWorld subsystem.

Applies strict constraint filtering and ranking on retrieved EvidenceItem instances.
Ensures decisions are grounded exclusively in evidence and rejects hallucinated citation IDs.
"""

from __future__ import annotations

import re
from datetime import datetime
from datetime import time as dt_time
from typing import Any

from relay.diagnostics import get_logger
from relay.liveworld.evidence import EvidenceStore, evidence_fingerprint
from relay.liveworld.types import EvidenceItem, RelayDecision, RelayIntent

log = get_logger("liveworld.ranking")


class GroundedDecisionEngine:
    """Evaluates constraints on live evidence items and synthesizes grounded decisions."""

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store

    def decide(self, intent: RelayIntent, evidence_items: list[EvidenceItem]) -> RelayDecision:
        cat = intent.category
        evidence_items = [item for item in evidence_items if self.store.get_by_id(item.id) is not None]
        excluded = set(intent.constraints.get("exclude_evidence_ids") or [])
        fingerprints = set(intent.constraints.get("exclude_evidence_fingerprints") or [])
        evidence_items = [
            item for item in evidence_items
            if item.id not in excluded and evidence_fingerprint(item) not in fingerprints
        ]

        if not evidence_items:
            return RelayDecision(
                answer="No live evidence could be retrieved to satisfy the constraints.",
                confidence=0.0,
                evidence_ids=[],
                action={"type": "none", "target": "", "label": ""},
            )

        if cat == "travel":
            return self._decide_travel(intent, evidence_items)
        elif cat == "shopping":
            return self._decide_shopping(intent, evidence_items)
        elif cat == "local":
            return self._decide_local(intent, evidence_items)
        elif cat == "news":
            return self._decide_news(intent, evidence_items)
        else:
            return self._decide_general(intent, evidence_items)

    def _decide_travel(self, intent: RelayIntent, items: list[EvidenceItem]) -> RelayDecision:
        constraints = intent.constraints
        excluded = set(constraints.get("exclude_evidence_ids") or [])
        excluded_fingerprints = set(constraints.get("exclude_evidence_fingerprints") or [])

        def included(item: EvidenceItem) -> bool:
            return item.id not in excluded and evidence_fingerprint(item) not in excluded_fingerprints

        flights = [i for i in items if i.engine == "google_flights" and included(i)]
        hotels = [i for i in items if i.engine == "google_hotels" and included(i)]
        dinners = [
            i for i in items if i.engine in ("google_maps", "google") and included(i)
        ]
        max_total = constraints.get("max_total_budget")
        max_hotel = constraints.get("max_hotel_price")
        max_flight = constraints.get("max_price")
        min_rating = constraints.get("min_rating", 4.0)
        low_objective = intent.objective.lower()
        needs_flight = bool(
            re.search(r"\b(?:flight|flights|fly|flying|ticket|tickets)\b", low_objective)
            or constraints.get("wants_flight")
        )
        needs_hotel = bool(re.search(r"\b(?:hotel|hotels|stay|resort)\b", low_objective))
        needs_dinner = bool(
            re.search(r"\b(?:dinner|restaurant|restaurants|food|lunch|breakfast)\b", low_objective)
        )

        # 1. Filter flights without guessing about missing schedule or price data.
        eligible_flights: list[EvidenceItem] = []
        for f in flights:
            is_nonstop = f.metadata.get("is_nonstop")
            if is_nonstop is None:
                is_nonstop = "nonstop" in f.snippet.lower()
            if constraints.get("nonstop") and not is_nonstop:
                continue
            if not self._time_is_at_or_after(f.departureTime, constraints.get("departure_after")):
                continue
            if max_flight is not None and (f.price is None or f.price > max_flight):
                continue
            eligible_flights.append(f)

        # 2. Filter hotels against every explicit per-night constraint.
        eligible_hotels: list[EvidenceItem] = []
        for h in hotels:
            if h.rating is None or h.rating < min_rating:
                continue
            if h.price is None or (max_hotel is not None and h.price > max_hotel):
                continue
            area = str(intent.entities.get("location_area") or "").casefold()
            if area and area not in " ".join((h.title, h.address or "", h.snippet)).casefold():
                continue
            eligible_hotels.append(h)

        best_flight = (
            min(eligible_flights, key=lambda item: item.price or float("inf"), default=None)
            if needs_flight
            else None
        )
        best_hotel = (
            max(eligible_hotels, key=lambda item: item.rating or 0, default=None)
            if needs_hotel
            else None
        )

        # A total budget is a hard constraint, not descriptive text. When a request
        # needs both a flight and hotel, select an actual pair under the ceiling.
        if max_total is not None and needs_flight and needs_hotel and eligible_flights and eligible_hotels:
            pairs = [
                (flight, hotel)
                for flight in eligible_flights
                for hotel in eligible_hotels
                if flight.price is not None
                and hotel.price is not None
                and flight.price + hotel.price <= max_total
            ]
            if not pairs:
                return RelayDecision(
                    answer=(
                        f"I found live travel results, but no verified flight and hotel "
                        f"combination fits the ₹{max_total:,.0f} total budget."
                    ),
                    confidence=0.35,
                    evidence_ids=[],
                    action={"type": "none", "target": "", "label": ""},
                )
            best_flight, best_hotel = min(
                pairs,
                key=lambda pair: (
                    (pair[0].price or 0) + (pair[1].price or 0),
                    -(pair[1].rating or 0),
                ),
            )
        if max_total is not None and needs_flight and best_flight:
            if best_flight.price is None or best_flight.price > max_total:
                best_flight = None
        if max_total is not None and needs_hotel and best_hotel:
            if best_hotel.price is None or best_hotel.price > max_total:
                best_hotel = None

        # 3. Select best dinner spot (rating > 4.0)
        best_dinner = None
        for d in dinners if needs_dinner else []:
            if d.rating is None or d.rating < min_rating:
                continue
            if re.search(r"\bopen\b", low_objective) and not self._opening_verified(intent, d):
                continue
            if best_dinner is None or (d.rating or 0) > (best_dinner.rating or 0):
                best_dinner = d

        if not (best_flight or best_hotel or best_dinner):
            return RelayDecision(
                answer="Live results were retrieved, but none satisfied the requested travel constraints.",
                confidence=0.35,
                evidence_ids=[],
                action={"type": "none", "target": "", "label": ""},
            )

        evidence_ids: list[str] = []
        if best_flight:
            evidence_ids.append(best_flight.id)
        if best_hotel:
            evidence_ids.append(best_hotel.id)
        if best_dinner:
            evidence_ids.append(best_dinner.id)

        # Validate citation IDs
        valid_ids = self.store.validate_citation_ids(evidence_ids)

        flight_cost = best_flight.price if best_flight and best_flight.price is not None else None
        hotel_cost = best_hotel.price if best_hotel and best_hotel.price is not None else None
        total_est = None
        under_budget = None
        if flight_cost is not None and hotel_cost is not None:
            total_est = flight_cost + hotel_cost
            under_budget = max_total - total_est if max_total is not None else None

        destination = str(intent.entities.get("destination") or "destination").upper()
        date_label = str(intent.entities.get("date") or "requested date").upper()
        flight_title = best_flight.sourceName if best_flight else "Not verified"
        flight_time = (
            f"{best_flight.departureTime} → {best_flight.arrivalTime}"
            if best_flight and best_flight.departureTime and best_flight.arrivalTime
            else "Time not verified"
        )
        flight_price = f"₹{flight_cost:,.0f}" if flight_cost is not None else "Price not verified"

        hotel_name = best_hotel.title if best_hotel else "No matching hotel verified"
        hotel_rating = f"{best_hotel.rating} ★" if best_hotel and best_hotel.rating is not None else "Rating not verified"
        hotel_price = f"₹{hotel_cost:,.0f}" if hotel_cost is not None else "Price not verified"

        dinner_name = best_dinner.title if best_dinner else "No matching dinner place verified"
        dinner_rating = f"{best_dinner.rating} ★" if best_dinner and best_dinner.rating is not None else "Rating not verified"

        answer_parts = []
        answer_parts.append(
            f"For {destination.title()} on {date_label.lower()}, I verified these live results."
        )
        if needs_flight:
            if best_flight:
                answer_parts.append(f"Flight: {flight_title} ({flight_time}) for {flight_price}.")
            else:
                answer_parts.append("I could not verify a flight matching your requested constraints.")
        if needs_hotel:
            if best_hotel:
                answer_parts.append(f"Stay: {hotel_name} rated {hotel_rating} for {hotel_price}/night.")
            elif max_hotel is not None:
                answer_parts.append(
                    f"I could not verify a hotel under ₹{max_hotel:,.0f} "
                    f"with rating at least {min_rating}."
                )
            else:
                answer_parts.append(
                    f"I could not verify a hotel rated at least {min_rating}."
                )
        if needs_dinner:
            if best_dinner:
                answer_parts.append(f"Dinner: {dinner_name} rated {dinner_rating}.")
            else:
                answer_parts.append("I could not verify a dinner place meeting the requested rating and opening constraints.")
        if needs_flight and needs_hotel and total_est is not None and max_total is not None:
            budget_text = (
                f"₹{under_budget:,.0f} under budget"
                if under_budget is not None and under_budget >= 0
                else f"₹{abs(under_budget or 0):,.0f} over budget"
            )
            answer_parts.append(f"The verified flight plus hotel total is ₹{total_est:,.0f}, {budget_text}.")
        elif needs_flight and needs_hotel and total_est is not None:
            answer_parts.append(f"The verified flight plus hotel total is ₹{total_est:,.0f}.")
        elif needs_flight and needs_hotel:
            answer_parts.append("I did not calculate a total because at least one required price was not verified.")

        answer = " ".join(answer_parts)

        rec = {
            "destination": f"{destination} · {date_label}",
            "badge": "Best plan",
            "flight": {
                "name": flight_title,
                "time": flight_time,
                "price": flight_price,
                "url": best_flight.url if best_flight else "",
            },
            "stay": {
                "name": hotel_name,
                "rating": hotel_rating,
                "price": hotel_price,
                "url": best_hotel.url if best_hotel else "",
            },
            "dinner": {
                "name": dinner_name,
                "rating": dinner_rating,
                "distance": best_dinner.distance or best_dinner.address or "" if best_dinner else "",
                "url": best_dinner.url if best_dinner else "",
            },
            "total_cost": f"₹{total_est:,.0f}" if total_est is not None else "Not fully verified",
            "savings": (
                f"₹{under_budget:,.0f} under your ₹{max_total:,.0f} budget"
                if under_budget is not None and under_budget >= 0
                else (
                    f"₹{abs(under_budget):,.0f} over your ₹{max_total:,.0f} budget"
                    if under_budget is not None
                    else "No total budget requested"
                )
            ),
        }

        for key, requested in (("flight", needs_flight), ("stay", needs_hotel), ("dinner", needs_dinner)):
            if not requested:
                rec.pop(key, None)

        action_item = next(
            (item for item in (best_flight, best_hotel, best_dinner) if item and item.url),
            None,
        )
        action_target = action_item.url if action_item and action_item.url else ""

        return RelayDecision(
            answer=answer,
            recommendation=rec,
            confidence=(
                0.98
                if (not needs_flight or best_flight)
                and (not needs_hotel or best_hotel)
                and (not needs_dinner or best_dinner)
                else 0.72
            ),
            evidence_ids=valid_ids,
            action={
                "type": "open_url" if action_target else "none",
                "target": action_target,
                "label": f"Open {action_item.title}" if action_item else "",
                "evidenceId": action_item.id if action_item else "",
            },
        )

    def _time_is_at_or_after(self, value: str | None, threshold: Any) -> bool:
        if not threshold:
            return True
        actual = self._parse_time(value)
        wanted = self._parse_time(str(threshold))
        if wanted is None:
            return True
        if actual is None:
            return False
        return actual >= wanted

    def _parse_time(self, value: str | None) -> dt_time | None:
        if not value:
            return None
        text = value.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}[ T]", text):
            try:
                return datetime.fromisoformat(text).time()
            except ValueError:
                return None
        match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?", text, re.IGNORECASE)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        suffix = (match.group(3) or "").upper()
        if suffix == "PM" and hour < 12:
            hour += 12
        elif suffix == "AM" and hour == 12:
            hour = 0
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return None
        return dt_time(hour, minute)

    def _decide_shopping(self, intent: RelayIntent, items: list[EvidenceItem]) -> RelayDecision:
        max_price = intent.constraints.get("max_price")

        valid_items = [
            i for i in items if i.engine == "google_shopping" and i.price is not None
            and (max_price is None or i.price <= max_price)
        ]
        if not valid_items:
            return RelayDecision(
                answer=(f"I found live products, but none had a verified price within ₹{max_price:,.0f}."
                        if max_price is not None else "I found no products with a verified price."),
                confidence=0.35,
                evidence_ids=[],
                action={"type": "none", "target": "", "label": ""},
            )

        best_item = min(valid_items, key=lambda x: x.price if x.price else 999999)
        valid_ids = self.store.validate_citation_ids([i.id for i in valid_items[:3]])

        low = intent.objective.lower()
        if re.search(r"\b(?:compare|comparison|versus|vs)\b", low) and len(valid_items) > 1:
            retailers = [f"{it.sourceName}: ₹{it.price:,.0f}" for it in valid_items[:3]]
            retailer_text = ", ".join(retailers)
            answer = (
                f"Comparing verified options under ₹{max_price:,.0f}: {retailer_text}. "
                f"The best deal is {best_item.title} on {best_item.sourceName} for ₹{best_item.price:,.0f}."
                if max_price is not None
                else f"Comparing verified options: {retailer_text}. The best deal is {best_item.title} on {best_item.sourceName} for ₹{best_item.price:,.0f}."
            )
        else:
            delivery = best_item.metadata.get("delivery")
            deliv_text = f" ({delivery})" if delivery else ""
            answer = (
                f"The cheapest deal found is {best_item.title} from {best_item.sourceName} "
                f"for ₹{best_item.price:,.0f}{deliv_text}."
                if best_item.price
                else f"The best option found is {best_item.title} from {best_item.sourceName}."
            )

        return RelayDecision(
            answer=answer,
            confidence=0.95,
            evidence_ids=valid_ids,
            recommendation={
                "title": best_item.title,
                "price": f"₹{best_item.price:,.0f}" if best_item.price else "Best Price",
                "source": best_item.sourceName,
                "url": best_item.url,
            },
            action={
                "type": "open_url" if best_item.url else "none",
                "target": best_item.url,
                "label": f"Open {best_item.sourceName}" if best_item.url else "",
                "evidenceId": best_item.id,
            },
        )

    def _decide_local(self, intent: RelayIntent, items: list[EvidenceItem]) -> RelayDecision:
        low = intent.objective.lower()
        rating_floor = intent.constraints.get("min_rating")
        if rating_floor is None and re.search(r"\b(?:highly rated|top rated|best)\b", low):
            rating_floor = 4.0
        candidates = [
            item for item in items if item.engine == "google_maps"
            and (rating_floor is None or (item.rating is not None and item.rating >= rating_floor))
            and (not re.search(r"\bopen\b", low) or self._opening_verified(intent, item))
        ]
        if not candidates:
            return RelayDecision(
                "I found live places, but couldn't verify one meeting your rating and opening constraints.",
                0.35,
                [],
                action={"type": "none", "target": "", "label": ""},
            )
        best_item = max(candidates, key=lambda x: (x.rating or 0, x.reviewCount or 0))
        valid_ids = self.store.validate_citation_ids([best_item.id])

        rating = f" rated {best_item.rating} stars" if best_item.rating is not None else ""
        reviews = f" with {best_item.reviewCount:,} reviews" if best_item.reviewCount else ""
        open_state = str(best_item.metadata.get("open_state") or "").strip()
        status_text = f", {open_state}" if open_state else ""
        address_text = f" at {best_item.address}" if best_item.address else ""
        answer = f"I recommend {best_item.title}{rating}{reviews}{address_text}{status_text}. {best_item.snippet}"
        return RelayDecision(
            answer=answer,
            confidence=0.95,
            evidence_ids=valid_ids,
            recommendation={
                "title": best_item.title,
                "rating": f"{best_item.rating} ★" if best_item.rating else "Top Rated",
                "address": best_item.address or "",
                "url": best_item.url,
            },
            action={
                "type": "open_maps" if best_item.url else "none",
                "target": best_item.url,
                "label": f"Open {best_item.title} in Maps" if best_item.url else "",
                "evidenceId": best_item.id,
            },
        )

    def _opening_verified(self, intent: RelayIntent, item: EvidenceItem) -> bool:
        low = intent.objective.lower()
        state = str(item.metadata.get("open_state") or "").strip().casefold()
        hours = str(item.metadata.get("hours") or "").strip().casefold()
        combined = f"{state} {hours}".strip()

        if re.search(r"\bopen\s+now\b", low):
            return bool(re.match(r"^(?:open|open 24 hours)\b", state)) and "closed" not in state

        if re.search(r"\b(?:tonight|this evening|dinner)\b", low):
            # Cannot infer future tonight from bare "open" observation without schedule
            # Must verify evening schedule / business hours
            if "24 hours" in combined:
                return True
            evening_close = re.search(
                r"closes?\s+(?:[89]|1[0-2])(?::\d{2})?\s*(?:pm|am)", combined
            )
            if evening_close:
                return True
            op_hours = item.metadata.get("operating_hours")
            if isinstance(op_hours, dict) and any("pm" in str(v).lower() for v in op_hours.values()):
                return True
            return False

        return bool(re.match(r"^(?:open|open 24 hours)\b", state)) and "closed" not in state

    def _decide_news(self, intent: RelayIntent, items: list[EvidenceItem]) -> RelayDecision:
        if not items:
            return RelayDecision(
                answer="I found no verified live news results for that request.",
                confidence=0.0,
                evidence_ids=[],
                action={"type": "none", "target": "", "label": ""},
            )
        top_news = items[:3]
        valid_ids = self.store.validate_citation_ids([n.id for n in top_news])

        headlines_list = []
        for n in top_news:
            date_str = f", {n.metadata.get('date')}" if n.metadata.get("date") else ""
            headlines_list.append(f"{n.title} ({n.sourceName}{date_str})")
        headlines = "; ".join(headlines_list)
        answer = f"Here are the latest updates: {headlines}."

        return RelayDecision(
            answer=answer,
            confidence=0.92,
            evidence_ids=valid_ids,
            recommendation={
                "title": top_news[0].title if top_news else "Latest News",
                "source": top_news[0].sourceName if top_news else "Google News",
                "url": top_news[0].url if top_news else "https://news.google.com",
            },
            action={
                "type": "open_url" if top_news and top_news[0].url else "none",
                "target": top_news[0].url if top_news else "",
                "label": "Read Source Article" if top_news and top_news[0].url else "",
                "evidenceId": top_news[0].id if top_news else "",
            },
        )

    def _decide_general(self, intent: RelayIntent, items: list[EvidenceItem]) -> RelayDecision:
        if not items:
            return RelayDecision(
                answer="I found no verified live search results for that request.",
                confidence=0.0,
                evidence_ids=[],
                action={"type": "none", "target": "", "label": ""},
            )
        best = items[0]
        top_items = items[:3]
        valid_ids = self.store.validate_citation_ids([it.id for it in top_items])

        low = intent.objective.lower()
        if re.search(r"\b(?:compare|versus|vs|comparison)\b", low) and len(top_items) > 1:
            points = "; ".join([it.snippet for it in top_items if it.snippet])
            answer = f"Based on live comparison results: {points}"
        else:
            answer = f"Based on live search results: {best.snippet}"

        return RelayDecision(
            answer=answer,
            confidence=0.90,
            evidence_ids=valid_ids,
            recommendation={
                "title": best.title,
                "source": best.sourceName,
                "url": best.url,
            },
            action={
                "type": "open_url" if best.url else "none",
                "target": best.url,
                "label": "Open Source" if best.url else "",
                "evidenceId": best.id,
            },
        )
