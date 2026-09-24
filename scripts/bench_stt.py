"""Benchmark whisper.cpp (pywhispercpp) vs faster-whisper on tiny.en INT8.

Deterministic and offline: synthesizes a known command phrase with Windows SAPI
(no mic needed), then transcribes it with both engines, reporting model-load time,
transcription latency, transcript accuracy vs the known text, and process RSS.

This informs the RELAY STT choice (spec §6). Run:
    uv run python scripts/bench_stt.py
Downloads the two tiny.en models on first run (~75 MB each).
"""

from __future__ import annotations

import time
import wave
from pathlib import Path

import numpy as np
import psutil

PHRASE = "open notepad and search for the weather in london"


def rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1e6


def synth_sapi_wav(text: str, path: Path) -> None:
    import win32com.client
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Open(str(path), 3, False)  # SSFMCreateForWrite
    voice.AudioOutputStream = stream
    voice.Speak(text)
    stream.Close()


def load_wav_16k_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[sw]
    x = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if dtype == np.int16:
        x /= 32768.0
    elif dtype == np.int32:
        x /= 2147483648.0
    else:  # uint8
        x = (x - 128) / 128.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x), n, endpoint=False),
                      np.arange(len(x)), x).astype(np.float32)
    return x


def norm(s: str) -> list[str]:
    return "".join(c.lower() if c.isalnum() or c == " " else " " for c in s).split()


def wer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    # Levenshtein on words
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    return d[len(r)][len(h)] / max(1, len(r))


def bench_faster_whisper(audio: np.ndarray, models_dir: Path) -> dict:
    from faster_whisper import WhisperModel
    base = rss_mb()
    t0 = time.perf_counter()
    m = WhisperModel("tiny.en", device="cpu", compute_type="int8",
                     download_root=str(models_dir))
    load = time.perf_counter() - t0
    after_load = rss_mb()
    t1 = time.perf_counter()
    segs, _ = m.transcribe(audio, language="en", beam_size=1)
    text = " ".join(s.text for s in segs).strip()
    infer = time.perf_counter() - t1
    return {"engine": "faster-whisper", "text": text, "load_s": load,
            "infer_s": infer, "rss_delta_mb": after_load - base, "wer": wer(PHRASE, text)}


def bench_whispercpp(audio: np.ndarray) -> dict:
    from pywhispercpp.model import Model
    base = rss_mb()
    t0 = time.perf_counter()
    m = Model("tiny.en", print_progress=False, print_realtime=False)
    load = time.perf_counter() - t0
    after_load = rss_mb()
    t1 = time.perf_counter()
    segs = m.transcribe(audio)
    text = " ".join(s.text for s in segs).strip()
    infer = time.perf_counter() - t1
    return {"engine": "whisper.cpp", "text": text, "load_s": load,
            "infer_s": infer, "rss_delta_mb": after_load - base, "wer": wer(PHRASE, text)}


def main() -> None:
    from relay.config import models_dir
    md = models_dir()
    wav = md / "_bench.wav"
    print(f"Synthesizing phrase via SAPI -> {wav.name}")
    synth_sapi_wav(PHRASE, wav)
    audio = load_wav_16k_mono(wav)
    dur = len(audio) / 16000
    print(f'ref: "{PHRASE}"  ({dur:.1f}s audio)\n')

    results = []
    for fn in (lambda: bench_whispercpp(audio), lambda: bench_faster_whisper(audio, md)):
        try:
            r = fn()
            results.append(r)
            print(f"[{r['engine']:>14}] load={r['load_s']:.2f}s infer={r['infer_s']:.2f}s "
                  f"rtf={r['infer_s']/dur:.2f} rss+={r['rss_delta_mb']:.0f}MB wer={r['wer']:.2f}")
            print(f'                 -> "{r["text"]}"')
        except Exception as e:
            print(f"ENGINE FAILED: {type(e).__name__}: {e}")

    if len(results) == 2:
        a, b = results
        print("\nSummary (lower is better): "
              f"{a['engine']} rtf={a['infer_s']/dur:.2f}/rss+{a['rss_delta_mb']:.0f}MB vs "
              f"{b['engine']} rtf={b['infer_s']/dur:.2f}/rss+{b['rss_delta_mb']:.0f}MB")


if __name__ == "__main__":
    main()
