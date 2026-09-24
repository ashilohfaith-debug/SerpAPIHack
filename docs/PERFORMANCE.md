# RELAY performance — measured results

All numbers are **measured** with `scripts/bench_perf.py`, not estimated. Measured on
the development machine (Windows 11, ~15.3 GB RAM, integrated-class CPU, no GPU). This
is **not** a real 4 GB laptop; the `--limit-mb` Job Object hard cap is the honest
constrained-environment proxy for 4 GB viability.

Reproduce:
```
uv run python scripts/bench_perf.py                  # measure
uv run python scripts/bench_perf.py --limit-mb 1024  # run under a hard 1 GB commit cap
```

## Essential-mode footprint (measured)

| Metric | Measured | Target | Result |
|---|---|---|---|
| Idle / baseline (core imported, **no models loaded**) | **35 MB** | < 200 MB | **PASS** |
| Essential peak — STT + TTS loaded | **~330 MB** | < 1 GB | **PASS** |
| Essential peak — STT + TTS + OCR loaded | **~406 MB** | < 1 GB | **PASS** |
| Process-tree RSS (incl. UIA worker) | ~330 MB | — | — |
| Peak working set | ~412 MB | — | — |
| After unloading models + gc | **~155 MB (freed ~176 MB)** | — | lazy-unload works |
| **Ran fully under a hard 1 GB memory cap** | **yes (peak ~323 MB)** | survive | **PASS** |

## Latency (measured)

| Operation | Time |
|---|---|
| STT (faster-whisper tiny.en int8) — cold load + transcribe | ~3.0 s (one-time load) |
| STT — warm transcribe (~4 s of audio) | ~0.38 s |
| TTS (Piper) — load + synth a sentence | ~0.22 s |
| UIA observe (warm) | ~0.09 s |
| SQLite — 200 preference writes | < 0.01 s |
| OCR (RapidOCR) — load + full-screen | ~9 s first run (on-demand region OCR is far faster) |

## What this shows
- The **idle footprint (35 MB)** and **Essential peak (~330–406 MB)** sit far under the
  200 MB / 1 GB targets, and Essential mode **survives a hard 1 GB commit cap** — strong
  evidence it fits a 4 GB machine (OS + peak + headroom).
- **Lazy load/unload works**: unloading STT/TTS/OCR frees ~176 MB back, so RELAY only
  pays for a model while it's in use.
- No LLM/VLM is loaded in Essential mode (those are opt-in Level-2/3 and are what would
  actually threaten the 4 GB budget).

## Not yet validated (honest)
- These are dev-box numbers; **final certification needs a real 4 GB laptop** (CPU speed
  there will raise STT/OCR latency — the memory picture should hold).
- Long-duration soak (hours) and broad fault-injection beyond the unit tests
  (emergency-stop-under-blocked-worker, worker timeout+restart, no-blind-replay) remain
  for release hardening (P13).
