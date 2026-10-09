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

from relay.liveworld.broker import LiveWorldBroker
from relay.liveworld.evidence import EvidenceStore, evidence_fingerprint
from relay.liveworld.normalizers import normalize_serp_response
from relay.liveworld.planner import SearchPlanner
from relay.liveworld.provenance import ProvenanceGenerator
from relay.liveworld.ranking import GroundedDecisionEngine
from relay.liveworld.router import LiveWorldRouter
from relay.liveworld.serpapi import SerpApiClient, SerpApiUnavailableError, _usable_api_key
from relay.liveworld.types import EvidenceItem, RelayDecision, RelayIntent


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
        intent = self.router.classify("Relay, I'm going from Chennai to Bangalore tomorrow. Find a flight, hotel under ₹4,000 near Indiranagar, and dinner spot.")
        plan = self.planner.create_search_plan(intent)

        self.assertEqual(intent.category, "travel")
        engines = [s.engine for s in plan.searches]
        self.assertIn("google_flights", engines)
        self.assertIn("google_hotels", engines)
        self.assertIn("google_maps", engines)
        self.assertLessEqual(len(plan.searches), 6)
        flight_search = next(search for search in plan.searches if search.engine == "google_flights")
        self.assertEqual(flight_search.params["type"], "2")

    def test_router_preserves_multiword_route_am_and_next_week(self):
        intent = self.router.classify(
            "Find a flight from Chennai to New Delhi next week after 8 AM under 5,000"
        )
        self.assertEqual(intent.entities["origin"], "Chennai")
        self.assertEqual(intent.entities["destination"], "New Delhi")
        self.assertEqual(intent.entities["date"], "next week")
        self.assertEqual(intent.constraints["departure_after"], "8:00 AM")
        self.assertEqual(intent.constraints["max_price"], 5000.0)
        plan = self.planner.create_search_plan(intent)
        flight = next(item for item in plan.searches if item.engine == "google_flights")
        self.assertEqual(flight.params["departure_id"], "MAA")
        self.assertEqual(flight.params["arrival_id"], "DEL")
        self.assertEqual(flight.params["outbound_times"], "8,23")
        self.assertEqual(flight.params["max_price"], 5000)

    def test_date_qualified_spoken_route_uses_iata_codes(self):
        intent = self.router.classify("New York to Los Angeles on 2026-10-20")
        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "travel")
        self.assertEqual(intent.entities["origin"], "New York")
        self.assertEqual(intent.entities["destination"], "Los Angeles")
        self.assertEqual(intent.entities["date"], "2026-10-20")
        plan = self.planner.create_search_plan(intent)
        flight = next(item for item in plan.searches if item.engine == "google_flights")
        self.assertEqual(flight.params["departure_id"], "NYC")
        self.assertEqual(flight.params["arrival_id"], "LAX")

    def test_travel_request_never_invents_missing_origin(self):
        class AvailableClient:
            def is_available(self):
                return True

            def search(self, engine, params):
                raise AssertionError("search must not run before clarification")

        broker = LiveWorldBroker(api_client=AvailableClient())
        intent, decision, telemetry = broker.process(
            "Find the cheapest flight to Bangalore tomorrow"
        )
        self.assertTrue(intent.requires_live_data)
        self.assertIn("departure city", decision.answer)
        self.assertEqual(decision.confidence, 0.0)
        self.assertEqual(decision.action["type"], "none")
        self.assertEqual(telemetry.total_searches, 0)

    def test_unknown_city_requires_airport_code_before_search(self):
        class AvailableClient:
            def is_available(self):
                return True

            def search(self, engine, params):
                raise AssertionError("unknown city text must never reach SerpApi")

        broker = LiveWorldBroker(api_client=AvailableClient())
        intent, decision, telemetry = broker.process(
            "Find a flight from Atlantis to Los Angeles on 2026-10-20"
        )
        self.assertEqual(intent.entities["origin"], "Atlantis")
        self.assertIn("departure airport or three-letter code", decision.answer)
        self.assertEqual(decision.action["type"], "none")
        self.assertEqual(telemetry.total_searches, 0)

    def test_clarification_reply_completes_pending_route(self):
        class AvailableClient:
            def __init__(self):
                self.calls = []

            def is_available(self):
                return True

            def search(self, engine, params):
                self.calls.append((engine, params))
                return {
                    "best_flights": [
                        {
                            "price": 4200,
                            "flights": [
                                {
                                    "airline": "Example Air",
                                    "departure_airport": {
                                        "name": "Chennai",
                                        "time": "8:00 AM",
                                    },
                                    "arrival_airport": {
                                        "name": "New Delhi",
                                        "time": "10:30 AM",
                                    },
                                }
                            ],
                        }
                    ]
                }

        client = AvailableClient()
        broker = LiveWorldBroker(api_client=client)
        _intent, clarification, telemetry = broker.process(
            "Find a flight to New Delhi tomorrow"
        )
        self.assertIn("departure city", clarification.answer)
        self.assertEqual(telemetry.total_searches, 0)

        completed = broker.classify("Chennai")
        self.assertTrue(completed.requires_live_data)
        self.assertEqual(completed.entities["origin"], "Chennai")
        self.assertEqual(completed.entities["destination"], "New Delhi")
        intent, decision, telemetry = broker.process("Chennai")
        self.assertEqual(intent.entities["origin"], "Chennai")
        self.assertEqual(telemetry.total_searches, 1)
        self.assertGreater(decision.confidence, 0.9)
        self.assertEqual(client.calls[0][1]["departure_id"], "MAA")
        self.assertEqual(client.calls[0][1]["arrival_id"], "DEL")

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
        self.assertTrue(item.metadata["is_nonstop"])

    def test_flight_normalizer_does_not_label_connections_nonstop(self):
        raw = {
            "best_flights": [
                {
                    "price": 5000,
                    "flights": [
                        {
                            "airline": "Example Air",
                            "departure_airport": {"name": "Chennai", "time": "4:00 PM"},
                            "arrival_airport": {"name": "Hyderabad", "time": "5:15 PM"},
                        },
                        {
                            "airline": "Example Air",
                            "departure_airport": {"name": "Hyderabad", "time": "6:15 PM"},
                            "arrival_airport": {"name": "Bangalore", "time": "7:30 PM"},
                        },
                    ],
                    "booking_token": "booking-123",
                }
            ]
        }
        item = normalize_serp_response("google_flights", raw)[0]
        self.assertFalse(item.metadata["is_nonstop"])
        self.assertEqual(item.metadata["stops"], 1)
        self.assertIn("1 stop", item.snippet)
        self.assertNotIn("Nonstop", item.snippet)
        self.assertEqual(item.metadata["booking_token"], "booking-123")

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

    def test_serpapi_placeholder_key_is_never_online(self):
        self.assertFalse(_usable_api_key("your_serpapi_key_here"))
        self.assertFalse(SerpApiClient(api_key="replace-me").is_available())
        self.assertTrue(_usable_api_key("real-shaped-test-key"))
        with self.assertRaises(SerpApiUnavailableError):
            SerpApiClient(api_key="your_serpapi_key_here").search("google", {"q": "test"})

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

    def test_total_budget_is_a_hard_constraint(self):
        flight = EvidenceItem(
            id="ev_over_flight",
            engine="google_flights",
            title="Flight",
            price=7000,
            departureTime="6:00 PM",
            metadata={"is_nonstop": True},
        )
        hotel = EvidenceItem(
            id="ev_over_hotel",
            engine="google_hotels",
            title="Hotel",
            price=5000,
            rating=4.5,
        )
        for item in (flight, hotel):
            self.store.store(item.engine, {"q": item.id}, [item])
        intent = RelayIntent(
            True,
            "travel",
            "flight and hotel from Chennai to Bangalore tomorrow",
            entities={"origin": "Chennai", "destination": "Bangalore", "date": "tomorrow"},
            constraints={"nonstop": True, "max_total_budget": 10000},
        )
        decision = self.decision_engine.decide(intent, [flight, hotel])
        self.assertEqual(decision.action["type"], "none")
        self.assertEqual(decision.evidence_ids, [])
        self.assertIn("no verified flight and hotel combination", decision.answer)

    def test_total_budget_does_not_invent_a_hotel_cap(self):
        flight = EvidenceItem(
            id="ev_budget_flight",
            engine="google_flights",
            title="Flight",
            price=4000,
        )
        hotel = EvidenceItem(
            id="ev_budget_hotel",
            engine="google_hotels",
            title="Hotel",
            price=5000,
            rating=4.5,
        )
        for item in (flight, hotel):
            self.store.store(item.engine, {"q": item.id}, [item])
        intent = RelayIntent(
            True,
            "travel",
            "flight and hotel from Chennai to Bangalore tomorrow",
            entities={"origin": "Chennai", "destination": "Bangalore", "date": "tomorrow"},
            constraints={"max_total_budget": 10000},
        )
        decision = self.decision_engine.decide(intent, [flight, hotel])
        self.assertGreater(decision.confidence, 0.9)
        self.assertEqual(decision.evidence_ids, [flight.id, hotel.id])
        self.assertIn("₹9,000", decision.answer)

    def test_explicit_hotel_cap_remains_a_hard_constraint(self):
        hotel = EvidenceItem(
            id="ev_expensive_hotel",
            engine="google_hotels",
            title="Hotel",
            price=5000,
            rating=4.5,
        )
        self.store.store(hotel.engine, {"q": hotel.id}, [hotel])
        intent = RelayIntent(
            True,
            "travel",
            "hotel in Bangalore tomorrow",
            entities={"destination": "Bangalore", "date": "tomorrow"},
            constraints={"max_hotel_price": 4000},
        )
        decision = self.decision_engine.decide(intent, [hotel])
        self.assertEqual(decision.action["type"], "none")
        self.assertEqual(decision.evidence_ids, [])

    def test_travel_answer_only_narrates_requested_components(self):
        flight = EvidenceItem(
            id="ev_only_flight",
            engine="google_flights",
            title="Flight",
            sourceName="Example Air",
            price=4000,
        )
        hotel = EvidenceItem(
            id="ev_unrequested_hotel",
            engine="google_hotels",
            title="Hotel",
            price=3000,
            rating=4.5,
        )
        dinner = EvidenceItem(
            id="ev_unrequested_dinner",
            engine="google_maps",
            title="Dinner",
            rating=4.7,
        )
        for item in (flight, hotel, dinner):
            self.store.store(item.engine, {"q": item.id}, [item])
        intent = RelayIntent(
            True,
            "travel",
            "find a flight from Chennai to Bangalore tomorrow",
            entities={"origin": "Chennai", "destination": "Bangalore", "date": "tomorrow"},
        )
        decision = self.decision_engine.decide(intent, [flight, hotel, dinner])
        self.assertEqual(decision.evidence_ids, [flight.id])
        self.assertIn("Flight:", decision.answer)
        self.assertNotIn("Stay:", decision.answer)
        self.assertNotIn("Dinner:", decision.answer)

    def test_stable_fingerprint_excludes_same_fresh_result(self):
        previous = EvidenceItem(
            id="ev_previous",
            engine="google_flights",
            title="Example Air EA 10",
            sourceName="Example Air",
            price=4000,
            departureTime="8:00 AM",
            arrivalTime="10:00 AM",
        )
        refreshed = EvidenceItem(
            id="ev_refreshed",
            engine=previous.engine,
            title=previous.title,
            sourceName=previous.sourceName,
            price=previous.price,
            departureTime=previous.departureTime,
            arrivalTime=previous.arrivalTime,
        )
        self.store.store(previous.engine, {"q": "previous"}, [previous])
        self.store.store(refreshed.engine, {"q": "refreshed"}, [refreshed])
        intent = RelayIntent(
            True,
            "travel",
            "find another flight",
            constraints={"exclude_evidence_fingerprints": [evidence_fingerprint(previous)]},
        )
        decision = self.decision_engine.decide(intent, [refreshed])
        self.assertEqual(decision.evidence_ids, [])
        self.assertEqual(decision.action["type"], "none")

    def test_departure_constraint_rejects_missing_time(self):
        item = EvidenceItem(
            id="ev_flight_missing_time",
            engine="google_flights",
            title="Unknown schedule",
            price=2500,
            snippet="Nonstop flight",
            metadata={"is_nonstop": True},
        )
        self.store.store(item.engine, {"q": "test"}, [item])
        intent = RelayIntent(
            True,
            "travel",
            "flight after 5 PM",
            constraints={"nonstop": True, "departure_after": "5 PM"},
        )
        decision = self.decision_engine.decide(intent, [item])
        self.assertLess(decision.confidence, 0.5)
        self.assertEqual(decision.action["type"], "none")

    def test_actions_never_fall_back_to_uncited_generic_urls(self):
        item = EvidenceItem(
            id="ev_shop_no_url",
            engine="google_shopping",
            title="Grounded product",
            sourceName="Merchant",
            price=1000,
            url="",
        )
        self.store.store(item.engine, {"q": "test"}, [item])
        decision = self.decision_engine.decide(
            RelayIntent(True, "shopping", "buy product", constraints={"max_price": 2000}),
            [item],
        )
        self.assertEqual(decision.action["type"], "none")
        self.assertEqual(decision.action["target"], "")

    def test_short_follow_up_reuses_context_and_excludes_previous_choice(self):
        broker = LiveWorldBroker(api_client=SerpApiClient(api_key="test"))
        broker._last_intent = RelayIntent(
            True,
            "travel",
            "find a flight to Bangalore tomorrow",
            entities={"destination": "Bangalore", "date": "tomorrow"},
        )
        broker._last_decision = RelayDecision("first", 1.0, ["ev_flight_1"])
        follow_up = broker._intent_with_follow_up("find me another cheaper option")
        self.assertEqual(follow_up.category, "travel")
        self.assertEqual(follow_up.entities["destination"], "Bangalore")
        self.assertEqual(follow_up.constraints["prefer"], "cheapest")
        self.assertEqual(follow_up.constraints["exclude_evidence_ids"], ["ev_flight_1"])

    def test_session_routes_contextual_follow_up_through_broker(self):
        from relay.session import Session

        calls = []

        class ContextBroker:
            def classify(self, utterance):
                calls.append(("classify", utterance))
                return RelayIntent(True, "travel", utterance)

            def process(self, utterance, bus=None):
                calls.append(("process", utterance))
                return (
                    RelayIntent(True, "travel", utterance),
                    RelayDecision(
                        "Here is another verified option.",
                        0.9,
                        [],
                        action={"type": "none", "target": "", "label": ""},
                    ),
                    None,
                )

        spoken = []
        session = Session(speak=spoken.append, db_path=":memory:")
        session.live_world = ContextBroker()
        result = session.handle("find me another cheaper option")
        self.assertIn(("process", "find me another cheaper option"), calls)
        self.assertEqual(result, ["Here is another verified option."])

    def test_provenance_never_calls_a_connection_nonstop(self):
        item = EvidenceItem(
            id="ev_connection",
            engine="google_flights",
            title="Example Air via Hyderabad",
            price=5000,
            metadata={"is_nonstop": False, "stops": 1},
        )
        decision = RelayDecision("result", 1.0, [item.id])
        provenance = ProvenanceGenerator().build_provenance(decision, [item])
        self.assertIn("1 stop flight", provenance["why"][0])
        self.assertNotIn("nonstop", provenance["why"][0])

    def test_booking_token_resolves_verified_provider_without_purchase(self):
        class BookingClient:
            def is_available(self):
                return True

            def search(self, engine, params):
                self.engine = engine
                self.params = params
                return {
                    "booking_options": [
                        {
                            "together": {
                                "book_with": "Example Airlines",
                                "local_prices": [{"currency": "INR", "price": 3210}],
                                "booking_request": {
                                    "url": "https://www.google.com/travel/booking",
                                    "post_data": "token=opaque-value",
                                },
                            }
                        }
                    ]
                }

        client = BookingClient()
        broker = LiveWorldBroker(api_client=client)
        flight = EvidenceItem(
            id="ev_flight_book",
            engine="google_flights",
            title="Example Air EA 123",
            url="https://www.google.com/travel/flights",
            metadata={"booking_token": "booking-token"},
        )
        broker.store.store("google_flights", {"q": "flight"}, [flight])
        decision = broker.prepare_flight_booking(flight.id)
        self.assertEqual(client.engine, "google_flights")
        self.assertEqual(client.params["booking_token"], "booking-token")
        self.assertEqual(decision.action["type"], "open_booking")
        self.assertEqual(decision.action["postData"], "token=opaque-value")
        self.assertIn("has not purchased anything", decision.answer)

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
