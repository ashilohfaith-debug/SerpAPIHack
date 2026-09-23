"""In-process event bus (thread-safe pub/sub).

The bus is the local spine: workers publish state transitions, perception changes,
verification results and errors; subscribers (narration, journal, the optional IPC
bridge) react. It is deliberately small and synchronous — a handler that must do
slow work should hand off to its own worker, never block the bus.

Design notes:
  * Subscribers register by event type, or "*" for all events.
  * Publishing dispatches to a snapshot of handlers taken under the lock, then
    calls them OUTSIDE the lock, so a handler may (un)subscribe without deadlock.
  * A raising handler never breaks delivery to the others; the error is captured.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

Handler = Callable[["Event"], None]
WILDCARD = "*"


@dataclass(frozen=True)
class Event:
    """One thing that happened. ``data`` is a plain dict (JSON-serialisable for
    the IPC bridge). ``type`` is a dotted name, e.g. ``task.state`` or
    ``perception.change``."""

    type: str
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = {}
        self._lock = threading.RLock()

    def subscribe(self, event_type: str, handler: Handler) -> Callable[[], None]:
        """Register ``handler`` for ``event_type`` (or ``"*"``). Returns an
        unsubscribe callable."""
        with self._lock:
            self._subs.setdefault(event_type, []).append(handler)

        def _unsub() -> None:
            with self._lock:
                lst = self._subs.get(event_type)
                if lst and handler in lst:
                    lst.remove(handler)

        return _unsub

    def publish(self, event: Event) -> list[Exception]:
        """Deliver ``event`` to matching handlers. Returns any exceptions raised
        by handlers (delivery to others is never interrupted)."""
        with self._lock:
            handlers = list(self._subs.get(event.type, ())) + list(self._subs.get(WILDCARD, ()))
        errors: list[Exception] = []
        for h in handlers:
            try:
                h(event)
            except Exception as e:  # a bad subscriber must not break the bus
                errors.append(e)
        return errors

    def emit(self, event_type: str, **data) -> list[Exception]:
        """Convenience: build and publish an Event from kwargs."""
        return self.publish(Event(type=event_type, data=dict(data)))
