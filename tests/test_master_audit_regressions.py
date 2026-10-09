"""Voice-session, provider-data and delta regressions found in the master audit."""

from __future__ import annotations

import threading
from datetime import date, timedelta

import pytest

from relay.core import EventBus
from relay.liveworld.broker import LiveWorldBroker
from relay.liveworld.evidence import EvidenceStore
from relay.liveworld.normalizers import normalize_serp_response
from relay.liveworld.planner import SearchPlanner
from relay.liveworld.ranking import GroundedDecisionEngine
from relay.liveworld.router import LiveWorldRouter
from relay.liveworld.speculative import SpeculativeSearchManager
from relay.liveworld.types import EvidenceItem, RelayIntent
from relay.narration.delta import diff
from relay.perception.semantic import ScreenSnapshot, UIElement
from relay.session import Session


class TravelProvider:
    def __init__(self, fail_hotels=False):
        self.calls = []
        self.fail_hotels = fail_hotels

    def is_available(self):
        return True

    def search(self, engine, params):
        self.calls.append((engine, params))
        if engine == "google_hotels":
            if self.fail_hotels:
                raise RuntimeError("Hotel provider unavailable")
            return {
                "properties": [
                    {
                        "name": "Indiranagar Hotel",
                        "overall_rating": 4.5,
                        "rate_per_night": {"extracted_lowest": 3000},
                        "link": "https://hotel.example/room",
                    }
                ]
            }
        day = params["outbound_date"]
        return {
            "search_metadata": {"google_flights_url": "https://flights.example/result"},
            "best_flights": [
                {
                    "price": 4000,
                    "flights": [
                        {
                            "airline": "Example Air",
                            "flight_number": "EA10",
                            "departure_airport": {"name": "Chennai", "time": f"{day} 18:00"},
                            "arrival_airport": {"name": "Bangalore", "time": f"{day} 19:30"},
                        }
                    ],
                }
            ],
        }


@pytest.fixture
def session():
    instance = Session(speak=lambda text: None, db_path=":memory:")
    instance.live_world = LiveWorldBroker(api_client=TravelProvider())
    yield instance
    instance.close()


def test_session_clarifies_then_searches_and_opens_requested_hotel(session, monkeypatch):
    assert "departure city" in session.handle("Find a flight to Bangalore tomorrow")[0]
    assert "Flight:" in session.handle("Chennai")[0]
    result = session.handle(
        "Find a nonstop flight from Chennai to Bangalore tomorrow after 5 PM "
        "and a hotel under 4000 near Indiranagar. Keep everything under 10000"
    )
    assert "7,000" in result[0]
    opened = []
    monkeypatch.setattr(
        "relay.system.web.open_booking_request", lambda url, data="": opened.append(url)
    )
    assert session.handle("open the hotel") == ["Opened https://hotel.example/room"]
    assert opened == ["https://hotel.example/room"]
    assert session.handle("open the flight") == ["Opened https://flights.example/result"]


def test_open_failure_never_returns_success(session, monkeypatch):
    session.handle("Find a flight from Chennai to Bangalore tomorrow")

    def fail(*args):
        raise OSError("Browser unavailable")

    monkeypatch.setattr("relay.system.web.open_booking_request", fail)
    assert session.handle("open selected result") == []
    assert session._last_live_action_success is False


def test_emergency_stop_preempts_capture_and_blocks_live_actions(session, monkeypatch):
    session.handle("Find a flight from Chennai to Bangalore tomorrow")
    captured = []
    session.capture_next(captured.append)
    session.handle("emergency stop")
    assert session.emergency.is_engaged
    assert captured == []
    opened = []
    monkeypatch.setattr("relay.system.web.open_booking_request", lambda *args: opened.append(args))
    before = len(session.live_world.client.calls)
    assert session.handle("open the flight") == []
    assert session.handle("Find a flight from Delhi to Mumbai tomorrow") == []
    assert opened == [] and len(session.live_world.client.calls) == before
    session.handle("continue")
    assert not session.emergency.is_engaged


def test_new_booking_route_does_not_open_previous_flight(session, monkeypatch):
    session.handle("Find a flight from Chennai to Bangalore tomorrow")
    opened = []
    monkeypatch.setattr("relay.system.web.open_booking_request", lambda *args: opened.append(args))
    session.handle("book the flight from Delhi to Mumbai tomorrow")
    assert opened == []
    assert session.live_world.client.calls[-1][1]["departure_id"] == "DEL"


