"""Managed model files — presence, integrity, and offline setup.

RELAY's Essential models live under ``models/`` (gitignored). This module reports
what's present and can fetch what's missing, so a packaged build or a fresh checkout
can be made fully offline-ready in one step. It never downloads optional LLM/VLM
weights. Integrity here is a presence + non-empty check (the download tools verify
their own payloads); a stronger per-file hash manifest can be added at release time.
"""

from __future__ import annotations

import subprocess
import sys

from relay.config import models_dir

PIPER_VOICE = "en_US-lessac-medium"


def _piper_onnx():
    d = models_dir() / "piper"
    files = sorted(d.glob("*.onnx")) if d.exists() else []
    return files[0] if files else None


def _whisper_present() -> bool:
    d = models_dir() / "whisper"
    return d.exists() and any(d.rglob("*.bin"))


def status() -> list[dict]:
    """Report each managed model: name, present, size (MB), and how to get it."""
    out = []
    voice = _piper_onnx()
    out.append({
        "name": f"Piper voice ({PIPER_VOICE})",
        "present": voice is not None,
        "size_mb": round(voice.stat().st_size / 1e6, 1) if voice else 0.0,
        "how": f"python -m piper.download_voices {PIPER_VOICE} --data-dir models/piper",
    })
    out.append({
        "name": "faster-whisper tiny.en (STT)",
        "present": _whisper_present(),
        "size_mb": None,
        "how": "downloaded automatically into models/whisper on first STT use",
    })
    out.append({
        "name": "RapidOCR ONNX (OCR)",
        "present": _rapidocr_installed(),
        "size_mb": None,
        "how": "ships inside the rapidocr-onnxruntime package (no separate file)",
    })
    return out


def _rapidocr_installed() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def ensure(download: bool = True) -> bool:
    """Make Essential models present offline. Downloads the Piper voice if missing
    and warms the whisper cache. Returns True if everything is present afterward."""
    ok = True
    if _piper_onnx() is None:
        if download:
            piper_dir = models_dir() / "piper"
            piper_dir.mkdir(parents=True, exist_ok=True)
            print(f"downloading Piper voice {PIPER_VOICE} …")
            r = subprocess.run(
                [sys.executable, "-m", "piper.download_voices", PIPER_VOICE,
                 "--data-dir", str(piper_dir)],
                capture_output=True, text=True)
            if r.returncode != 0:
                print("  piper download failed:", r.stderr.strip()[:200])
                ok = False
        else:
            ok = False
    if not _whisper_present():
        if download:
            print("warming whisper tiny.en cache …")
            try:
                from relay.audio import WhisperSTT
                WhisperSTT()._ensure()  # triggers the model download into models/whisper
            except Exception as e:
                print("  whisper warm failed:", str(e)[:200])
                ok = False
        else:
            ok = False
    return ok and _piper_onnx() is not None and _whisper_present()


def status_text() -> str:
    lines = ["Managed models:"]
    for m in status():
        size = f" ({m['size_mb']} MB)" if m["size_mb"] else ""
        mark = "OK " if m["present"] else "-- "
        lines.append(f"  [{mark}] {m['name']}{size}")
        if not m["present"]:
            lines.append(f"         get: {m['how']}")
    return "\n".join(lines)
