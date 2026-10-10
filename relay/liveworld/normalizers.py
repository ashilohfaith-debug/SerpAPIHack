"""Normalizers for converting SerpApi multi-engine responses into standardized EvidenceItem instances.

Supports:
  - google (organic search results)
  - google_shopping (shopping results & inline products)
  - google_maps (local places & map results)
  - google_flights (flight options & prices)
  - google_hotels (hotel properties & rates)
  - google_news (news headlines & sources)
"""

from __future__ import annotations

import math
import re
import uuid
from typing import Any
from urllib.parse import urlparse

from relay.diagnostics import get_logger
from relay.liveworld.types import EngineType, EvidenceItem

log = get_logger("liveworld.normalizers")


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9.]", "", value)
        try:
            number = float(cleaned) if cleaned else None
            return number if number is not None and math.isfinite(number) and number >= 0 else None
        except ValueError:
            return None
    return None


def normalize_serp_response(engine: EngineType, raw_data: dict[str, Any]) -> list[EvidenceItem]:
    """Route raw SerpApi engine response to its corresponding normalizer."""
    if engine == "google_flights":
        items = _normalize_flights(raw_data)
    elif engine == "google_hotels":
        items = _normalize_hotels(raw_data)
    elif engine == "google_maps":
        items = _normalize_maps(raw_data)
    elif engine == "google_shopping":
        items = _normalize_shopping(raw_data)
    elif engine == "google_news":
        items = _normalize_news(raw_data)
    else:
        items = _normalize_google_web(raw_data)
    for item in items:
        item.url = _safe_url(item.url)
    return items


def _safe_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlparse(value.strip())
        return value.strip() if parsed.scheme in ("http", "https") and parsed.hostname else ""
    except ValueError:
        return ""