@pytest.mark.parametrize("command", ["stop", "cancel"])
def test_stop_and_cancel_preempt_captured_replies(session, command):
    captured = []
    session.capture_next(captured.append)
    session.handle(command)
    assert captured == []
    assert session.cancel.is_set()
    assert session._capture is None


def test_emergency_during_booking_lookup_prevents_handoff(session, monkeypatch):
    from relay.liveworld.types import RelayDecision

    def delayed_result(**kwargs):
        session.emergency_stop()
        return RelayDecision(
            answer="Verified provider",
            confidence=1.0,
            evidence_ids=[],
            action={"target": "https://provider.example"},
        )

    monkeypatch.setattr(session.live_world, "prepare_flight_booking", delayed_result)
    opened = []
    monkeypatch.setattr("relay.system.web.open_booking_request", lambda *args: opened.append(args))
    assert session.handle("book the flight") == []
    assert session.emergency.is_engaged and opened == []


@pytest.mark.parametrize("reply", ["today", "tomorrow", "on monday", "2026-10-20"])
def test_pending_date_reply_is_travel(reply):
    broker = LiveWorldBroker(api_client=TravelProvider())
    _, decision, _ = broker.process("Find a flight from Chennai to Bangalore")
    assert "travel date" in decision.answer
    intent = broker.classify(reply)
    assert intent.category == "travel"
    assert intent.entities["origin"] == "Chennai"
    assert SearchPlanner().missing_travel_details(intent) == []


def test_pending_unknown_origin_is_replaced_by_airport_code():
    broker = LiveWorldBroker(api_client=TravelProvider())
    broker.process("Find a flight from Atlantis to Bangalore tomorrow")
    intent, decision, _ = broker.process("MAA")
    assert intent.entities["origin"] == "Maa"
    assert decision.confidence > 0.9
    assert broker.client.calls[0][1]["departure_id"] == "MAA"


def test_shorthand_route_reaches_grounded_flight_decision():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    broker = LiveWorldBroker(api_client=TravelProvider())
    _, decision, telemetry = broker.process(f"New York to Los Angeles on {tomorrow}")
    assert telemetry.total_searches == 1
    assert "Flight:" in decision.answer
    assert decision.confidence > 0.9
    assert "stay" not in decision.recommendation


def test_partial_engine_failure_keeps_verified_flight():
    broker = LiveWorldBroker(api_client=TravelProvider(fail_hotels=True))
    _, decision, _ = broker.process(
        "Find a flight from Chennai to Bangalore tomorrow and a hotel. Keep everything under 10000"
    )
    assert "Flight:" in decision.answer
    assert "could not verify a hotel" in decision.answer
    assert "did not calculate a total" in decision.answer
    assert len(decision.evidence_ids) == 1


def test_provider_iso_departure_filter():
    engine = GroundedDecisionEngine(EvidenceStore())
    assert engine._time_is_at_or_after("2026-10-20 18:30", "5 PM")
    assert not engine._time_is_at_or_after("2026-10-20 08:30", "5 PM")


def test_read_news_requires_live_data_and_local_commands_stay_local():
    router = LiveWorldRouter()
    assert router.classify("Read the latest news about Nvidia").requires_live_data
    assert router.classify("Compare the current status of AI coding agents").requires_live_data
    assert router.classify("Read the page").category == "local_action"
    assert router.classify("Find a cheap restaurant near Indiranagar open now").category == "local"


def test_explicit_new_route_is_not_replaced_by_old_context():
    broker = LiveWorldBroker(api_client=TravelProvider())
    broker.process("Find a flight from Chennai to Bangalore tomorrow")
    intent = broker.classify("Find another flight from Delhi to Mumbai tomorrow")
    assert intent.entities["origin"] == "Delhi"
    assert intent.entities["destination"] == "Mumbai"
    assert broker.classify("open another file").requires_live_data is False


def test_unstored_evidence_cannot_drive_an_action():
    engine = GroundedDecisionEngine(EvidenceStore())
    item = EvidenceItem(
        "missing", "google_shopping", "Unstored product", price=100, url="https://shop.example"
    )
    decision = engine.decide(RelayIntent(True, "shopping", "buy a product"), [item])
    assert decision.confidence == 0
    assert decision.action["type"] == "none"


