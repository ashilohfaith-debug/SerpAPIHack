"""The two coordinated state machines: voice and task.

They are INDEPENDENT and run concurrently — RELAY can narrate (voice=speaking)
while a task verifies (task=verifying). Forcing them into one mutually-exclusive
state would break barge-in and progress narration.

Transitions are validated against an explicit allow-map; an illegal transition
raises rather than silently corrupting state. Every machine has an id and emits
``<name>.state`` events on the bus so the journal and UI can follow along.
"""

from __future__ import annotations

from enum import Enum

from .bus import EventBus


class VoiceState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"


class TaskState(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    ACTING = "acting"
    VERIFYING = "verifying"
    PAUSED = "paused"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Allowed transitions. ERROR is reachable from any voice state (added below).
VOICE_TRANSITIONS: dict[VoiceState, set[VoiceState]] = {
    VoiceState.IDLE: {VoiceState.LISTENING, VoiceState.SPEAKING},
    VoiceState.LISTENING: {VoiceState.TRANSCRIBING, VoiceState.IDLE, VoiceState.INTERRUPTED},
    VoiceState.TRANSCRIBING: {VoiceState.SPEAKING, VoiceState.IDLE, VoiceState.LISTENING},
    VoiceState.SPEAKING: {VoiceState.IDLE, VoiceState.INTERRUPTED, VoiceState.LISTENING},
    VoiceState.INTERRUPTED: {VoiceState.IDLE, VoiceState.LISTENING, VoiceState.SPEAKING},
    VoiceState.ERROR: {VoiceState.IDLE},
}

TERMINAL_TASK = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
TASK_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {TaskState.PLANNING, TaskState.CANCELLED},
    TaskState.PLANNING: {
        TaskState.WAITING_FOR_CONFIRMATION,
        TaskState.ACTING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.WAITING_FOR_CONFIRMATION: {
        TaskState.ACTING,
        TaskState.PAUSED,
        TaskState.CANCELLED,
        TaskState.FAILED,
    },
    TaskState.ACTING: {
        TaskState.VERIFYING,
        TaskState.PAUSED,
        TaskState.RECOVERING,
        TaskState.CANCELLED,
        TaskState.FAILED,
    },
    TaskState.VERIFYING: {
        TaskState.ACTING,
        TaskState.COMPLETED,
        TaskState.RECOVERING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.PAUSED: {TaskState.ACTING, TaskState.PLANNING, TaskState.CANCELLED},
    TaskState.RECOVERING: {
        TaskState.ACTING,
        TaskState.VERIFYING,
        TaskState.PLANNING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}


class InvalidTransition(Exception):
    pass


class StateMachine:
    """A validated state machine. ``allow_error`` lets any state jump to an ERROR
    member (voice machine) — passed explicitly to keep the class generic."""

    def __init__(
        self,
        name: str,
        machine_id: str,
        initial,
        transitions: dict,
        bus: EventBus | None = None,
        error_state=None,
    ) -> None:
        self.name = name
        self.id = machine_id
        self.state = initial
        self._transitions = transitions
        self._bus = bus
        self._error_state = error_state

    def can(self, to) -> bool:
        if self._error_state is not None and to == self._error_state:
            return True
        return to in self._transitions.get(self.state, set())

    def transition(self, to, reason: str = "") -> None:
        if not self.can(to):
            raise InvalidTransition(
                f"{self.name}[{self.id}]: {self.state.value} -> {to.value} not allowed"
            )
        frm, self.state = self.state, to
        if self._bus is not None:
            self._bus.emit(
                f"{self.name}.state",
                id=self.id,
                **{"from": frm.value},
                to=to.value,
                reason=reason,
            )

    @property
    def is_terminal(self) -> bool:
        return not self._transitions.get(self.state, set()) and (
            self._error_state is None or self.state != self._error_state
        )


def voice_machine(machine_id: str, bus: EventBus | None = None) -> StateMachine:
    return StateMachine(
        "voice", machine_id, VoiceState.IDLE, VOICE_TRANSITIONS, bus, error_state=VoiceState.ERROR
    )


def task_machine(machine_id: str, bus: EventBus | None = None) -> StateMachine:
    return StateMachine("task", machine_id, TaskState.PENDING, TASK_TRANSITIONS, bus)


class RelayState(str, Enum):
    """The complete 17-state dialogue, voice and execution state machine."""

    BOOTING = "booting"
    GREETING = "greeting"
    LOADING = "loading"
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    CLARIFYING = "clarifying"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    ACTING = "acting"
    VERIFYING = "verifying"
    REPORTING = "reporting"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    EMERGENCY_STOPPED = "emergency_stopped"
    FAILED = "failed"
    RECOVERING = "recovering"


RELAY_TRANSITIONS: dict[RelayState, set[RelayState]] = {
    RelayState.BOOTING: {RelayState.GREETING, RelayState.LOADING, RelayState.FAILED},
    RelayState.GREETING: {RelayState.LOADING, RelayState.IDLE, RelayState.LISTENING},
    RelayState.LOADING: {RelayState.IDLE, RelayState.LISTENING, RelayState.FAILED},
    RelayState.IDLE: {
        RelayState.LISTENING,
        RelayState.PLANNING,
        RelayState.PAUSED,
        RelayState.EMERGENCY_STOPPED,
    },
    RelayState.LISTENING: {
        RelayState.TRANSCRIBING,
        RelayState.IDLE,
        RelayState.CANCELLED,
        RelayState.EMERGENCY_STOPPED,
    },
    RelayState.TRANSCRIBING: {
        RelayState.PLANNING,
        RelayState.CLARIFYING,
        RelayState.IDLE,
        RelayState.FAILED,
        RelayState.EMERGENCY_STOPPED,
    },
    RelayState.CLARIFYING: {
        RelayState.LISTENING,
        RelayState.PLANNING,
        RelayState.CANCELLED,
        RelayState.EMERGENCY_STOPPED,
    },
    RelayState.PLANNING: {
        RelayState.AWAITING_CONFIRMATION,
        RelayState.ACTING,
        RelayState.CLARIFYING,
        RelayState.CANCELLED,
        RelayState.FAILED,
        RelayState.EMERGENCY_STOPPED,
    },
    RelayState.AWAITING_CONFIRMATION: {
        RelayState.LISTENING,
        RelayState.ACTING,
        RelayState.CANCELLED,
        RelayState.EMERGENCY_STOPPED,
    },
    RelayState.ACTING: {
        RelayState.VERIFYING,
        RelayState.RECOVERING,
        RelayState.PAUSED,
        RelayState.CANCELLED,
        RelayState.FAILED,
        RelayState.EMERGENCY_STOPPED,
    },
    RelayState.VERIFYING: {
        RelayState.REPORTING,
        RelayState.ACTING,
        RelayState.RECOVERING,
        RelayState.FAILED,
        RelayState.CANCELLED,
        RelayState.EMERGENCY_STOPPED,
    },
    RelayState.REPORTING: {
        RelayState.IDLE,
        RelayState.LISTENING,
        RelayState.PAUSED,
        RelayState.EMERGENCY_STOPPED,
    },
    RelayState.PAUSED: {
        RelayState.IDLE,
        RelayState.PLANNING,
        RelayState.ACTING,
        RelayState.CANCELLED,
        RelayState.EMERGENCY_STOPPED,
    },
    RelayState.CANCELLED: {RelayState.IDLE, RelayState.LISTENING},
    RelayState.EMERGENCY_STOPPED: {RelayState.IDLE, RelayState.RECOVERING},
    RelayState.FAILED: {RelayState.RECOVERING, RelayState.IDLE, RelayState.LISTENING},
    RelayState.RECOVERING: {
        RelayState.IDLE,
        RelayState.PLANNING,
        RelayState.ACTING,
        RelayState.FAILED,
        RelayState.CANCELLED,
        RelayState.EMERGENCY_STOPPED,
    },
}


def relay_state_machine(machine_id: str = "relay", bus: EventBus | None = None) -> StateMachine:
    return StateMachine(
        "relay",
        machine_id,
        RelayState.BOOTING,
        RELAY_TRANSITIONS,
        bus,
        error_state=RelayState.FAILED,
    )
