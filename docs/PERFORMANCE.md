# RELAY performance — measured on basic-laptop conditions

Everything here is **measured**, never estimated. The development machine is fast (AMD
Ryzen 9 270, 8 cores / 16 threads, 15.3 GB), so "it runs fine here" proves nothing for
a basic laptop. Low-end hardware is therefore **emulated** with Windows Job Objects:
the process is pinned to 2 physical cores, its CPU is hard-capped (40% ≈ budget i3 /
Ryzen 3 / older i5; 25% ≈ Celeron / Pentium Silver), and memory is hard-capped at 1 GB.

```
uv run python scripts/bench_basic_laptop.py          # emulated laptops, real models
uv run python scripts/bench_perf.py --limit-mb 1024   # footprint under a 1 GB cap
```

> **Correction (0.2.1).** Earlier builds reported "ran under a hard 1 GB cap". That
> helper passed the process pseudo-handle to Windows as a 32-bit value, so the cap may
> never have been applied. It is fixed (explicit handle types) and now **verified**:
> under a 300 MB cap a 500 MB allocation is refused, and CPU-bound work slows by the
> expected factor. All numbers below were taken with the limits enforced.

## What the user waits for (emulated hardware, real models)
"Wait" = end-of-speech detection (0.6 s) + speech recognition + doing the command +
synthesising the first reply. RTF < 1 means speech is generated faster than it plays.

| Profile | Start-up | Recognition | Reply speech | **Wait** | TTS RTF | Idle CPU* | Peak memory |
|---|---|---|---|---|---|---|---|
| this PC (no limits) | 5.6 s | 0.48 s | 0.18 s | **1.3 s** | 0.08 | 2.3% | 388 MB |
| budget: 2 cores @ 40% | 6.2 s | 1.20 s | 0.54 s | **2.4 s** | 0.23 | 2.5% | 381 MB |
| Celeron-class: 2 cores @ 25% | 9.6 s | 2.11 s | 0.57 s | **3.3 s** | 0.26 | 1.9% | 380 MB |

\* percent of one core while listening for "Relay" on the real microphone in a normal
room. With the wake word turned off (talk key only) idle CPU is **0.1%**.

The first sound comes immediately on start ("Starting Relay. One moment.") via
Windows' built-in voice, so a slow start is never silent.

### What fixed it (before → after, same emulation)
| | budget before | budget after | Celeron before | Celeron after |
|---|---|---|---|---|
| Wait after speaking | 10.6 s | **2.4 s** | 10.7 s | **3.3 s** |
| TTS RTF | 1.61 (stutters) | **0.23** | 1.38 | **0.26** |
| Start-up | 20.9 s | **6.2 s** | 30.9 s | **9.6 s** |
| Idle CPU while waiting for "Relay" | ~36% | **2.5%** | ~19% | **1.9%** |

- **Thread oversubscription and spin-waiting.** The voice runtime (onnxruntime) started
  one spinning thread per physical core, and the speech model's Intel OpenMP threads
  busy-wait by default. On a 2-core laptop they fought over the CPU. RELAY now sizes
  both to the cores it can actually use (≤ 4), disables spinning, and sets
  `KMP_BLOCKTIME=0` / `OMP_WAIT_POLICY=PASSIVE` (`relay/__init__.py`, `relay/audio/`).
- **Noise reaching the speech model.** Whisper costs the same ~0.4 s of CPU for any
  clip (it pads to a fixed window), and every noise blip in the room was transcribed
  to check for "Relay". Unprompted sounds are now screened first — aggressive VAD, at
  least 0.45 s of actual voice, and louder than the measured room noise floor
  (`relay/loop.py`).
- **No network at start-up.** The speech model loads with `local_files_only` once it is
  on disk; faster-whisper otherwise contacts the model hub on every start.

## Memory (1 GB cap enforced)
| Metric | Measured |
|---|---|
| Idle / baseline (core imported, no models) | **35 MB** |
| Essential peak — voice + speech model + screen reading + OCR | **402 MB** RSS (512 MB peak working set) |
| After unloading models | 191 MB (frees 211 MB) |
| Survived a hard 1 GB cap | **yes** (verified enforcement) |

A 4 GB laptop running Windows 11 typically has 1–1.5 GB free; RELAY's ~400 MB peak fits.

## Limits of the emulation (honest)
A CPU-rate cap slows throughput like a slower chip, but it can't reproduce a small
CPU cache, a slow hard disk (first start from HDD will be slower), thermal throttling,
or a busy antivirus scan. Single-threaded parts of the emulation run up to 2x faster
than on a real 2-core chip at the same cap. Final sign-off still needs a real low-end
laptop — the numbers above say it should be comfortable.
