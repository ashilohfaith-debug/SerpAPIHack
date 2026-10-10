"""Comprehensive integration tests verifying all 8 Hackathon scenarios.

Tests:
  1. Google Flights Integration (Route parsing, IATA resolution, nonstop, departure time, cheapest, booking token handoff)
  2. Google Hotels Integration (Indiranagar Bangalore, Connaught Place Delhi budget, check-in/out, rating >= 4, open hotel)
  3. Google Maps Integration (Places open tonight with verified hours, Cafes in Bandra Mumbai open status)
  4. Google Shopping Integration (RTX 4060 laptop under 80000 + review check, iPhone 15 cheapest deals with delivery)
  5. Google News Integration (Indian space missions freshness, stock market top headlines)
  6. General Google Web Search & Research (Latest Python version, MacBook Air M3 vs Dell XPS 13 battery life)
  7. Multi-Engine Composite Query (Flagship: Flights + Hotels + Maps in parallel, <= 10,000 total budget verification)
  8. Architectural Fail-Closed Verification (Offline refusal + immediate local battery percentage)
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from relay.liveworld.broker import LiveWorldBroker
from relay.liveworld.planner import SearchPlanner
from relay.liveworld.router import LiveWorldRouter
from relay.liveworld.serpapi import SerpApiClient
from relay.session import Session


class MockSerpApiClient:
    """Mock client recording calls and returning engine fixtures."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._available = True

    def is_available(self) -> bool:
        return self._available

    def set_available(self, val: bool):
        self._available = val

    def search(self, engine: str, params: dict) -> dict:
        self.calls.append((engine, params))
        if engine == "google_flights":
            if "booking_token" in params:
                return {
                    "booking_options": [
                        {
                            "together": {
                                "book_with": "IndiGo Airlines",
                                "local_prices": [{"currency": "INR", "price": 3142}],
                                "booking_request": {
                                    "url": "https://www.goindigo.in/booking/handoff",
                                    "post_data": "token=indigo-handoff-123",
                                },
                            }
                        }
                    ]
                }
            return {
                "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights/search"},
                "best_flights": [
                    {
                        "price": 3142,
                        "booking_token": "booking_tok_6e241",
                        "flights": [
                            {
                                "airline": "IndiGo",
                                "flight_number": "6E-241",
                                "departure_airport": {"name": "Delhi", "time": "18:30"},
                                "arrival_airport": {"name": "Mumbai", "time": "20:45"},
                            }
                        ],
                    }
                ],
            }
        elif engine == "google_hotels":
            return {
                "properties": [
                    {
                        "name": "The Oberoi Grand Indiranagar",
                        "overall_rating": 4.5,
                        "reviews": 1200,
                        "rate_per_night": {"extracted_lowest": 3720},
                        "link": "https://hotels.example/oberoi-indiranagar",
                        "address": "100 Feet Road, Indiranagar, Bangalore",
                    }
                ]
            }
        elif engine == "google_maps":
            return {
                "local_results": [
                    {
                        "title": "Toit Brewpub Koramangala",
                        "rating": 4.6,
                        "reviews": 4500,
                        "address": "100 Ft Rd, Koramangala, Bangalore",
                        "link": "https://maps.example/toit",
                        "type": "Microbrewery & Dinner",
                        "open_state": "Open ⋅ Closes 11:30 PM",
                        "hours": "Open ⋅ Closes 11:30 PM",
                    }
                ]
            }
        elif engine == "google_shopping":
            return {
                "shopping_results": [
                    {
                        "title": "Lenovo LOQ RTX 4060 Gaming Laptop",
                        "price": 76990,
                        "extracted_price": 76990,
                        "source": "Flipkart",
                        "link": "https://flipkart.example/loq4060",
                        "delivery": "Delivery tomorrow",
                    },
                    {
                        "title": "HP Victus RTX 4060 Gaming Laptop",
                        "price": 78990,
                        "extracted_price": 78990,
                        "source": "Amazon India",
                        "link": "https://amazon.example/victus4060",
                        "delivery": "Free delivery",
                    },
                    {
                        "title": "Acer Nitro V RTX 4060 Gaming Laptop",
                        "price": 79999,
                        "extracted_price": 79999,
                        "source": "Croma",
                        "link": "https://croma.example/nitrov4060",
                        "delivery": "Standard delivery",
                    },
                ]
            }
        elif engine == "google_news":
            return {
                "news_results": [
                    {
                        "title": "ISRO announces next Chandrayaan exploration milestone",
                        "source": {"name": "The Hindu"},
                        "link": "https://thehindu.example/isro-mission",
                        "date": "2 hours ago",
                        "snippet": "India's space agency announced key milestones for upcoming missions.",
                    },
                    {
                        "title": "Gaganyaan crew module undergoes crucial high-altitude test",
                        "source": {"name": "PTI"},
                        "link": "https://pti.example/gaganyaan",
                        "date": "5 hours ago",
                        "snippet": "Test flight validates life-support systems.",
                    },
                ]
            }
        elif engine == "google":
            return {
                "answer_box": {
                    "title": "Python Latest Release",
                    "snippet": "Python 3.13 was released as the latest stable version this year.",
                    "link": "https://docs.python.org/release",
                },
                "organic_results": [
                    {
                        "title": "MacBook Air M3 vs Dell XPS 13 Battery Life Benchmark",
                        "link": "https://benchmarks.example/m3-vs-xps13",
                        "snippet": "MacBook Air M3 achieved 15 hours 13 minutes web browsing while Dell XPS 13 achieved 12 hours 20 minutes in standard battery rundown tests.",
                        "displayed_link": "Tom's Guide",
                    }
                ],
            }
        return {}


