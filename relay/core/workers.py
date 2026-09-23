"""Bounded worker calls with timeouts and a watchdog.

Blocking subsystems — Windows UI Automation and model inference above all — must
never freeze the core, speech or cancellation. Every call into such a worker runs
through ``run_bounded``: it executes on a worker thread and the caller waits at
most ``timeout`` seconds. If the worker overruns, the call returns a timeout
result and the hung thread is abandoned (daemon) rather than awaited forever.

This is intentionally simple: real isolation of UIA (a dedicated COM MTA thread)
and inference (a subprocess) is added in P4/P3; this module gives the core a
uniform, testable "never block longer than T" primitive now.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class WorkerResult:
    ok: bool
    value: Any = None
    error: BaseException | None = None
    timed_out: bool = False


def run_bounded(fn: Callable[[], Any], timeout: float, name: str = "worker") -> WorkerResult:
    """Run ``fn`` on a daemon thread; wait at most ``timeout`` seconds.

    Returns a WorkerResult. On timeout the worker thread is left running (daemon,
    so it dies with the process) and ``timed_out=True`` is returned — the caller
    stays responsive. ``fn`` should itself honour a CancellationToken so an
    abandoned call can wind down.
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - report any failure to caller
            box["error"] = e
        finally:
            done.set()

    t = threading.Thread(target=_target, name=name, daemon=True)
    t.start()
    if not done.wait(timeout):
        return WorkerResult(ok=False, timed_out=True)
    if "error" in box:
        return WorkerResult(ok=False, error=box["error"])
    return WorkerResult(ok=True, value=box.get("value"))
