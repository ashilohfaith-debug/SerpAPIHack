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

__version__ = "0.0.1"
