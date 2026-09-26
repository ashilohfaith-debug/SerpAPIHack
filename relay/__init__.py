"""RELAY — local-first, voice-first Windows accessibility assistant.

Subsystems (built phase by phase; see ../docs/04-phase-plan.md):
  core/          lifecycle, event bus, state machines, ids, cancellation,
                 emergency stop, worker supervision          [P2]
  safety/        risk classification + permission engine      [P2]
  memory/        action journal, checkpoints, five-layer memory [P2 minimal, P7 full]
  diagnostics/   logging, performance/resource measurement    [P1/P11]
  audio/         wake/VAD/STT + Piper TTS + barge-in           [P3]
  perception/    UI Automation worker + semantic screen model  [P4]
  executor/      central executor + action ladder              [P5]
  verifier/      post-action verification                      [P5]
  recovery/      dialogs, stale refs, crash reconciliation     [P5/P7]
  intent/        deterministic grammar + reference resolution  [P6]
  planner/       goal decomposition + step sequencing          [P6]
  accessibility/ narration modes + spoken onboarding + NVDA    [P8]
  ipc/           authenticated local channel for optional UI   [P10]
"""

import os as _os

# Basic laptops: the speech model's OpenMP threads (Intel runtime, loaded by
# ctranslate2) busy-wait between work by default, burning CPU and battery for nothing.
# Make them sleep instead. Set before any model library is imported; a user's own
# environment setting still wins.
_os.environ.setdefault("KMP_BLOCKTIME", "0")
_os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")

__version__ = "0.3.3"


def inference_threads() -> int:
    """Threads for model inference: the CPUs this process may actually use, at most 4
    and never more than the physical cores (more threads than cores only contend)."""
    try:
        import psutil
        usable = len(psutil.Process().cpu_affinity())
        physical = psutil.cpu_count(logical=False) or usable
    except Exception:
        usable = physical = _os.cpu_count() or 2
    return max(1, min(4, usable, physical))
