"""Offline speech-to-text (faster-whisper, tiny.en INT8 on CPU).

Chosen over whisper.cpp after benchmarking (scripts/bench_stt.py): comparable
latency, ~35 MB less resident RAM, and a clean pip wheel (no native binary) which
matters for the 4 GB target and Windows packaging. whisper.cpp (pywhispercpp)
remains a documented fallback.

The model is loaded lazily on first use and can be unloaded to free RAM when idle.
Input is float32 mono PCM at 16 kHz (numpy); output is plain text.
"""

from __future__ import annotations

import numpy as np

from relay.config import models_dir
from relay.diagnostics import get_logger

log = get_logger("audio.stt")
SAMPLE_RATE = 16000
# Biases recognition toward the wake word: without it tiny.en hears "Relay," as
# "Really," about a third of the time. Deliberately contains no command, so even if the
# model echoed its prompt on noise it could not trigger an action (measured: silence,
# noise and mains hum all transcribe to "").
WAKE_PROMPT = "Hey Relay."


class WhisperSTT:
    def __init__(self, model_name: str = "tiny.en", compute_type: str = "int8",
                 prompt: str | None = WAKE_PROMPT) -> None:
        self.model_name = model_name
        self.compute_type = compute_type
        self.prompt = prompt
        self._model = None

    def _ensure(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            whisper_dir = models_dir() / "whisper"
            whisper_dir.mkdir(parents=True, exist_ok=True)
            # Once the model is on disk, never contact the model hub again: offline
            # mode must not make a network request (or wait on one) at every start.
            local = any(whisper_dir.rglob("model.bin"))
            log.info("loading STT model %s (%s, %s)", self.model_name, self.compute_type,
                     "local files only" if local else "may download")
            from relay import inference_threads
            self._model = WhisperModel(
                self.model_name, device="cpu", compute_type=self.compute_type,
                download_root=str(whisper_dir), local_files_only=local,
                cpu_threads=inference_threads(),
            )
        return self._model

    def transcribe(self, audio: np.ndarray, language: str = "en") -> str:
        """Transcribe float32 mono 16 kHz audio to text (may be empty)."""
        if audio is None or len(audio) == 0:
            return ""
        audio = np.asarray(audio, dtype=np.float32)
        model = self._ensure()
        segments, _ = model.transcribe(audio, language=language, beam_size=1,
                                       condition_on_previous_text=False,
                                       initial_prompt=self.prompt)
        return " ".join(s.text for s in segments).strip()

    def unload(self) -> None:
        """Drop the model to free RAM (reloaded lazily on next transcribe)."""
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None
