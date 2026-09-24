"""P4 perception: semantic model, and the UIA worker's timeout/restart, change
events and stale detection (headless via an injected observe fn). A real UIA
observation is exercised as an integration test."""

import time

import pytest

from relay.perception.semantic import Dialog, ScreenSnapshot, UIElement


def _el(uid, name, role="Button", bbox=(0, 0, 10, 10), **kw):
    return UIElement(uid=uid, name=name, role=role, bbox=bbox, **kw)


# ---- semantic model ----
def test_element_center_and_dict():
    e = _el(1, "Save", bbox=(10, 20, 30, 40), actions=("invoke",))
    assert e.center == (20, 30)
    assert e.to_dict()["actions"] == ["invoke"]


def test_snapshot_fingerprint_stable_and_sensitive():
    a = ScreenSnapshot(1, foreground_title="Notepad", elements=[_el(1, "OK")])
    b = ScreenSnapshot(2, foreground_title="Notepad", elements=[_el(1, "OK")])  # diff version only
    c = ScreenSnapshot(3, foreground_title="Notepad", elements=[_el(1, "Cancel")])
    assert a.fingerprint() == b.fingerprint()   # version doesn't affect fingerprint
    assert a.fingerprint() != c.fingerprint()   # element change does


def test_snapshot_find_prefers_exact_then_smallest():
    els = [_el(1, "Save As", bbox=(0, 0, 100, 100)), _el(2, "Save", bbox=(0, 0, 10, 10)),
           _el(3, "Save", bbox=(0, 0, 5, 5))]
    snap = ScreenSnapshot(1, elements=els)
    assert [e.uid for e in snap.find("Save")] == [2, 3]      # exact matches only
    assert snap.find("save as")[0].uid == 1
    subs = snap.find("sav")                                   # substring -> smallest first
    assert subs[0].uid == 3


def test_snapshot_summary_and_unavailable():
    s = ScreenSnapshot(1, foreground_app="notepad.exe", foreground_title="Untitled",
                       elements=[_el(1, "OK")], dialogs=[Dialog("Save", ("Save", "Cancel"))])
    assert "notepad.exe" in s.summary() and "dialog" in s.summary()
    blind = ScreenSnapshot(1, foreground_app="game.exe", uia_available=False)
    assert "can't read" in blind.summary()


# ---- worker (headless, injected observe) ----
def test_worker_observe_updates_live_and_version():
    from relay.perception.worker import UIAWorker
    seq = []

    def fake(v):
        seq.append(v)
        return ScreenSnapshot(v, foreground_app="A", foreground_title="A")

    w = UIAWorker(observe_fn=fake)
    s1 = w.observe(timeout=1)
    s2 = w.observe(timeout=1)
    assert s1.observation_version == 1 and s2.observation_version == 2
    assert w.live is s2
    assert w.is_stale(s1) and not w.is_stale(s2)


def test_worker_publishes_change_only_on_difference():
    from relay.core import EventBus
    from relay.perception.worker import UIAWorker
    bus = EventBus()
    events = []
    bus.subscribe("perception.change", lambda e: events.append(e.data["foreground_title"]))
    titles = ["Notepad", "Notepad", "Explorer"]

    def fake(v):
        return ScreenSnapshot(v, foreground_app="x", foreground_title=titles[v - 1])

    w = UIAWorker(bus=bus, observe_fn=fake)
    for _ in range(3):
        w.observe(timeout=1)
    assert events == ["Notepad", "Explorer"]  # unchanged middle observe -> no event


def test_worker_times_out_and_restarts_without_hanging():
    from relay.perception.worker import UIAWorker
    calls = {"n": 0}

    def fake(v):
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(3.0)  # simulate a hung provider on the first call
        return ScreenSnapshot(v, foreground_app="Recovered", foreground_title="Recovered")

    w = UIAWorker(observe_fn=fake)
    t0 = time.perf_counter()
    assert w.observe(timeout=0.2) is None          # caller stays responsive
    assert time.perf_counter() - t0 < 1.0
    snap = w.observe(timeout=2.0)                   # fresh worker serves the next call
    assert snap is not None and snap.foreground_app == "Recovered"


# ---- real UIA (integration) ----
@pytest.mark.integration
def test_real_uia_observe_returns_snapshot():
    from relay.perception import UIAWorker
    w = UIAWorker()
    snap = w.observe(timeout=5.0)
    assert snap is not None
    # On a live desktop there is a foreground window with a title or some controls.
    assert snap.foreground_title or snap.elements or snap.foreground_app
    w.stop()
