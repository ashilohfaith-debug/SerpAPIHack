"""Offline speech-to-text (faster-whisper, accuracy-first INT8 on CPU).

``base.en`` is the default because the previous ``tiny.en`` model was fast but too
often lost place names, prices, and short accessibility commands.  A user can still
select ``tiny.en`` on a very small machine with ``RELAY_STT_MODEL=tiny.en``.

The model is loaded lazily on first use and can be unloaded to free RAM when idle.
Input is float32 mono PCM at 16 kHz (numpy); output is plain text.
"""

from __future__ import annotations

import os

import numpy as np

from relay.config import models_dir
from relay.diagnostics import get_logger

log = get_logger("audio.stt")
SAMPLE_RATE = 16000
DEFAULT_STT_MODEL = "base.en"
# Biases recognition toward the wake word: without it tiny.en hears "Relay," as
# "Really," about a third of the time. Deliberately contains no command, so even if the
# model echoed its prompt on noise it could not trigger an action (measured: silence,
# noise and mains hum all transcribe to "").
WAKE_PROMPT = "Hey Relay."
COMMAND_HOTWORDS = (
    "Relay, SerpApi, Bengaluru, Bangalore, Indiranagar, Chennai, nonstop, "
    "flight, hotel, restaurant, book, confirm, cancel, Notepad, File Explorer"
)


class WhisperSTT:
    def __init__(
        self,
        model_name: str | None = None,
        compute_type: str = "int8",
        prompt: str | None = WAKE_PROMPT,
        beam_size: int | None = None,
    ) -> None:
        self.model_name = model_name or os.environ.get("RELAY_STT_MODEL", DEFAULT_STT_MODEL)
        self.compute_type = compute_type
        self.prompt = prompt
        configured_beam = os.environ.get("RELAY_STT_BEAM_SIZE", "3")
        try:
            selected_beam = beam_size if beam_size is not None else int(configured_beam)
        except (TypeError, ValueError):
            selected_beam = 3
            log.warning("invalid RELAY_STT_BEAM_SIZE=%r; using 3", configured_beam)
        self.beam_size = max(1, min(5, selected_beam))
        self._model = None
        self.last_language = ""
        self.last_language_probability = 0.0

    def _cached_locally(self, whisper_dir) -> bool:
        """Check the requested model, not merely any Whisper model in the cache."""
        if os.path.isdir(self.model_name):
            return True
        safe_name = self.model_name.replace("/", "--")
        candidates = (
            whisper_dir / f"models--Systran--faster-whisper-{safe_name}",
            whisper_dir / f"models--{safe_name}",
        )
        return any(path.exists() and any(path.rglob("model.bin")) for path in candidates)

    def _ensure(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            whisper_dir = models_dir() / "whisper"
            whisper_dir.mkdir(parents=True, exist_ok=True)
            # Once the model is on disk, never contact the model hub again: offline
            # mode must not make a network request (or wait on one) at every start.
            local = self._cached_locally(whisper_dir)
            log.info(
                "loading STT model %s (%s, %s)",
                self.model_name,
                self.compute_type,
                "local files only" if local else "may download",
            )
            from relay import inference_threads

            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type=self.compute_type,
                download_root=str(whisper_dir),
                local_files_only=local,
                cpu_threads=inference_threads(),
            )
        return self._model

    def transcribe(self, audio: np.ndarray, language: str = "en") -> str:
        """Transcribe float32 mono 16 kHz audio to text (may be empty)."""
        if audio is None or len(audio) == 0:
            return ""
        audio = np.asarray(audio, dtype=np.float32)
        model = self._ensure()
        segments, info = model.transcribe(
            audio,
            language=language,
            beam_size=self.beam_size,
            patience=1.0,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=self.prompt,
            hotwords=COMMAND_HOTWORDS,
            no_speech_threshold=0.55,
            vad_filter=False,
        )
        text = " ".join(s.text for s in segments).strip()
        self.last_language = getattr(info, "language", language) or language
        self.last_language_probability = float(
            getattr(info, "language_probability", 0.0) or 0.0
        )
        return text

    def unload(self) -> None:
        """Drop the model to free RAM (reloaded lazily on next transcribe)."""
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None
