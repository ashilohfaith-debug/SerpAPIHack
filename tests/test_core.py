"""P2: ids, event bus, state machines, cancellation, emergency stop, workers."""

import threading
import time

import pytest


# ---- ids ----
def test_ids_unique_and_prefixed():
    from relay.core.ids import new_action_id, new_session_id, new_task_id
    assert new_session_id().startswith("ses_")
    assert new_task_id().startswith("task_")
    assert new_action_id().startswith("act_")
    assert len({new_task_id() for _ in range(1000)}) == 1000


# ---- bus ----
def test_bus_pubsub_and_wildcard():
    from relay.core.bus import Event, EventBus
    bus = EventBus()
    seen, allseen = [], []
    bus.subscribe("task.state", lambda e: seen.append(e.data.get("to")))
    bus.subscribe("*", lambda e: allseen.append(e.type))
    bus.publish(Event("task.state", {"to": "acting"}))
    bus.emit("voice.state", to="speaking")
    assert seen == ["acting"]
    assert allseen == ["task.state", "voice.state"]


def test_bus_unsubscribe_and_handler_error_isolation():
    from relay.core.bus import Event, EventBus
    bus = EventBus()
    hits = []
    unsub = bus.subscribe("x", lambda e: hits.append(1))
    bus.subscribe("x", lambda e: (_ for _ in ()).throw(RuntimeError("bad")))  # raises
    errs = bus.publish(Event("x"))
    assert hits == [1] and len(errs) == 1  # good handler still ran
    unsub()
    bus.publish(Event("x"))
    assert hits == [1]  # not called again


# ---- state machines ----
def test_task_state_valid_and_invalid():
    from relay.core.bus import EventBus
    from relay.core.state import TaskState, task_machine
    bus = EventBus()
    got = []
    bus.subscribe("task.state", lambda e: got.append((e.data["from"], e.data["to"])))
    m = task_machine("t1", bus)
    m.transition(TaskState.PLANNING)
    m.transition(TaskState.ACTING)
    m.transition(TaskState.VERIFYING)
    m.transition(TaskState.COMPLETED)
    assert m.is_terminal
    assert got[0] == ("pending", "planning")
    from relay.core.state import InvalidTransition
    with pytest.raises(InvalidTransition):
        m.transition(TaskState.ACTING)  # terminal -> nothing


def test_voice_error_reachable_from_any_state():
    from relay.core.state import VoiceState, voice_machine
    m = voice_machine("v1")
    m.transition(VoiceState.LISTENING)
    m.transition(VoiceState.ERROR)   # allowed from any
    m.transition(VoiceState.IDLE)
    assert m.state == VoiceState.IDLE


def test_voice_and_task_are_independent():
    from relay.core.state import TaskState, VoiceState, task_machine, voice_machine
    v = voice_machine("v")
    t = task_machine("t")
    t.transition(TaskState.PLANNING)
    t.transition(TaskState.ACTING)
    t.transition(TaskState.VERIFYING)
    v.transition(VoiceState.SPEAKING)   # narrating WHILE verifying
    assert v.state == VoiceState.SPEAKING and t.state == TaskState.VERIFYING


# ---- cancellation ----
def test_cancellation_token():
    from relay.core.cancellation import CancellationToken, Cancelled
    tok = CancellationToken()
    fired = []
    tok.on_cancel(lambda: fired.append(1))
    assert not tok.cancelled
    tok.cancel()
    assert tok.cancelled and fired == [1]
    with pytest.raises(Cancelled):
        tok.raise_if_cancelled()
    tok.on_cancel(lambda: fired.append(2))  # already cancelled -> immediate
    assert fired == [1, 2]


# ---- emergency stop (must work while a worker is blocked) ----
def test_emergency_stop_independent_of_blocked_worker():
    from relay.core.emergency import EmergencyStop
    es = EmergencyStop()
    flushed = []
    es.register_flush(lambda: flushed.append("input_queue"))

    worker_running = threading.Event()

    def blocked_worker():
        worker_running.set()
        time.sleep(5.0)  # simulate a hung UIA/inference worker

    th = threading.Thread(target=blocked_worker, daemon=True)
    th.start()
    worker_running.wait(1.0)

    t0 = time.perf_counter()
    es.engage("user")          # must not wait on the blocked worker
    dt = time.perf_counter() - t0
    assert es.is_engaged and flushed == ["input_queue"]
    assert dt < 0.2            # responsive despite the 5s-blocked worker


# ---- worker bounded call ----
def test_run_bounded_times_out_without_hanging_caller():
    from relay.core.workers import run_bounded
    t0 = time.perf_counter()
    r = run_bounded(lambda: time.sleep(5), timeout=0.2, name="hang")
    dt = time.perf_counter() - t0
    assert r.timed_out and not r.ok
    assert dt < 1.0  # returned promptly, did not wait 5s


def test_run_bounded_success_and_error():
    from relay.core.workers import run_bounded
    assert run_bounded(lambda: 21 * 2, timeout=1).value == 42

    def boom():
        raise ValueError("nope")
    r = run_bounded(boom, timeout=1)
    assert not r.ok and isinstance(r.error, ValueError)
