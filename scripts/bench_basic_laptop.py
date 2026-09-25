"""How RELAY feels on a basic laptop — measured under emulated low-end hardware.

Each profile runs in a fresh child process that pins itself to a few physical cores,
hard-caps its CPU speed with a Windows Job Object CPU-rate limit, and caps memory at
1 GB. Then it measures what a user actually waits for, with the real models:

  * start-up until RELAY can speak and understand (voice + speech model loaded)
  * after you stop talking: speech recognition of a spoken command
  * understanding + doing the command, then synthesising the first reply
  * idle CPU while listening for the wake word on the real microphone
  * peak memory

The emulation is honest but approximate: a hard CPU cap slows throughput the way a
slower chip does, but it cannot reproduce a small cache or a slow disk.

    uv run python scripts/bench_basic_laptop.py              # all profiles
    uv run python scripts/bench_basic_laptop.py --profile budget
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

PROFILES = {
    "this-pc": (0, 1.0),        # no limits (reference)
    "budget": (2, 0.40),        # 2 cores at ~40%: i3 / Ryzen 3 / older i5 class
    "celeron": (2, 0.25),       # 2 cores at ~25%: Celeron / Pentium Silver class
}
VAD_HANGOVER_S = 0.60           # silence RELAY waits for before deciding you've finished


def _resample(a, sr):
    import numpy as np
    if sr == 16000:
        return a.astype(np.float32)
    n = int(len(a) * 16000 / sr)
    return np.interp(np.linspace(0, len(a), n, endpoint=False), np.arange(len(a)),
                     a).astype(np.float32)


def run_profile(name: str, audio_path: str) -> dict:
    import numpy as np

    from relay.diagnostics.perf import (
        emulate_slow_cpu,
        peak_working_set_mb,
        rss_mb,
        set_process_memory_limit_mb,
    )
    cores, speed = PROFILES[name]
    limited = True
    if cores:
        limited = emulate_slow_cpu(cores, speed) and set_process_memory_limit_mb(1024)
    cmd_audio = np.load(audio_path)
    out: dict = {"profile": name, "limits_applied": limited}

    t0 = time.perf_counter()
    from relay.audio import WhisperSTT, make_tts
    tts = make_tts(prefer_piper=True)
    tts.synth_to_array("Relay is ready.")
    stt = WhisperSTT()
    stt.transcribe(np.zeros(8000, dtype=np.float32))
    os.environ.setdefault("RELAY_DATA_DIR", tempfile.mkdtemp())
    from relay.session import Session
    said: list[str] = []
    s = Session(speak=said.append, db_path=":memory:")
    out["startup_s"] = time.perf_counter() - t0

    t = time.perf_counter()
    text = stt.transcribe(cmd_audio)
    out["stt_s"] = time.perf_counter() - t
    out["heard"] = text

    t = time.perf_counter()
    from relay.audio.wake import detect_wake
    s.handle(detect_wake(text)[1] or text)
    out["handle_s"] = time.perf_counter() - t
    reply = said[-1] if said else "Done."
    out["reply"] = reply

    t = time.perf_counter()
    a, sr = tts.synth_to_array(reply)
    out["tts_reply_s"] = time.perf_counter() - t
    long_line = ("I'm going to open Notepad. Done. Notepad is open, and the text box is "
                 "focused, so you can start typing whenever you're ready.")
    t = time.perf_counter()
    a2, sr2 = tts.synth_to_array(long_line)
    synth = time.perf_counter() - t
    out["tts_long_rtf"] = synth / (len(a2) / sr2)

    out["wait_after_speaking_s"] = VAD_HANGOVER_S + out["stt_s"] + out["handle_s"] \
        + out["tts_reply_s"]

    # idle: real microphone, wake-word listening, for 15 seconds
    import psutil

    from relay.loop import VoiceLoop
    loop = VoiceLoop(lambda t: None, stt=stt, wake_required=True)
    p = psutil.Process()
    c0 = sum(p.cpu_times()[:2])
    try:
        loop.run()
        w0 = time.perf_counter()
        time.sleep(15)
        wall = time.perf_counter() - w0
        loop.stop()
        out["idle_cpu_pct_of_one_core"] = 100 * (sum(p.cpu_times()[:2]) - c0) / wall
    except Exception as e:
        out["idle_cpu_pct_of_one_core"] = None
        out["idle_note"] = f"microphone unavailable: {e}"
    out["rss_mb"] = rss_mb()
    out["peak_mb"] = peak_working_set_mb()
    s.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=list(PROFILES), action="append")
    ap.add_argument("--child", help=argparse.SUPPRESS)
    ap.add_argument("--audio", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.child:
        print("RESULT " + json.dumps(run_profile(args.child, args.audio)))
        return 0

    # the spoken command, synthesised once (outside the limits) and reused by all
    import numpy as np

    from relay.audio import make_tts
    a, sr = make_tts(prefer_piper=True).synth_to_array("Relay, what is twenty five times four?")
    tmp = os.path.join(tempfile.mkdtemp(), "cmd.npy")
    np.save(tmp, _resample(a, sr))

    results = []
    for name in args.profile or list(PROFILES):
        print(f"running profile {name} ...", flush=True)
        r = subprocess.run([sys.executable, __file__, "--child", name, "--audio", tmp],
                           capture_output=True, text=True, timeout=900)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")), None)
        if line is None:
            print(r.stdout[-2000:], r.stderr[-2000:])
            continue
        results.append(json.loads(line[7:]))

    print("\nRELAY on emulated hardware (1 GB memory cap on limited profiles)")
    hdr = (f"{'profile':9} {'start':>7} {'STT':>6} {'do':>6} {'reply TTS':>9} "
           f"{'WAIT':>6} {'TTS rtf':>7} {'idle CPU':>8} {'peak MB':>8}")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        idle = r.get("idle_cpu_pct_of_one_core")
        print(f"{r['profile']:9} {r['startup_s']:6.1f}s {r['stt_s']:5.2f}s "
              f"{r['handle_s']:5.2f}s {r['tts_reply_s']:8.2f}s "
              f"{r['wait_after_speaking_s']:5.1f}s {r['tts_long_rtf']:7.2f} "
              f"{(f'{idle:6.1f}%' if idle is not None else '   n/a'):>8} "
              f"{(r.get('peak_mb') or r['rss_mb']):8.0f}")
    for r in results:
        print(f"  {r['profile']}: heard {r['heard']!r} -> replied {r['reply']!r}"
              + ("" if r["limits_applied"] else "  (LIMITS NOT APPLIED)"))
    print("\nWAIT = silence detection (0.6 s) + recognition + doing it + first reply audio."
          " TTS rtf < 1 means speech is generated faster than it plays.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