def _normalize_flights(raw_data: dict[str, Any]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []

    # Check best_flights and other_flights arrays
    flight_groups = raw_data.get("best_flights", []) + raw_data.get("other_flights", [])

    for idx, flight in enumerate(flight_groups[:10]):
        flights_list = flight.get("flights", [])
        if not flights_list:
            continue
        
        first_leg = flights_list[0]
        last_leg = flights_list[-1]
        airline = first_leg.get("airline", "Airline")
        flight_num = first_leg.get("flight_number", "")
        dep_airport = first_leg.get("departure_airport", {}).get("name", "Origin")
        arr_airport = last_leg.get("arrival_airport", {}).get("name", "Destination")
        dep_time = first_leg.get("departure_airport", {}).get("time", "")
        arr_time = last_leg.get("arrival_airport", {}).get("time", "")

        price_val = _number(flight.get("price"))
        layovers = flight.get("layovers") or []
        stops = max(len(flights_list) - 1, len(layovers))
        stop_label = "Nonstop" if stops == 0 else f"{stops} stop" + ("s" if stops != 1 else "")

        title = f"{airline} {flight_num} ({dep_time} → {arr_time})" if flight_num else f"{airline} ({dep_time} → {arr_time})"
        url = raw_data.get("search_metadata", {}).get("google_flights_url", "")

        items.append(
            EvidenceItem(
                id=f"ev_flight_{idx+1}_{uuid.uuid4().hex[:4]}",
                engine="google_flights",
                sourceName=airline,
                title=title,
                url=url,
                snippet=(
                    f"{stop_label} flight from {dep_airport} to {arr_airport}. Price: ₹{price_val:,.0f}."
                    if price_val is not None
                    else f"{stop_label} flight from {dep_airport} to {arr_airport}; price not returned."
                ),
                price=price_val,
                currency="INR",
                departureTime=dep_time,
                arrivalTime=arr_time,
                metadata={
                    "airline": airline,
                    "flight_number": flight_num,
                    "stops": stops,
                    "is_nonstop": stops == 0,
                    "booking_token": flight.get("booking_token", ""),
                    "raw_flight": flight,
                },
            )
        )

    return items


def _normalize_hotels(raw_data: dict[str, Any]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    properties = raw_data.get("properties", [])

    for idx, prop in enumerate(properties[:10]):
        title = prop.get("name", "Hotel Property")
        rate_info = prop.get("rate_per_night", {})
        extracted_price = rate_info.get("extracted_before_taxes") or rate_info.get("extracted_lowest") or prop.get("extracted_price")
        
        rating = prop.get("overall_rating") or prop.get("rating")
        reviews = prop.get("reviews") or prop.get("review_count")
        description = prop.get("description", "") or prop.get("snippet", "")
        link = prop.get("link", "")

        items.append(
            EvidenceItem(
                id=f"ev_hotel_{idx+1}_{uuid.uuid4().hex[:4]}",
                engine="google_hotels",
                sourceName="Google Hotels",
                title=title,
                url=link,
                snippet=description or f"Hotel in target area rated {rating} stars with {reviews} reviews.",
                price=_number(extracted_price),
                currency="INR",
                rating=float(rating) if rating else None,
                reviewCount=int(reviews) if reviews else None,
                address=prop.get("address") or None,
                metadata={
                    "hotel_class": prop.get("hotel_class"),
                    "amenities": prop.get("amenities", []),
                    "property_token": prop.get("property_token", ""),
                    "free_cancellation": prop.get("free_cancellation"),
                },
            )
        )

    return items


def _normalize_maps(raw_data: dict[str, Any]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    results = raw_data.get("local_results", []) or raw_data.get("places", [])

    for idx, place in enumerate(results[:10]):
        title = place.get("title") or place.get("name", "Local Business")
        rating = place.get("rating")
        reviews = place.get("reviews") or place.get("user_ratings_total")
        address = place.get("address", "")
        link = place.get("website") or place.get("link") or ""
        type_str = place.get("type", "Local Place")

        items.append(
            EvidenceItem(
                id=f"ev_map_{idx+1}_{uuid.uuid4().hex[:4]}",
                engine="google_maps",
                sourceName="Google Maps",
                title=title,
                url=link,
                snippet=f"{type_str} located at {address}. Rating: {rating} ★ ({reviews} reviews).",
                rating=float(rating) if rating else None,
                reviewCount=int(reviews) if reviews else None,
                address=address,
                metadata={
                    "place_id": place.get("place_id"),
                    "hours": place.get("operating_hours"),
                    "open_state": place.get("open_state") or place.get("hours"),
                },
            )
        )

    return items


def _normalize_shopping(raw_data: dict[str, Any]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    results = raw_data.get("shopping_results", []) or raw_data.get("inline_shopping_results", [])

    for idx, prod in enumerate(results[:10]):
        title = prod.get("title", "Product Item")
        price = prod.get("extracted_price") or prod.get("price")
        source = prod.get("source", "Google Shopping")
        link = prod.get("link") or prod.get("product_link") or ""
        rating = prod.get("rating")
        reviews = prod.get("reviews")
        delivery = prod.get("delivery")

        deliv_str = f" ({delivery})" if delivery else ""
        items.append(
            EvidenceItem(
                id=f"ev_shop_{idx+1}_{uuid.uuid4().hex[:4]}",
                engine="google_shopping",
                sourceName=source,
                title=title,
                url=link,
                snippet=f"Available from {source} for ₹{price:,.0f}{deliv_str}." if isinstance(price, (int, float)) else f"Available from {source}{deliv_str}.",
                price=_number(price),
                currency="INR",
                rating=float(rating) if rating else None,
                reviewCount=int(reviews) if reviews else None,
                metadata={"merchant": source, "delivery": delivery},
            )
        )

    return items


def normalize_flight_booking_options(
    raw_data: dict[str, Any], flight: EvidenceItem
) -> list[EvidenceItem]:
    """Normalize SerpApi's second-stage Google Flights booking options.

    A booking request can be a direct GET or a POST relay.  The request is retained
    as structured metadata so Relay can open it without altering opaque form data.
    """
    items: list[EvidenceItem] = []
    for idx, option in enumerate(raw_data.get("booking_options", [])[:10]):
        sections = [option.get("together"), option.get("departing")]
        offer = next((part for part in sections if isinstance(part, dict)), None)
        if not offer:
            continue
        seller = str(offer.get("book_with") or offer.get("option_title") or "Booking provider")
        request = offer.get("booking_request") or {}
        request = request if isinstance(request, dict) else {}
        local_prices = offer.get("local_prices") or []
        inr_price = next(
            (
                _number(p.get("price"))
                for p in local_prices
                if isinstance(p, dict) and p.get("currency") == "INR"
            ),
            None,
        )
        price = inr_price or _number(offer.get("price"))
        items.append(
            EvidenceItem(
                id=f"ev_booking_{idx + 1}_{uuid.uuid4().hex[:4]}",
                engine="google_flights",
                sourceName=seller,
                title=f"Book {flight.title} with {seller}",
                url=_safe_url(request.get("url")),
                snippet=(
                    f"Verified booking option from {seller} for ₹{price:,.0f}."
                    if price is not None
                    else f"Verified booking option from {seller}; price was not returned."
                ),
                price=price,
                currency="INR" if inr_price is not None else flight.currency,
                metadata={
                    "kind": "flight_booking",
                    "post_data": str(request.get("post_data") or ""),
                    "booking_phone": offer.get("booking_phone", ""),
                    "separate_tickets": bool(option.get("separate_tickets")),
                    "flight_evidence_id": flight.id,
                },
            )
        )
    return items


def _normalize_news(raw_data: dict[str, Any]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    results = raw_data.get("news_results", [])

    for idx, article in enumerate(results[:10]):
        title = article.get("title", "News Article")
        source_info = article.get("source", {})
        source_name = source_info.get("name") if isinstance(source_info, dict) else str(source_info)
        link = article.get("link", "")
        snippet = article.get("snippet", "")
        date = article.get("date", "")

        items.append(
            EvidenceItem(
                id=f"ev_news_{idx+1}_{uuid.uuid4().hex[:4]}",
                engine="google_news",
                sourceName=source_name or "Google News",
                title=title,
                url=link,
                snippet=f"{snippet} ({date})" if date else snippet,
                metadata={"date": date},
            )
        )

    return items


def _normalize_google_web(raw_data: dict[str, Any]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []

    # Check for direct answer box
    ans_box = raw_data.get("answer_box", {})
    if isinstance(ans_box, dict) and ans_box:
        ans_title = ans_box.get("title") or "Direct Answer"
        ans_snippet = ans_box.get("snippet") or ans_box.get("answer") or ans_box.get("result") or ""
        ans_link = ans_box.get("link") or ""
        if ans_snippet:
            items.append(
                EvidenceItem(
                    id=f"ev_web_ans_{uuid.uuid4().hex[:4]}",
                    engine="google",
                    sourceName="Google Direct Answer",
                    title=ans_title,
                    url=ans_link,
                    snippet=ans_snippet,
                )
            )

    # Check for knowledge graph
    kg = raw_data.get("knowledge_graph", {})
    if isinstance(kg, dict) and kg.get("description"):
        kg_title = kg.get("title", "Knowledge Graph")
        kg_desc = kg.get("description", "")
        kg_link = kg.get("source", {}).get("link", "") if isinstance(kg.get("source"), dict) else ""
        items.append(
            EvidenceItem(
                id=f"ev_web_kg_{uuid.uuid4().hex[:4]}",
                engine="google",
                sourceName="Google Knowledge Graph",
                title=kg_title,
                url=kg_link,
                snippet=kg_desc,
            )
        )

    results = raw_data.get("organic_results", [])
    for idx, res in enumerate(results[:10]):
        title = res.get("title", "Web Result")
        link = res.get("link", "")
        snippet = res.get("snippet", "")
        source = res.get("displayed_link", "Google Search")

        items.append(
            EvidenceItem(
                id=f"ev_web_{idx+1}_{uuid.uuid4().hex[:4]}",
                engine="google",
                sourceName=source,
                title=title,
                url=link,
                snippet=snippet,
            )
        )

    return items
