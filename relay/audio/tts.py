"""Offline text-to-speech: Piper (preferred) with a Windows SAPI fallback.

Piper gives a natural neural voice on CPU; SAPI is always available on Windows and
needs no model download, so it is the guaranteed fallback. Both expose the same
interface: synth_to_array() for tests/benchmarks and speak()/interrupt() for the
speech queue. Real audio playback lives in speech.py (this module only produces
samples / drives SAPI), so barge-in and the emergency stop control one output path.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from relay.config import models_dir
from relay.diagnostics import get_logger

log = get_logger("audio.tts")


class PiperTTS:
    """Neural CPU voice via Piper. Produces float32 mono samples at the voice's
    native sample rate (22050 for *-medium)."""

    def __init__(self, onnx_path: Path) -> None:
        self.onnx_path = Path(onnx_path)
        self._voice = None
        self.sample_rate = 22050

    def _ensure(self):
        if self._voice is None:
            from piper import PiperVoice
            self._voice = PiperVoice.load(str(self.onnx_path))
        return self._voice

    def synth_to_array(self, text: str) -> tuple[np.ndarray, int]:
        if not text.strip():
            return np.zeros(0, dtype=np.float32), self.sample_rate
        voice = self._ensure()
        chunks = list(voice.synthesize(text))
        if not chunks:
            return np.zeros(0, dtype=np.float32), self.sample_rate
        self.sample_rate = chunks[0].sample_rate
        audio = np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32)
        return audio, self.sample_rate

    def available(self) -> bool:
        try:
            self._ensure()
            return True
        except Exception as e:
            log.warning("Piper unavailable: %s", e)
            return False


class SapiTTS:
    """Windows SAPI5 fallback. Always offline, no model download."""

    def __init__(self) -> None:
        self._voice = None

    def _ensure(self):
        if self._voice is None:
            import win32com.client
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
        return self._voice

    def synth_to_array(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize to a temp WAV via SpFileStream, read it back as float32."""
        if not text.strip():
            return np.zeros(0, dtype=np.float32), 22050
        import tempfile

        import win32com.client
        voice = self._ensure()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            stream.Open(path, 3, False)  # SSFMCreateForWrite
            voice.AudioOutputStream = stream
            voice.Speak(text)
            stream.Close()
            with wave.open(path, "rb") as w:
                sr = w.getframerate()
                raw = w.readframes(w.getnframes())
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            return audio, sr
        finally:
            Path(path).unlink(missing_ok=True)

    def speak_blocking(self, text: str) -> None:
        """Speak directly through SAPI (used only if no unified playback path)."""
        self._ensure().Speak(text)

    def available(self) -> bool:
        try:
            self._ensure()
            return True
        except Exception as e:
            log.warning("SAPI unavailable: %s", e)
            return False


def default_piper_voice() -> Path | None:
    """Return a Piper voice .onnx under models/piper if one is present."""
    d = models_dir() / "piper"
    if not d.exists():
        return None
    voices = sorted(d.glob("*.onnx"))
    return voices[0] if voices else None


def make_tts(prefer_piper: bool = True):
    """Pick the TTS engine: Piper if a voice is installed and loads, else SAPI."""
    if prefer_piper:
        voice = default_piper_voice()
        if voice is not None:
            piper = PiperTTS(voice)
            if piper.available():
                log.info("TTS: Piper (%s)", voice.name)
                return piper
    sapi = SapiTTS()
    if sapi.available():
        log.info("TTS: SAPI fallback")
        return sapi
    raise RuntimeError("no TTS engine available (Piper voice missing and SAPI failed)")
