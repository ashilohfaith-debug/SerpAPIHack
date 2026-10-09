"""Live-world Router for classifying user intent.

Determines:
  - requires_live_data (bool)
  - category (travel, shopping, local, news, research, general, local_action)
  - objective
  - extracted entities (origin, destination, budget, location, date, time)
  - extracted constraints (max_price, min_rating, nonstop, time_after, etc.)
"""

from __future__ import annotations

import re
from typing import Any

from relay.diagnostics import get_logger
from relay.liveworld.types import Category, RelayIntent

log = get_logger("liveworld.router")

# Obvious local actions that DO NOT require live world data
LOCAL_PATTERNS = [
    r"\b(?:turn|set|raise|lower|mute|unmute)\s+(?:(?:the|my)\s+)?volume\b",
    r"\b(?:open|close|launch|switch\s+to)\s+(?:notepad|calculator|vs\s*code|browser|chrome|edge|explorer|word|excel|settings|terminal|cmd|powershell|spotify)\b",
    r"^(?:relay[, ]+)?(?:open|close|show)\s+(?:(?:the|another|my)\s+)?(?:file|folder|document)\b",
    r"^(?:relay[, ]+)?(?:(?:emergency\s+)?stop|pause|resume|continue|cancel|help)\b",
    r"^(?:relay[, ]+)?(?:read|spell)\b(?!.*\b(?:news|latest|current|prices|flights|hotels)\b)",
    r"^(?:relay[, ]+)?(?:what\s+time|what\s+is\s+the\s+date|battery|volume|status)\b",
    r"\b(?:where\s+am\s+i|what'?s\s+on\s+(?:my\s+)?screen|describe\s+(?:my\s+)?screen|what\s+do\s+you\s+see)\b",
    r"\b(?:where\s+is\s+(?:the\s+)?sound\s+going|headphone\s+mode|speaker|speaking\s+through)\b",
    r"\b(?:create|make)\s+(?:a\s+)?new\s+(?:folder|file)\b",
    r"\b(?:new\s+folder|new\s+file|rename|copy|move|delete)\b",
    r"\b(?:remember|forget|show\s+notes|add\s+note|clear\s+history)\b",
    r"\b(?:type|dictate)\s+",
]

# Live world triggers
LIVE_WORLD_PATTERNS = {
    "travel": [
        r"\b(?:flight|flights|hotel|hotels|stay|resort|ticket|tickets|flying|fly|trip|travel)\b",
        r"\b(?:go\s+to|going\s+to|visit)\s+([a-zA-Z\s]+)\s+(?:tomorrow|tonight|next\s+week|on\s+[a-zA-Z]+)\b",
    ],
    "shopping": [
        r"\b(?:buy|price|prices|cheap|cheapest|deal|deals|cost|costs|laptop|phone|rtx|graphics\s+card|tv|monitor|specs|review)\b",
        r"\bunder\s+(?:₹|\$|rs\.?|inr)?\s*[\d,]+\b",
    ],
    "local": [
        r"\b(?:restaurant|restaurants|cafe|cafes|food|dinner|lunch|breakfast|place|places|bar|pub|atm|hospital)\s+(?:near|in|around)\b",
        r"\b(?:open\s+tonight|open\s+now|highly\s+rated|rated\s+above)\b",
    ],
    "news": [
        r"\b(?:news|happened|events|headlines|latest\s+update|what\s+happened\s+with)\b",
        r"\b(?:today|yesterday|this\s+week)\s+with\b",
    ],
    "research": [
        r"\b(?:compare|versus|vs|differences|latest\s+information|current\s+status|research)\b",
        r"\b(?:who\s+is\s+currently|what\s+is\s+the\s+current|latest\s+version)\b",
    ],
}