class TestHackathonAll8Scenarios(unittest.TestCase):

    def setUp(self):
        SerpApiClient.set_disconnected(False)
        self.router = LiveWorldRouter()
        self.planner = SearchPlanner()
        self.mock_client = MockSerpApiClient()
        self.broker = LiveWorldBroker(api_client=self.mock_client)

    def tearDown(self):
        SerpApiClient.set_disconnected(False)

    # --------------------------------------------------------------------------
    # Scenario 1: Google Flights Integration
    # --------------------------------------------------------------------------
    def test_scenario_1_question_1_route_and_time_filter(self):
        """Test Question 1: 'Relay, find the cheapest flight from Delhi to Mumbai tomorrow after 6 PM.'"""
        utterance = "Relay, find the cheapest flight from Delhi to Mumbai tomorrow after 6 PM."
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "travel")
        self.assertEqual(intent.entities.get("origin"), "Delhi")
        self.assertEqual(intent.entities.get("destination"), "Mumbai")
        self.assertEqual(intent.entities.get("date"), "tomorrow")
        self.assertEqual(intent.constraints.get("departure_after"), "6:00 PM")
        self.assertEqual(intent.constraints.get("prefer"), "cheapest")

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_flights"])

        flight_params = plan.searches[0].params
        self.assertEqual(flight_params["departure_id"], "DEL")
        self.assertEqual(flight_params["arrival_id"], "BOM")
        self.assertEqual(flight_params["type"], "2")  # One-way
        self.assertEqual(flight_params["sort_by"], "2")  # Cheapest
        self.assertEqual(flight_params["outbound_times"], "18,23")  # After 18:00
        self.assertEqual(
            flight_params["outbound_date"],
            (date.today() + timedelta(days=1)).isoformat(),
        )

    def test_scenario_1_question_2_strict_nonstop_and_budget(self):
        """Test Question 2: 'Relay, find a nonstop flight from Bangalore to Kolkata next week under 7000.'"""
        utterance = "Relay, find a nonstop flight from Bangalore to Kolkata next week under 7000."
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "travel")
        self.assertEqual(intent.entities.get("origin"), "Bangalore")
        self.assertEqual(intent.entities.get("destination"), "Kolkata")
        self.assertEqual(intent.entities.get("date"), "next week")
        self.assertTrue(intent.constraints.get("nonstop"))
        self.assertEqual(intent.constraints.get("max_price"), 7000.0)

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_flights"])

        flight_params = plan.searches[0].params
        self.assertEqual(flight_params["departure_id"], "BLR")
        self.assertEqual(flight_params["arrival_id"], "CCU")
        self.assertEqual(flight_params["stops"], "1")  # Direct / nonstop only
        self.assertEqual(flight_params["max_price"], 7000)
        self.assertEqual(
            flight_params["outbound_date"],
            (date.today() + timedelta(days=7)).isoformat(),
        )

    def test_scenario_1_followup_booking_handoff(self):
        """Follow-up: 'Relay, book the flight.' resolves booking token via Google Flights."""
        opened_urls = []
        with patch("relay.system.web.open_booking_request", lambda url, data="": opened_urls.append((url, data))):
            session = Session(speak=lambda t: None, db_path=":memory:")
            session.live_world = self.broker

            # Find flight first
            session.handle("Relay, find the cheapest flight from Delhi to Mumbai tomorrow after 6 PM.")
            self.assertEqual(len(self.mock_client.calls), 1)

            # Book follow-up
            result = session.handle("Relay, book the flight.")
            self.assertTrue(any("IndiGo Airlines" in r for r in result))
            self.assertEqual(len(self.mock_client.calls), 2)
            self.assertEqual(self.mock_client.calls[1][0], "google_flights")
            self.assertEqual(self.mock_client.calls[1][1]["booking_token"], "booking_tok_6e241")
            self.assertEqual(opened_urls, [("https://www.goindigo.in/booking/handoff", "token=indigo-handoff-123")])

    # --------------------------------------------------------------------------
    # Scenario 2: Google Hotels Integration
    # --------------------------------------------------------------------------
    def test_scenario_2_question_1_location_and_rating(self):
        """Test Question 1: 'Relay, find hotels in Indiranagar Bangalore tomorrow rated above 4 stars.'"""
        utterance = "Relay, find hotels in Indiranagar Bangalore tomorrow rated above 4 stars."
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "travel")
        self.assertEqual(intent.entities.get("location_area"), "Indiranagar")
        self.assertEqual(intent.entities.get("destination"), "Bangalore")
        self.assertEqual(intent.entities.get("date"), "tomorrow")
        self.assertEqual(intent.constraints.get("min_rating"), 4.0)

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_hotels"])

        hotel_params = plan.searches[0].params
        self.assertEqual(hotel_params["q"], "hotels in Indiranagar Bangalore")
        self.assertEqual(
            hotel_params["check_in_date"],
            (date.today() + timedelta(days=1)).isoformat(),
        )
        self.assertEqual(
            hotel_params["check_out_date"],
            (date.today() + timedelta(days=2)).isoformat(),
        )
        self.assertEqual(hotel_params["rating"], "4")

    def test_scenario_2_question_2_strict_budget_constraint(self):
        """Test Question 2: 'Relay, find a hotel near Connaught Place in Delhi tomorrow under 3500.'"""
        utterance = "Relay, find a hotel near Connaught Place in Delhi tomorrow under 3500."
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "travel")
        self.assertEqual(intent.entities.get("location_area"), "Connaught Place")
        self.assertEqual(intent.entities.get("destination"), "Delhi")
        self.assertEqual(intent.constraints.get("max_hotel_price"), 3500.0)

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_hotels"])

        hotel_params = plan.searches[0].params
        self.assertEqual(hotel_params["max_price"], 3500)
        self.assertEqual(hotel_params["q"], "hotels in Connaught Place Delhi")

    def test_scenario_2_followup_open_hotel(self):
        """Follow-up: 'Relay, open the hotel.' opens exact cited hotel booking link."""
        opened_urls = []
        with patch("relay.system.web.open_booking_request", lambda url, data="": opened_urls.append(url)):
            session = Session(speak=lambda t: None, db_path=":memory:")
            session.live_world = self.broker

            session.handle("Relay, find hotels in Indiranagar Bangalore tomorrow rated above 4 stars.")
            result = session.handle("Relay, open the hotel.")
            self.assertEqual(result, ["Opened https://hotels.example/oberoi-indiranagar"])
            self.assertEqual(opened_urls, ["https://hotels.example/oberoi-indiranagar"])

    # --------------------------------------------------------------------------
    # Scenario 3: Google Maps Integration
    # --------------------------------------------------------------------------
    def test_scenario_3_question_1_places_open_tonight(self):
        """Test Question 1: 'Relay, find highly rated dinner restaurants near Koramangala that are open tonight.'"""
        utterance = "Relay, find highly rated dinner restaurants near Koramangala that are open tonight."
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "local")
        self.assertEqual(intent.entities.get("location_area"), "Koramangala")
        self.assertEqual(intent.constraints.get("min_rating"), 4.0)
        self.assertTrue(intent.constraints.get("open_tonight"))

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_maps"])
        self.assertEqual(plan.searches[0].params["type"], "search")

        # Execute decision
        _intent, decision, _telemetry = self.broker.process(utterance)
        self.assertGreater(decision.confidence, 0.9)
        self.assertIn("Toit Brewpub Koramangala", decision.answer)
        self.assertIn("4.6", decision.answer)
        self.assertIn("Koramangala", decision.answer)

    def test_scenario_3_question_2_cafes_and_local_services(self):
        """Test Question 2: 'Relay, find top rated cafes near Bandra in Mumbai.'"""
        utterance = "Relay, find top rated cafes near Bandra in Mumbai."
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "local")
        self.assertEqual(intent.entities.get("location_area"), "Bandra")
        self.assertEqual(intent.constraints.get("min_rating"), 4.0)

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_maps"])

    # --------------------------------------------------------------------------
    # Scenario 4: Google Shopping Integration
    # --------------------------------------------------------------------------
    def test_scenario_4_question_1_electronics_and_price_cap(self):
        """Test Question 1: 'Relay, compare RTX 4060 laptop prices under 80000.' triggers shopping + google."""
        utterance = "Relay, compare RTX 4060 laptop prices under 80000."
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "shopping")
        self.assertEqual(intent.constraints.get("max_price"), 80000.0)

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_shopping", "google"])  # Parallel review check

        _intent, decision, _telemetry = self.broker.process(utterance)
        self.assertGreater(decision.confidence, 0.9)
        self.assertIn("Flipkart", decision.answer)
        self.assertIn("₹76,990", decision.answer)

    def test_scenario_4_question_2_smartphone_deals(self):
        """Test Question 2: 'Relay, what are the cheapest deals on iPhone 15 online right now?'"""
        utterance = "Relay, what are the cheapest deals on iPhone 15 online right now?"
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "shopping")
        self.assertEqual(intent.constraints.get("prefer"), "cheapest")

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_shopping"])

    # --------------------------------------------------------------------------
    # Scenario 5: Google News Integration
    # --------------------------------------------------------------------------
    def test_scenario_5_question_1_regional_news(self):
        """Test Question 1: 'Relay, what is the latest news today regarding Indian space missions?'"""
        utterance = "Relay, what is the latest news today regarding Indian space missions?"
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "news")

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_news"])

        _intent, decision, _telemetry = self.broker.process(utterance)
        self.assertGreater(decision.confidence, 0.9)
        self.assertIn("The Hindu", decision.answer)
        self.assertIn("PTI", decision.answer)

    def test_scenario_5_question_2_financial_headlines(self):
        """Test Question 2: 'Relay, what are the top news headlines about the stock market today?'"""
        utterance = "Relay, what are the top news headlines about the stock market today?"
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "news")

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_news"])

    # --------------------------------------------------------------------------
    # Scenario 6: General Google Web Search & Research
    # --------------------------------------------------------------------------
    def test_scenario_6_question_1_live_fact_release(self):
        """Test Question 1: 'Relay, what is the current latest version of Python released this year?'"""
        utterance = "Relay, what is the current latest version of Python released this year?"
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "research")

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google"])

        _intent, decision, _telemetry = self.broker.process(utterance)
        self.assertGreater(decision.confidence, 0.85)
        self.assertIn("Python 3.13", decision.answer)

    def test_scenario_6_question_2_product_comparison(self):
        """Test Question 2: 'Relay, compare MacBook Air M3 versus Dell XPS 13 for battery life.'"""
        utterance = "Relay, compare MacBook Air M3 versus Dell XPS 13 for battery life."
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "research")

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google"])

        _intent, decision, _telemetry = self.broker.process(utterance)
        self.assertGreater(decision.confidence, 0.85)
        self.assertIn("MacBook Air M3", decision.answer)

    # --------------------------------------------------------------------------
    # Scenario 7: Multi-Engine Composite Query (The Flagship Hackathon Query)
    # --------------------------------------------------------------------------
    def test_scenario_7_flagship_composite_query(self):
        """Flagship: Chennai to Bangalore tomorrow, nonstop flight after 5 PM, hotel under 4000 near Indiranagar, dinner open tonight, total under 10000."""
        utterance = (
            "Relay, I'm going to Bangalore tomorrow. Find the cheapest nonstop flight from Chennai "
            "after 5 PM, a hotel under 4000 near Indiranagar rated above 4 stars, and a dinner place open tonight. "
            "Keep everything under 10000."
        )
        intent = self.router.classify(utterance)

        self.assertTrue(intent.requires_live_data)
        self.assertEqual(intent.category, "travel")
        self.assertEqual(intent.entities.get("origin"), "Chennai")
        self.assertEqual(intent.entities.get("destination"), "Bangalore")
        self.assertEqual(intent.entities.get("location_area"), "Indiranagar")
        self.assertTrue(intent.constraints.get("nonstop"))
        self.assertEqual(intent.constraints.get("departure_after"), "5:00 PM")
        self.assertEqual(intent.constraints.get("max_hotel_price"), 4000.0)
        self.assertEqual(intent.constraints.get("min_rating"), 4.0)
        self.assertEqual(intent.constraints.get("max_total_budget"), 10000.0)

        plan = self.planner.create_search_plan(intent)
        engines = [s.engine for s in plan.searches]
        self.assertEqual(engines, ["google_flights", "google_hotels", "google_maps"])

        _intent, decision, telemetry = self.broker.process(utterance)
        self.assertGreater(decision.confidence, 0.9)
        self.assertEqual(telemetry.total_searches, 3)

        # Total cost is 3142 (flight) + 3720 (hotel) = 6862 <= 10000
        self.assertIn("₹6,862", decision.answer)
        self.assertIn("under budget", decision.answer)
        self.assertEqual(len(decision.evidence_ids), 3)

    # --------------------------------------------------------------------------
    # Scenario 8: Architectural Fail-Closed Verification
    # --------------------------------------------------------------------------
    def test_scenario_8_fail_closed_and_local_autonomy(self):
        """Test Question: 'Relay, what is the price of gold in India today?' while disconnected, followed by local battery."""
        session = Session(speak=lambda t: None, db_path=":memory:")
        session.live_world = self.broker

        # Disconnect Live World
        SerpApiClient.set_disconnected(True)
        self.mock_client.set_available(False)

        # 1. Grounded refusal when live retrieval is blocked
        result = session.handle("Relay, what is the price of gold in India today?")
        expected_refusal = (
            "I understood the request, but live-world access is unavailable, so I can't verify current results."
        )
        self.assertEqual(result, [expected_refusal])

        # 2. Immediate local follow-up proving desktop autonomy is unaffected
        with patch("psutil.sensors_battery") as mock_bat:
            class FakeBattery:
                percent = 84
                power_plugged = True
                secsleft = -1
            mock_bat.return_value = FakeBattery()

            battery_reply = session.handle("Relay, how is my laptop battery?")
            self.assertTrue(len(battery_reply) > 0)
            self.assertIn("84 percent", battery_reply[0])


if __name__ == "__main__":
    unittest.main()
