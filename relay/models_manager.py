"""Managed model files — presence, licences, and offline setup.

RELAY's models live under ``models/`` (gitignored). This module reports what's
present, which voice is active and under what licence, and fetches what's missing so
a packaged build or a fresh checkout can be made fully offline-ready in one step. It
never downloads optional LLM/VLM weights and never needs an account or key.

Voices are chosen for their licence as well as their sound. The release voice is
``en_US-ljspeech-medium``: public-domain recordings, trained from scratch. The earlier
``en_US-lessac-medium`` is still usable if present, but its training data (Blizzard
2013 Lessac) is licensed for research only — not for commercial redistribution.

Downloads are resumable and size-verified: bytes go to ``<file>.part`` and are renamed
only when complete, so a slow or broken connection can never leave a half voice that
RELAY would try to load.
"""

from __future__ import annotations

import os
import time
import urllib.request
from pathlib import Path

from relay.config import models_dir

_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOICES = {
    "en_US-ljspeech-medium": {
        "path": "en/en_US/ljspeech/medium/",
        "licence": "public domain (LJ Speech), trained from scratch",
        "release_ok": True,
    },
    "en_US-lessac-medium": {
        "path": "en/en_US/lessac/medium/",
        "licence": "Blizzard 2013 Lessac data: research use only, no commercial use",
        "release_ok": False,
    },
}
DEFAULT_VOICE = "en_US-ljspeech-medium"
PIPER_VOICE = DEFAULT_VOICE  # kept for older callers


def _piper_dir() -> Path:
    return models_dir() / "piper"


def installed_voices() -> list[str]:
    d = _piper_dir()
    if not d.exists():
        return []
    return sorted(
        p.stem
        for p in d.glob("*.onnx")
        if Path(f"{p}.json").exists() and p.stat().st_size > 1_000_000
    )


def active_voice(preferred: str | None = None) -> str | None:
    """The voice RELAY will speak with: the configured one if installed, else the
    release voice, else any installed voice (release-licensed first)."""
    have = installed_voices()
    for name in (preferred, DEFAULT_VOICE):
        if name and name != "default" and name in have:
            return name
    have.sort(key=lambda n: not VOICES.get(n, {}).get("release_ok", False))
    return have[0] if have else None


def voice_path(preferred: str | None = None) -> Path | None:
    name = active_voice(preferred)
    return _piper_dir() / f"{name}.onnx" if name else None


def voice_licence(name: str | None) -> tuple[str, bool]:
    info = VOICES.get(name or "", {})
    return info.get("licence", "unknown licence — check its model card"), bool(
        info.get("release_ok", False)
    )


def _piper_onnx():
    return voice_path()


def _whisper_model_name() -> str:
    return os.environ.get("RELAY_STT_MODEL", "base.en").strip() or "base.en"


def _whisper_present(model_name: str | None = None) -> bool:
    model_name = model_name or _whisper_model_name()
    direct = Path(model_name)
    if direct.is_dir():
        return (direct / "model.bin").exists()
    d = models_dir() / "whisper"
    safe_name = model_name.replace("/", "--")
    candidates = (
        d / f"models--Systran--faster-whisper-{safe_name}",
        d / f"models--{safe_name}",
    )
    return any(path.exists() and any(path.rglob("model.bin")) for path in candidates)


def status() -> list[dict]:
    """Report each managed model: name, present, size (MB), and how to get it."""
    out = []
    voice = active_voice()
    p = voice_path()
    licence, ok = voice_licence(voice)
    out.append(
        {
            "name": f"Voice {voice or DEFAULT_VOICE} ({licence})",
            "present": p is not None,
            "size_mb": round(p.stat().st_size / 1e6, 1) if p else 0.0,
            "how": "relay --setup-models",
            "release_ok": ok,
        }
    )
    out.append(
        {
            "name": f"faster-whisper {_whisper_model_name()} (STT)",
            "present": _whisper_present(),
            "size_mb": None,
            "how": "relay --setup-models (downloaded once into models/whisper)",
        }
    )
    out.append(
        {
            "name": "RapidOCR ONNX (OCR)",
            "present": _rapidocr_installed(),
            "size_mb": None,
            "how": "ships inside the rapidocr-onnxruntime package (no separate file)",
        }
    )
    return out


def _rapidocr_installed() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except Exception:
        return False


def download(
    url: str, dest: Path, attempts: int = 30, timeout: float = 30.0, progress=None
) -> bool:
    """Resumable, size-verified download to ``dest`` (via ``dest.part``)."""
    part = Path(f"{dest}.part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = None
    for attempt in range(attempts):
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent": "RELAY-setup"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                length = resp.headers.get("Content-Length")
                if resp.status == 206:
                    rng = resp.headers.get("Content-Range", "")
                    total = int(rng.rsplit("/", 1)[-1]) if "/" in rng else None
                else:
                    have = 0  # server ignored Range: start over
                    total = int(length) if length else None
                with open(part, "ab" if have else "wb") as f:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        if progress is not None:
                            progress(part.stat().st_size, total)
        except (OSError, ValueError) as e:
            if progress is not None:
                progress(part.stat().st_size if part.exists() else 0, total, error=str(e))
            time.sleep(min(30, 2 + attempt * 2))
            continue
        size = part.stat().st_size
        if total is None or size == total:
            part.replace(dest)
            return True
    return False


def download_voice(name: str = DEFAULT_VOICE, progress=None) -> bool:
    info = VOICES[name]
    base = _HF + info["path"] + name
    d = _piper_dir()
    ok = download(f"{base}.onnx.json", d / f"{name}.onnx.json", progress=progress)
    return ok and download(f"{base}.onnx", d / f"{name}.onnx", progress=progress)


def ensure(download_missing: bool = True, download: bool | None = None) -> bool:
    """Make the models present offline: the release voice and the speech model."""
    if download is not None:  # older keyword
        download_missing = download
    ok = True
    if DEFAULT_VOICE not in installed_voices():
        if download_missing:
            print(f"downloading voice {DEFAULT_VOICE} (public domain) …")

            def show(done, total, error=None):
                if error:
                    print(f"  connection problem ({error[:60]}); retrying …")
                elif total:
                    print(f"\r  {done / 1e6:5.1f} / {total / 1e6:.1f} MB", end="", flush=True)

            if not download_voice(DEFAULT_VOICE, progress=show):
                print("\n  voice download did not finish")
                ok = False
            else:
                print()
        else:
            ok = False
    if not _whisper_present():
        if download_missing:
            print(f"downloading the speech-recognition model (whisper {_whisper_model_name()}) …")
            try:
                from relay.audio import WhisperSTT

                WhisperSTT()._ensure()  # triggers the model download into models/whisper
            except Exception as e:
                print("  whisper download failed:", str(e)[:200])
                ok = False
        else:
            ok = False
    return ok and voice_path() is not None and _whisper_present()


def status_text() -> str:
    lines = ["Managed models:"]
    for m in status():
        size = f" ({m['size_mb']} MB)" if m["size_mb"] else ""
        mark = "OK " if m["present"] else "-- "
        lines.append(f"  [{mark}] {m['name']}{size}")
        if not m["present"]:
            lines.append(f"         get: {m['how']}")
        elif m.get("release_ok") is False:
            lines.append(
                "         note: fine for testing; for public release run "
                "relay --setup-models to get the public-domain voice"
            )
    return "\n".join(lines)
