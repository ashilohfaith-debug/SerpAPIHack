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

import time
import uuid
from typing import Any

from relay.diagnostics import get_logger
from relay.liveworld.types import EngineType, EvidenceItem

log = get_logger("liveworld.normalizers")


def normalize_serp_response(engine: EngineType, raw_data: dict[str, Any]) -> list[EvidenceItem]:
    """Route raw SerpApi engine response to its corresponding normalizer."""
    if engine == "google_flights":
        return _normalize_flights(raw_data)
    elif engine == "google_hotels":
        return _normalize_hotels(raw_data)
    elif engine == "google_maps":
        return _normalize_maps(raw_data)
    elif engine == "google_shopping":
        return _normalize_shopping(raw_data)
    elif engine == "google_news":
        return _normalize_news(raw_data)
    else:
        return _normalize_google_web(raw_data)


def _normalize_flights(raw_data: dict[str, Any]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []

    # Check best_flights and other_flights arrays
    flight_groups = raw_data.get("best_flights", []) + raw_data.get("other_flights", [])

    for idx, flight in enumerate(flight_groups[:10]):
        flights_list = flight.get("flights", [])
        if not flights_list:
            continue
        
        first_leg = flights_list[0]
        airline = first_leg.get("airline", "Airline")
        flight_num = first_leg.get("flight_number", "")
        dep_airport = first_leg.get("departure_airport", {}).get("name", "Origin")
        arr_airport = first_leg.get("arrival_airport", {}).get("name", "Destination")
        dep_time = first_leg.get("departure_airport", {}).get("time", "")
        arr_time = first_leg.get("arrival_airport", {}).get("time", "")

        price = flight.get("price")
        if isinstance(price, (int, float)):
            price_val = float(price)
        else:
            price_val = 0.0

        title = f"{airline} {flight_num} ({dep_time} → {arr_time})" if flight_num else f"{airline} ({dep_time} → {arr_time})"
        url = raw_data.get("search_metadata", {}).get("google_flights_url", "https://www.google.com/travel/flights")

        items.append(
            EvidenceItem(
                id=f"ev_flight_{idx+1}_{uuid.uuid4().hex[:4]}",
                engine="google_flights",
                sourceName=airline,
                title=title,
                url=url,
                snippet=f"Nonstop flight from {dep_airport} to {arr_airport}. Price: ₹{price_val:,.0f}.",
                price=price_val,
                currency="INR",
                departureTime=dep_time,
                arrivalTime=arr_time,
                metadata={"airline": airline, "flight_number": flight_num, "raw_flight": flight},
            )
        )

    return items


def _normalize_hotels(raw_data: dict[str, Any]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    properties = raw_data.get("properties", [])

    for idx, prop in enumerate(properties[:10]):
        title = prop.get("name", "Hotel Property")
        rate_info = prop.get("rate_per_night", {})
        extracted_price = rate_info.get("extracted_before_taxes") or rate_info.get("extracted_lowest") or prop.get("extracted_price", 0)
        
        rating = prop.get("overall_rating") or prop.get("rating")
        reviews = prop.get("reviews") or prop.get("review_count")
        description = prop.get("description", "") or prop.get("snippet", "")
        link = prop.get("link", "https://www.google.com/travel/hotels")

        items.append(
            EvidenceItem(
                id=f"ev_hotel_{idx+1}_{uuid.uuid4().hex[:4]}",
                engine="google_hotels",
                sourceName="Google Hotels",
                title=title,
                url=link,
                snippet=description or f"Hotel in target area rated {rating} stars with {reviews} reviews.",
                price=float(extracted_price) if extracted_price else None,
                currency="INR",
                rating=float(rating) if rating else None,
                reviewCount=int(reviews) if reviews else None,
                metadata={"hotel_class": prop.get("hotel_class"), "amenities": prop.get("amenities", [])},
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
        link = place.get("website") or place.get("link") or "https://maps.google.com"
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
                metadata={"place_id": place.get("place_id"), "hours": place.get("operating_hours")},
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
        link = prod.get("link") or prod.get("product_link", "https://google.com/shopping")
        rating = prod.get("rating")
        reviews = prod.get("reviews")

        items.append(
            EvidenceItem(
                id=f"ev_shop_{idx+1}_{uuid.uuid4().hex[:4]}",
                engine="google_shopping",
                sourceName=source,
                title=title,
                url=link,
                snippet=f"Available from {source} for ₹{price:,.0f}." if isinstance(price, (int, float)) else f"Available from {source}.",
                price=float(price) if isinstance(price, (int, float)) else None,
                currency="INR",
                rating=float(rating) if rating else None,
                reviewCount=int(reviews) if reviews else None,
                metadata={"merchant": source},
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