def test_offline_refusal_clears_previous_panel_decision():
    class Offline:
        def is_available(self):
            return False

    bus, events = EventBus(), []
    bus.subscribe("liveworld.decision", events.append)
    broker = LiveWorldBroker(api_client=Offline())
    broker.process("Find a flight from Chennai to Bangalore tomorrow", bus=bus)
    assert events
    assert events[-1].data["evidence"] == []
    assert events[-1].data["action"]["type"] == "none"


def test_speculative_route_change_discards_old_evidence():
    store = EvidenceStore()
    manager = SpeculativeSearchManager(TravelProvider(), store)
    old = LiveWorldRouter().classify("Find a flight from Chennai to Bangalore tomorrow")
    params = SearchPlanner().create_search_plan(old).searches[0].params
    item = EvidenceItem("old", "google_flights", "Old route", metadata={"search_params": params})
    manager._speculative_items = [item]
    final = LiveWorldRouter().classify("Find a flight from Delhi to Mumbai tomorrow")
    assert manager.consume_speculative(final) is None


def test_speculative_matching_result_is_only_returned_once():
    store = EvidenceStore()
    manager = SpeculativeSearchManager(TravelProvider(), store)
    intent = LiveWorldRouter().classify("Find a flight from Chennai to Bangalore tomorrow")
    params = SearchPlanner().create_search_plan(intent).searches[0].params
    item = EvidenceItem(
        "matching", "google_flights", "Matching route", metadata={"search_params": params}
    )
    manager._speculative_items = [item]
    manager._active_cancel_event = threading.Event()
    assert manager.consume_speculative(intent) == [item]
    assert manager.consume_speculative(intent) is None


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///C:/Windows", "data:text/html,test"]
)
def test_external_evidence_rejects_non_web_links(url):
    items = normalize_serp_response(
        "google", {"organic_results": [{"title": "Source", "link": url}]}
    )
    assert items[0].url == ""


def test_background_delta_reports_status_removal_and_toggle():
    old_status = UIElement(
        1, "Status", "Text", (0, 0, 1, 1), value="Downloading", stable_id="status"
    )
    new_status = UIElement(9, "Status", "Text", (0, 0, 1, 1), value="Complete", stable_id="status")
    old_button = UIElement(2, "Submit", "Button", (0, 0, 1, 1), states={"enabled": False})
    new_button = UIElement(8, "Submit", "Button", (0, 0, 1, 1), states={"enabled": True})
    removed = UIElement(3, "Download progress", "ProgressBar", (0, 0, 1, 1))
    old = ScreenSnapshot(1, "app", "Window", elements=[old_status, old_button, removed])
    new = ScreenSnapshot(2, "app", "Window", elements=[new_status, new_button])
    text = " ".join(diff(old, new))
    assert "Complete" in text
    assert "Submit is now enabled" in text
    assert "No longer on screen: Download progress" in text


def test_background_password_delta_does_not_read_secret():
    old = UIElement(1, "Password", "Edit", (0, 0, 1, 1), value="old", states={"is_password": True})
    new = UIElement(
        2, "Password", "Edit", (0, 0, 1, 1), value="super-secret", states={"is_password": True}
    )
    text = " ".join(
        diff(
            ScreenSnapshot(1, "app", "Window", elements=[old]),
            ScreenSnapshot(2, "app", "Window", elements=[new]),
        )
    )
    assert "Password text updated" in text
    assert "super-secret" not in text


def test_future_opening_is_not_inferred_from_open_now():
    store = EvidenceStore()
    place = EvidenceItem(
        "place", "google_maps", "Restaurant", rating=4.8, metadata={"open_state": "Open"}
    )
    store.store(place.engine, {"q": "restaurant"}, [place])
    engine = GroundedDecisionEngine(store)
    decision = engine.decide(
        RelayIntent(True, "local", "Find a highly rated restaurant open tonight"), [place]
    )
    assert decision.action["type"] == "none"
    assert engine.decide(
        RelayIntent(True, "local", "Find a highly rated restaurant open now"), [place]
    ).evidence_ids == [place.id]
