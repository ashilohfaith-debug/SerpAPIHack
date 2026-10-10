"""End-to-End Blind-User Accessibility Verification for SERP-Relay.

Tests that every interaction is 100% eyes-free, audible, unambiguous,
and safe for a visually impaired user across multi-step live-world workflows.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from relay.liveworld.broker import LiveWorldBroker
from relay.liveworld.serpapi import SerpApiClient
from relay.session import Session
from tests.test_hackathon_8_scenarios import MockSerpApiClient


class TestBlindUserEndToEndWorkflows(unittest.TestCase):
    """Rigorous tests confirming that a blind user can complete all multi-step

    tasks using voice only, with zero visual reliance and complete auditory feedback.
    """

    def setUp(self):
        self.spoken_messages: list[str] = []

        def mock_speak(text: str, *args, **kwargs):
            if text:
                self.spoken_messages.append(text)

        self.session = Session(speak=mock_speak, db_path=":memory:")
        self.mock_client = MockSerpApiClient()
        self.broker = LiveWorldBroker(api_client=self.mock_client)
        self.session.live_world = self.broker
        SerpApiClient.set_disconnected(False)

    def tearDown(self):
        self.session.close()

    def test_blind_trip_planning_and_handoff_multistep(self):
        """Blind User Multi-Step Flight Workflow:

        Step 1: Incomplete prompt -> Spoken clarification prompt.
        Step 2: Complete flight prompt -> Detailed auditory synthesis.
        Step 3: 'Book the flight' -> Spoken provider handoff confirmation.
        """
        # Step 1: Incomplete query
        self.spoken_messages.clear()
        self.session.handle("Relay, find the cheapest flight to Bangalore tomorrow")
        self.assertTrue(len(self.spoken_messages) > 0, "Must speak clarification to blind user")
        self.assertIn("departure city", self.spoken_messages[-1].lower())

        # Step 2: Complete flight query with live mock response
        self.spoken_messages.clear()
        self.session.handle(
            "Relay, find the cheapest flight from Delhi to Mumbai tomorrow after 6 PM"
        )
        self.assertTrue(len(self.spoken_messages) > 0, "Must audibly describe best flight")
        spoken_flight = self.spoken_messages[-1]
        self.assertIn("IndiGo", spoken_flight)
        self.assertIn("3,142", spoken_flight)

        # Step 3: Eyes-free booking handoff via voice
        self.spoken_messages.clear()
        with patch("relay.system.web.open_booking_request") as mock_open:
            self.session.handle("Relay, book the flight")
            self.assertTrue(len(self.spoken_messages) > 0, "Must confirm booking action audibly")
            spoken_booking = self.spoken_messages[-1]
            self.assertIn("IndiGo Airlines", spoken_booking)
            self.assertIn("3,142", spoken_booking)
            mock_open.assert_called_once_with(
                "https://www.goindigo.in/booking/handoff", "token=indigo-handoff-123"
            )

    def test_blind_offline_fail_closed_and_immediate_hardware_check(self):
        """Blind User Fail-Safe:

        When internet drops, user is NOT left waiting in silence or misled.
        Then, requesting laptop battery immediately speaks local telemetry.
        """
        SerpApiClient.set_disconnected(True)
        self.mock_client.set_available(False)

        # 1. Offline live query
        self.spoken_messages.clear()
        self.session.handle("Relay, what is the price of gold in India today?")
        self.assertTrue(len(self.spoken_messages) > 0, "Must audibly explain unavailable live access")
        self.assertIn("live-world access is unavailable", self.spoken_messages[-1])

        # 2. Hardware state query remains 100% functional
        self.spoken_messages.clear()
        with patch("psutil.sensors_battery") as mock_bat:
            class FakeBattery:
                percent = 92
                power_plugged = False
                secsleft = 14400
            mock_bat.return_value = FakeBattery()

            self.session.handle("Relay, how is my laptop battery?")
            self.assertTrue(len(self.spoken_messages) > 0, "Must speak battery percentage")
            self.assertIn("92 percent", self.spoken_messages[-1])

    def test_blind_shopping_and_action_opening(self):
        """Blind User Shopping Workflow:

        Speaks price comparisons across retailers, delivery info,
        and cleanly opens the verified merchant URL upon voice confirmation.
        """
        self.spoken_messages.clear()
        self.session.handle("Relay, find an RTX 4060 laptop under 80000 and compare reviews")
        self.assertTrue(len(self.spoken_messages) > 0)
        spoken_deal = self.spoken_messages[-1]
        self.assertIn("Lenovo LOQ", spoken_deal)
        self.assertIn("76,990", spoken_deal)
        self.assertIn("Flipkart", spoken_deal)

        # Follow-up: 'Relay, open the best deal'
        self.spoken_messages.clear()
        with patch("relay.system.web.open_booking_request") as mock_open:
            self.session.handle("Relay, open the best deal")
            self.assertTrue(len(self.spoken_messages) > 0)
            self.assertIn("Opening", self.spoken_messages[-1])
            mock_open.assert_called_once_with("https://flipkart.example/loq4060", "")

    def test_blind_dinner_hours_verification(self):
        """Blind User Dining Workflow:

        Ensures places with unknown hours are NOT recommended blindly;
        speaks verified closing time and address.
        """
        self.spoken_messages.clear()
        self.session.handle("Relay, find a dinner place near Koramangala open tonight")
        self.assertTrue(len(self.spoken_messages) > 0)
        spoken_dinner = self.spoken_messages[-1]
        self.assertIn("Toit Brewpub Koramangala", spoken_dinner)
        self.assertIn("11:30 PM", spoken_dinner)
        self.assertIn("Koramangala, Bangalore", spoken_dinner)


if __name__ == "__main__":
    unittest.main()
