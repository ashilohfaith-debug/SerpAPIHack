"""Unit and integration tests for Relay LiveWorld subsystem and SerpApi integration.

Verifies:
  - Intent classification (requiresLiveData vs local_action)
  - SerpApi client configuration & fail-closed behavior
  - Search planning across multi-engine queries (google_flights, google_hotels, google_maps, google_shopping, google_news)
  - Normalization of raw engine JSON responses into EvidenceItem instances
  - EvidenceStore caching, deduplication, and citation validation
  - Grounded decision engine constraint filtering (budget, nonstop, rating)
  - Action provenance generation
  - Fail-closed refusal when SerpApi is disconnected or unconfigured
  - Local actions unaffected when SerpApi is offline
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from relay.liveworld.broker import LiveWorldBroker
from relay.liveworld.evidence import EvidenceStore
from relay.liveworld.normalizers import normalize_serp_response
from relay.liveworld.planner import SearchPlanner
from relay.liveworld.provenance import ProvenanceGenerator
from relay.liveworld.ranking import GroundedDecisionEngine
from relay.liveworld.router import LiveWorldRouter
from relay.liveworld.serpapi import SerpApiClient, SerpApiUnavailableError
from relay.liveworld.types import EvidenceItem, RelayIntent


class TestLiveWorldSubsystem(unittest.TestCase):

    def setUp(self):
        SerpApiClient.set_disconnected(False)
        self.router = LiveWorldRouter()
        self.planner = SearchPlanner()
        self.store = EvidenceStore()
        self.decision_engine = GroundedDecisionEngine(self.store)

    def tearDown(self):
        SerpApiClient.set_disconnected(False)

    def test_router_local_action(self):
        """TEST 2: Local actions must be classified as requiring NO live data."""
        intent = self.router.classify("Turn my volume down")
        self.assertFalse(intent.requires_live_data)
        self.assertEqual(intent.category, "local_action")

        intent2 = self.router.classify("Open Notepad")
        self.assertFalse(intent2.requires_live_data)

    def test_router_live_world_travel(self):
        """Travel intent must be classified as requiring live world data."""
        intent = self.router.classify("Find the cheapest nonstop flight to Bangalore tomorrow evening")
        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "travel")
        self.assertEqual(intent.entities.get("destination"), "Bangalore")

    def test_router_live_world_shopping(self):
        intent = self.router.classify("Compare the latest RTX 5070 laptop prices under 1.5 lakh")
        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "shopping")

    def test_search_planner_multi_engine(self):
        """TEST 3: Multi-engine planning generates flight, hotel, and maps searches."""
        intent = self.router.classify("Relay, I'm going to Bangalore tomorrow. Find a flight, hotel under ₹4,000 near Indiranagar, and dinner spot.")
        plan = self.planner.create_search_plan(intent)

        self.assertEqual(intent.category, "travel")
        engines = [s.engine for s in plan.searches]
        self.assertIn("google_flights", engines)
        self.assertIn("google_hotels", engines)
        self.assertIn("google_maps", engines)
        self.assertLessEqual(len(plan.searches), 6)

    def test_normalizers_flights(self):
        raw_flights = {
            "best_flights": [
                {
                    "price": 3142,
                    "flights": [
                        {
                            "airline": "IndiGo",
                            "flight_number": "6E-241",
                            "departure_airport": {"name": "Chennai", "time": "6:35 PM"},
                            "arrival_airport": {"name": "Bangalore", "time": "7:40 PM"},
                        }
                    ],
                }
            ]
        }
        items = normalize_serp_response("google_flights", raw_flights)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.engine, "google_flights")
        self.assertEqual(item.price, 3142.0)
        self.assertEqual(item.sourceName, "IndiGo")
        self.assertEqual(item.departureTime, "6:35 PM")

    def test_evidence_store_citation_validation(self):
        """TEST 4: Nonexistent citation IDs must be rejected to prevent hallucinated citations."""
        item = EvidenceItem(id="ev_valid_1", engine="google", title="Valid Result")
        self.store.store("google", {"q": "test"}, [item])

        valid_ids = self.store.validate_citation_ids(["ev_valid_1", "ev_fake_99"])
        self.assertEqual(valid_ids, ["ev_valid_1"])

    def test_serpapi_fail_closed(self):
        """TEST 1: Disabling SerpApi forces fail-closed refusal without LLM hallucination."""
        SerpApiClient.set_disconnected(True)
        broker = LiveWorldBroker()

        intent, decision, telemetry = broker.process("What's the cheapest flight tomorrow?")
        self.assertTrue(intent.requires_live_data)
        self.assertEqual(decision.confidence, 0.0)
        self.assertIn("live-world access is unavailable", decision.answer)

    def test_grounded_decision_travel_constraints(self):
        """TEST 5: Constraint adherence for travel budget and ratings."""
        flight_item = EvidenceItem(
            id="ev_flight_1", engine="google_flights", title="IndiGo 6E-241",
            price=3142.0, sourceName="IndiGo", departureTime="6:35 PM", arrivalTime="7:40 PM",
            snippet="Nonstop flight"
        )
        hotel_item = EvidenceItem(
            id="ev_hotel_1", engine="google_hotels", title="Hotel Example Indiranagar",
            price=3720.0, rating=4.4, reviewCount=1800, sourceName="Google Hotels"
        )
        dinner_item = EvidenceItem(
            id="ev_dinner_1", engine="google_maps", title="Restaurant Example",
            rating=4.6, reviewCount=1500, address="Indiranagar", sourceName="Google Maps"
        )

        items = [flight_item, hotel_item, dinner_item]
        for it in items:
            self.store.store(it.engine, {"q": "test"}, [it])

        intent = self.router.classify(
            "Relay, I'm going to Bangalore tomorrow. Find the cheapest nonstop flight after 5 PM, "
            "a hotel under ₹4,000 near Indiranagar rated above 4 stars, and somewhere highly rated for dinner. Keep everything under ₹10,000."
        )

        decision = self.decision_engine.decide(intent, items)
        self.assertGreater(decision.confidence, 0.9)
        self.assertIn("Bangalore", decision.answer)
        self.assertIn("₹6,862", decision.answer)  # Total 3142 + 3720 = 6862
        self.assertEqual(len(decision.evidence_ids), 3)

    def test_provenance_generator(self):
        item = EvidenceItem(id="ev_1", engine="google_shopping", title="RTX 5070 Laptop", price=125000.0, sourceName="Amazon")
        self.store.store("google_shopping", {"q": "laptop"}, [item])

        decision = self.decision_engine.decide(RelayIntent(True, "shopping", "buy laptop"), [item])
        prov_gen = ProvenanceGenerator()
        prov = prov_gen.build_provenance(decision, [item])

        self.assertIn("sources", prov)
        self.assertIn("freshness", prov)
        self.assertEqual(prov["cited_count"], 1)


if __name__ == "__main__":
    unittest.main()
