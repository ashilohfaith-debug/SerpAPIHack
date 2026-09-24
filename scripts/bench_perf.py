"""RELAY performance benchmark — real, measured numbers (never estimates).

Measures the Essential-mode footprint and latencies on this machine, verifies lazy
load/unload frees RAM, and (with --limit-mb) runs the whole thing under a hard
Windows Job Object commit cap — the honest proxy for a 4 GB machine on a bigger box.

    uv run python scripts/bench_perf.py                 # measure, no cap
    uv run python scripts/bench_perf.py --limit-mb 1024  # must survive a 1 GB cap
    uv run python scripts/bench_perf.py --no-ocr         # skip full-screen OCR

Targets (provisional): idle < 200 MB, Essential peak < 1 GB. Reported pass/fail is
measured, not claimed.
"""

from __future__ import annotations

import argparse
import gc
import sys
import time

import numpy as np

from relay.diagnostics.perf import (
    Measure,
    peak_working_set_mb,
    process_tree_rss_mb,
    rss_mb,
    set_process_memory_limit_mb,
)


def _resample_16k(audio, sr):
    if sr == 16000 or not len(audio):
        return audio.astype(np.float32)
    n = int(len(audio) * 16000 / sr)
    return np.interp(np.linspace(0, len(audio), n, endpoint=False),
                     np.arange(len(audio)), audio).astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-mb", type=int, default=0)
    ap.add_argument("--no-ocr", action="store_true")
    args = ap.parse_args()

    capped = False
    if args.limit_mb:
        capped = set_process_memory_limit_mb(args.limit_mb)
        print(f"[constrained] hard process memory cap = {args.limit_mb} MB "
              f"({'applied' if capped else 'FAILED to apply'})")

    baseline = rss_mb()
    print(f"\nbaseline RSS (core imported, no models loaded): {baseline:6.0f} MB")

    rows = []
    try:
        # --- TTS (Piper) load + synth ---
        from relay.audio import make_tts
        tts = make_tts(prefer_piper=True)
        with Measure("TTS Piper load+synth") as m:
            audio, sr = tts.synth_to_array("open notepad and read the screen to me")
        rows.append((m.label, m.seconds, m.rss_after_mb))

        # --- STT (faster-whisper) load + transcribe (cold, then warm) ---
        from relay.audio import WhisperSTT
        a16 = _resample_16k(audio, sr)
        stt = WhisperSTT()
        with Measure("STT load+transcribe (cold)") as m:
            stt.transcribe(a16)
        rows.append((m.label, m.seconds, m.rss_after_mb))
        with Measure("STT transcribe (warm)") as m:
            stt.transcribe(a16)
        rows.append((m.label, m.seconds, m.rss_after_mb))

        # --- UIA observe latency ---
        from relay.perception import UIAWorker
        worker = UIAWorker()
        worker.start()
        worker.observe(5.0)  # warm the COM thread
        with Measure("UIA observe (warm)") as m:
            worker.observe(5.0)
        rows.append((m.label, m.seconds, m.rss_after_mb))

        # --- SQLite memory ops ---
        from relay.memory import MemoryStore, connect
        store = MemoryStore(connect(":memory:"))
        with Measure("SQLite 200 pref writes") as m:
            for i in range(200):
                store.set_pref(f"k{i}", "value")
        rows.append((m.label, m.seconds, m.rss_after_mb))

        ocr = None
        if not args.no_ocr:
            from relay.perception.ocr import OCR
            ocr = OCR()
            with Measure("OCR load+full-screen") as m:
                n = len(ocr.read_screen())
            rows.append((f"{m.label} ({n} regions)", m.seconds, m.rss_after_mb))

        peak = rss_mb()
        tree = process_tree_rss_mb()
        pk = peak_working_set_mb()

        # --- unload models, verify RAM drops ---
        stt.unload()
        if hasattr(tts, "unload"):
            tts.unload()
        if ocr is not None:
            ocr.unload()
        worker.stop()
        gc.collect()
        time.sleep(0.6)
        after_unload = rss_mb()

    except MemoryError:
        print("\nRESULT: hit the memory cap (MemoryError) — Essential peak does NOT fit "
              f"under {args.limit_mb} MB on this run.")
        return 1

    print("\n  phase                              time      RSS after")
    print("  " + "-" * 52)
    for label, secs, rss in rows:
        print(f"  {label:34} {secs:6.2f}s   {rss:6.0f} MB")

    print("\n  -- summary (measured on this machine) --")
    print(f"  idle / baseline (no models):     {baseline:6.0f} MB   (target < 200)")
    print(f"  Essential peak (all models):     {peak:6.0f} MB   (target < 1000)")
    print(f"  process-tree RSS (with workers): {tree:6.0f} MB")
    if pk:
        print(f"  peak working set:                {pk:6.0f} MB")
    print(f"  after unload + gc:               {after_unload:6.0f} MB   "
          f"(freed {max(0, peak - after_unload):.0f} MB)")
    idle_ok = baseline < 200
    peak_ok = peak < 1000
    print(f"\n  idle target: {'PASS' if idle_ok else 'over'};  "
          f"peak target: {'PASS' if peak_ok else 'over'}"
          + (f";  survived {args.limit_mb} MB cap" if capped else ""))
    print("  (Measured on this dev CPU/box, not a real 4 GB laptop; the --limit-mb cap "
          "is the constrained-env proxy.)")
    return 0 if peak_ok else 2


if __name__ == "__main__":
    sys.exit(main())
