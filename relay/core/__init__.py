"""Core runtime: ids, event bus, state machines, cancellation, emergency stop,
and worker supervision. Pure stdlib — the Essential core has no heavy deps."""

from .bus import Event, EventBus
from .cancellation import CancellationToken, Cancelled
from .emergency import EmergencyStop
from .ids import new_action_id, new_session_id, new_task_id
from .state import (
    RELAY_TRANSITIONS,
    TASK_TRANSITIONS,
    VOICE_TRANSITIONS,
    RelayState,
    StateMachine,
    TaskState,
    VoiceState,
    relay_state_machine,
    task_machine,
    voice_machine,
)

__all__ = [
    "RELAY_TRANSITIONS",
    "RelayState",
    "TASK_TRANSITIONS",
    "VOICE_TRANSITIONS",
    "CancellationToken",
    "Cancelled",
    "EmergencyStop",
    "Event",
    "EventBus",
    "StateMachine",
    "TaskState",
    "VoiceState",
    "new_action_id",
    "new_session_id",
    "new_task_id",
    "relay_state_machine",
    "task_machine",
    "voice_machine",
]
