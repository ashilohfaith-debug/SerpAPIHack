"""Evidence Store for Relay LiveWorld subsystem.

Features:
  - Short-lived in-memory query caching (5-minute TTL)
  - Request deduplication
  - Citation verification (validates referenced evidence IDs against stored evidence)
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from relay.diagnostics import get_logger
from relay.liveworld.types import EvidenceItem

log = get_logger("liveworld.evidence")

CACHE_TTL_SECONDS = 300.0  # 5 minutes cache TTL


class EvidenceStore:
    """In-memory store for normalized live evidence with TTL caching."""

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[float, list[EvidenceItem]]] = {}
        self._items_by_id: dict[str, EvidenceItem] = {}

    def _hash_key(self, engine: str, params: dict[str, Any]) -> str:
        raw = f"{engine}:{json.dumps(params, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_cached(self, engine: str, params: dict[str, Any]) -> list[EvidenceItem] | None:
        key = self._hash_key(engine, params)
        if key in self._cache:
            timestamp, items = self._cache[key]
            if time.time() - timestamp <= self.ttl:
                log.info("Evidence cache HIT for engine=%s", engine)
                return items
            else:
                log.info("Evidence cache EXPIRED for engine=%s", engine)
                del self._cache[key]
        return None

    def store(self, engine: str, params: dict[str, Any], items: list[EvidenceItem]) -> None:
        key = self._hash_key(engine, params)
        self._cache[key] = (time.time(), items)
        for item in items:
            self._items_by_id[item.id] = item

    def get_by_id(self, item_id: str) -> EvidenceItem | None:
        return self._items_by_id.get(item_id)

    def validate_citation_ids(self, ids: list[str]) -> list[str]:
        """Filters out non-existent evidence IDs to prevent hallucinated citations."""
        valid_ids: list[str] = []
        for eid in ids:
            if eid in self._items_by_id:
                valid_ids.append(eid)
            else:
                log.warning("Rejected invalid/hallucinated citation ID: %s", eid)
        return valid_ids

    def clear(self) -> None:
        self._cache.clear()
        self._items_by_id.clear()
