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

from relay.diagnostics import get_logger

log = get_logger("audio.tts")


class PiperTTS:
    """Neural CPU voice via Piper. Produces float32 mono samples at the voice's
    native sample rate (22050 for *-medium)."""

    def __init__(self, onnx_path: Path) -> None:
        self.onnx_path = Path(onnx_path)
        self._voice = None
        self.sample_rate = 22050
        self.rate = 1.0

    def _ensure(self):
        if self._voice is None:
            self._voice = self._load()
        return self._voice

    def _load(self):
        """Like PiperVoice.load, but with an inference session sized for the machine:
        onnxruntime otherwise starts a spinning thread per physical core, which on a
        2-core laptop steals the CPU the voice itself needs."""
        import json

        import onnxruntime
        from piper import PiperVoice
        from piper.config import PiperConfig

        from relay import inference_threads
        with open(f"{self.onnx_path}.json", encoding="utf-8") as f:
            cfg = json.load(f)
        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = inference_threads()
        opts.inter_op_num_threads = 1
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        session = onnxruntime.InferenceSession(str(self.onnx_path), sess_options=opts,
                                               providers=["CPUExecutionProvider"])
        return PiperVoice(session=session, config=PiperConfig.from_dict(cfg),
                          download_dir=self.onnx_path.parent)

    def set_rate(self, rate: float) -> None:
        """Speech speed multiplier (1.0 normal; 1.5 = 50% faster)."""
        self.rate = max(0.5, min(2.5, float(rate)))

    def synth_to_array(self, text: str) -> tuple[np.ndarray, int]:
        if not text.strip():
            return np.zeros(0, dtype=np.float32), self.sample_rate
        voice = self._ensure()
        cfg = None
        if abs(self.rate - 1.0) > 1e-3:
            from piper import SynthesisConfig
            cfg = SynthesisConfig(length_scale=1.0 / self.rate)
        chunks = list(voice.synthesize(text, syn_config=cfg))
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

    def unload(self) -> None:
        """Drop the loaded voice to free RAM (reloaded lazily on next synth)."""
        self._voice = None


class SapiTTS:
    """Windows SAPI5 fallback. Always offline, no model download."""

    def __init__(self) -> None:
        import threading
        self._local = threading.local()   # one COM voice per thread (apartment-safe)
        self.rate = 1.0

    def _ensure(self):
        voice = getattr(self._local, "voice", None)
        if voice is None:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()   # SAPI is used from the speech thread
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            self._local.voice = voice
        return voice

    def set_rate(self, rate: float) -> None:
        # applied on the speech thread at the next synth (COM objects stay on one thread)
        self.rate = max(0.5, min(2.5, float(rate)))

    def synth_to_array(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize to a temp WAV via SpFileStream, read it back as float32."""
        if not text.strip():
            return np.zeros(0, dtype=np.float32), 22050
        import tempfile

        import win32com.client
        voice = self._ensure()
        try:  # SAPI rate is -10..10; map 0.5x..2.5x onto it
            voice.Rate = int(max(-10, min(10, round((self.rate - 1.0) * 8))))
        except Exception:
            pass
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
    """The installed Piper voice RELAY should use: the configured voice, else the
    release (public-domain) voice, else any complete installed voice."""
    from relay.config import Config
    from relay.models_manager import voice_path
    try:
        preferred = Config.load().voice
    except Exception:
        preferred = None
    return voice_path(preferred)


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
