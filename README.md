# RELAY

Windows-first, offline-first, voice-first accessibility assistant for blind and
visually impaired people. It perceives the screen through Windows UI Automation,
narrates what matters, performs real actions, verifies results, and recovers when
things go wrong — driven entirely by voice.

Loop: **PERCEIVE → UNDERSTAND → PLAN → ACT → VERIFY → NARRATE → RECOVER.**

Essential mode is fully offline: no mandatory LLM/VLM/embeddings/vector-db/cloud.

## Status
Under construction, phase by phase (see `../docs/04-phase-plan.md`). Each phase
lands with tests. Nothing is claimed working unless its tests actually ran.

- P1 foundation — done (this commit): env, config, per-user storage, logging, CLI, tests.
- P2 runtime & safety — done: event bus, voice/task state machines, ids, worker
  supervisor, cancellation, emergency stop, risk/permission engine, action journal.
- P3+ — pending.

## Dev
Requires Python 3.12 (via [uv](https://docs.astral.sh/uv/)).

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
uv run relay --selftest
uv run pytest
```

## Reused code (attribution)
See `NOTICE`. Small components adapted from MIT-licensed screen-use and clacky.