class LiveWorldRouter:
    """Fast deterministic intent router with fallback parsing."""

    def classify(self, utterance: str) -> RelayIntent:
        raw = utterance.strip()
        low = raw.lower()

        # Step 1: Check for deterministic local actions
        for pat in LOCAL_PATTERNS:
            if re.search(pat, low):
                return RelayIntent(
                    requires_live_data=False,
                    category="local_action",
                    objective=raw,
                    confidence=1.0,
                )

        # Step 2: Check for live world category match
        detected_category: Category | None = None
        for cat in ("travel", "news", "local", "shopping", "research"):
            patterns = LIVE_WORLD_PATTERNS[cat]
            for pat in patterns:
                if re.search(pat, low):
                    detected_category = cat  # type: ignore
                    break
            if detected_category:
                break

        # Spoken route shorthand often omits the word "flight", for example
        # "New York to Los Angeles on 2026-10-20". A date-qualified route is
        # specific enough to treat as travel instead of sending it to web search.
        if not detected_category and re.match(
            r"^(?:relay[, ]+)?[a-z][a-z .'-]*?\s+to\s+[a-z][a-z .'-]*?\s+"
            r"(?:today|tomorrow|tonight|next\s+week|on\s+(?:[a-z]+|\d{4}-\d{2}-\d{2}))\b",
            low,
        ):
            detected_category = "travel"

        # If no explicit live pattern, check for generic questions asking about current/live information
        if not detected_category:
            if re.search(r"\b(?:today|now|current|latest|price|best|top)\b", low):
                detected_category = "research"

        if not detected_category:
            # Default fallback for general questions
            return RelayIntent(
                requires_live_data=False,
                category="general",
                objective=raw,
                confidence=0.8,
            )

        # Extract entities and constraints from text
        entities, constraints = self._extract_entities_and_constraints(raw, low, detected_category)
        if (
            detected_category == "travel"
            and entities.get("origin")
            and entities.get("destination")
            and not re.search(
                r"\b(?:flight|flights|fly|flying|ticket|tickets|hotel|hotels|stay|resort|dinner|restaurant|food)\b",
                low,
            )
        ):
            constraints["wants_flight"] = True

        return RelayIntent(
            requires_live_data=True,
            category=detected_category,
            objective=raw,
            entities=entities,
            constraints=constraints,
            confidence=0.95,
        )

    def _extract_entities_and_constraints(
        self, raw: str, low: str, category: Category
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        entities: dict[str, Any] = {}
        constraints: dict[str, Any] = {}

        # Travel entity extraction. Capture multi-word places, but stop before
        # dates/constraints so "New Delhi next week" never becomes an airport name.
        stop = (
            r"(?=\s+(?:today|tomorrow|tonight|next\s+week|"
            r"on\s+(?:[a-z]+|\d{4}-\d{2}-\d{2})|after\b|"
            r"before\b|under\b|nonstop\b|direct\b|rated\b|near\b|with\b|and\b|for\b)"
            r"|[,.]|$)"
        )
        route_match = re.search(
            rf"\bfrom\s+([a-z][a-z .'-]*?)\s+to\s+([a-z][a-z .'-]*?){stop}",
            low,
            re.IGNORECASE,
        )
        if not route_match:
            route_match = re.search(
                rf"^(?:relay[, ]+)?(?:find|show|book|search)(?:\s+me)?(?:\s+the)?"
                rf"(?:\s+(?:cheapest|best|nonstop|direct))*(?:\s+a)?"
                rf"\s+(?:flight|flights|ticket|tickets)\s+"
                rf"([a-z][a-z .'-]*?)\s+to\s+([a-z][a-z .'-]*?){stop}",
                low,
                re.IGNORECASE,
            )
        if not route_match and not re.match(r"^(?:relay[, ]+)?(?:find|show|book|search)\b", low):
            route_match = re.search(
                rf"^(?:relay[, ]+)?([a-z][a-z .'-]*?)\s+to\s+"
                rf"([a-z][a-z .'-]*?){stop}",
                low,
                re.IGNORECASE,
            )
        if route_match:
            entities["origin"] = self._clean_place(route_match.group(1))
            entities["destination"] = self._clean_place(route_match.group(2))
        else:
            from_match = re.search(rf"\bfrom\s+([a-z][a-z .'-]*?){stop}", low, re.I)
            if from_match:
                entities["origin"] = self._clean_place(from_match.group(1))
            dest_match = re.search(
                rf"\b(?:going|go|flying|fly|travel(?:ling)?|trip)?\s*"
                rf"(?:to|in|at|around)\s+([a-z][a-z .'-]*?){stop}",
                low,
                re.IGNORECASE,
            )
            if dest_match:
                dest = self._clean_place(dest_match.group(1))
                if dest.lower() not in {"the", "a", "an", "my", "some"}:
                    entities["destination"] = dest

        # Date extraction
        if "tomorrow" in low:
            entities["date"] = "tomorrow"
        elif "today" in low or "tonight" in low:
            entities["date"] = "today"
        elif "next week" in low:
            entities["date"] = "next week"
        else:
            iso_date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", low)
            weekday = re.search(
                r"\bon\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
                low,
            )
            if iso_date:
                entities["date"] = iso_date.group(1)
            elif weekday:
                entities["date"] = weekday.group(1)

        # Time constraints
        time_after = re.search(r"\bafter\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", low)
        if time_after:
            minute = time_after.group(2) or "00"
            constraints["departure_after"] = (
                f"{time_after.group(1)}:{minute} {time_after.group(3).upper()}"
            )

        # Nonstop constraint
        if "nonstop" in low or "direct" in low:
            constraints["nonstop"] = True

        # Rating constraint (e.g. "above 4 stars", "rated 4.5+")
        rating_match = re.search(r"(?:above|rated|>)\s*(\d+(?:\.\d+)?)\s*(?:stars|star|\+)?", low)
        if rating_match:
            constraints["min_rating"] = float(rating_match.group(1))

        # Location area constraint
        near_match = re.search(
            r"\bnear\s+([A-Za-z0-9\s]+?)(?:\s+rated|\s+under|\s+open|\s+after|\.|\,|$)",
            raw,
            re.IGNORECASE,
        )
        if near_match:
            entities["location_area"] = near_match.group(1).strip()

        # Price / budget extraction (supports ₹, rs, rupees, lakh, k)
        # 1. Total budget: "keep everything under ₹10,000"
        total_budget_m = re.search(
            r"(?:everything|total|overall)\s+under\s+(?:₹|rs\.?|rupees|inr)?\s*([\d,]+)", low
        )
        if total_budget_m:
            constraints["max_total_budget"] = float(total_budget_m.group(1).replace(",", ""))

        # 2. Hotel budget: "hotel under ₹4,000"
        hotel_budget_m = re.search(r"hotel\s+under\s+(?:₹|rs\.?|rupees|inr)?\s*([\d,]+)", low)
        if hotel_budget_m:
            constraints["max_hotel_price"] = float(hotel_budget_m.group(1).replace(",", ""))

        # 3. Laptop/item budget: "under ₹1.5 lakh" or "under 150000"
        lakh_m = re.search(r"under\s+(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*lakh", low)
        if lakh_m:
            constraints["max_price"] = float(lakh_m.group(1)) * 100000
        else:
            gen_price_m = re.search(r"under\s+(?:₹|rs\.?|rupees|inr)?\s*([\d,]+)", low)
            if (
                gen_price_m
                and "max_total_budget" not in constraints
                and "max_hotel_price" not in constraints
            ):
                constraints["max_price"] = float(gen_price_m.group(1).replace(",", ""))

        # Cheapest preference
        if "cheapest" in low or "lowest price" in low:
            constraints["prefer"] = "cheapest"

        return entities, constraints

    @staticmethod
    def _clean_place(value: str) -> str:
        return " ".join(value.strip(" .,-").split()).title()
