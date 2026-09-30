"""Sarvam as RELAY's voice (Bulbul) and, optionally, its ears (Saaras) — with the
offline engines always underneath.

``SarvamTTS`` and ``SarvamSTT`` have the same interface as the offline Piper / Whisper
engines, so they drop straight into the speech queue and the voice loop. Any failure
(no internet, a bad key, rate limits) falls back to the offline engine for that
utterance — RELAY never goes silent because a server is unreachable — and tells the
user once. Anything that looks like a password or code is always spoken by the
offline voice, so it is never sent anywhere.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

from relay.diagnostics import get_logger
from relay.memory.store import looks_sensitive
from relay.sarvam.client import API_BASE, SarvamClient, SarvamError, float_to_wav

log = get_logger("sarvam")


def settings() -> dict:
    """Sarvam settings from the environment (.env). Empty key = Sarvam off."""
    from relay.envfile import offline_forced
    from relay.memory.secrets import get_secret

    return {
        "key": "" if offline_forced() else os.environ.get("SARVAM_API_KEY", "").strip() or get_secret("SARVAM_API_KEY", "").strip(),
        "tts_model": os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3").strip() or "bulbul:v3",
        "speaker": os.environ.get("SARVAM_SPEAKER", "").strip(),
        "language": os.environ.get("SARVAM_LANGUAGE", "en-IN").strip() or "en-IN",
        # one key = both: Bulbul voice AND Saaras recognition (SARVAM_STT=off keeps only
        # the voice)
        "stt": os.environ.get("SARVAM_STT", "on").strip().lower()
        not in ("0", "off", "false", "no"),
        "stt_model": os.environ.get("SARVAM_STT_MODEL", "saaras:v3").strip() or "saaras:v3",
        # your own proxy in front of Sarvam (it adds the real key), for public builds
        "base": os.environ.get("SARVAM_BASE_URL", "").strip() or API_BASE,
    }


class _Fallback:
    def __init__(self, on_fallback: Callable[[str], None] | None) -> None:
        self._on_fallback = on_fallback or (lambda msg: None)
        self._warned = False
        self._lock = threading.Lock()

    def fell_back(self, err: SarvamError, what: str) -> None:
        log.warning("Sarvam %s failed, using offline %s: %s", what, what, err)
        with self._lock:
            if self._warned:
                return
            self._warned = True
        self._on_fallback(
            "I can't reach the online voice right now, so I'm using my offline voice."
            if err.offline
            else "The online voice returned an error, so I'm using my offline voice."
        )

    def recovered(self) -> None:
        self._warned = False


class SarvamTTS:
    """Bulbul voice with the offline voice as a safety net."""

    def __init__(
        self,
        client: SarvamClient,
        offline_tts,
        language: str = "en-IN",
        speaker: str = "",
        model: str = "bulbul:v3",
        on_fallback: Callable[[str], None] | None = None,
    ) -> None:
        self.client = client
        self.offline = offline_tts
        self.language = language
        self.speaker = speaker
        self.model = model
        self.rate = getattr(offline_tts, "rate", 1.0)
        self._fb = _Fallback(on_fallback)

    def set_rate(self, rate: float) -> None:
        self.rate = rate
        if hasattr(self.offline, "set_rate"):
            self.offline.set_rate(rate)

    def synth_to_array(self, text: str):
        if not text.strip() or looks_sensitive(text):  # secrets never leave the PC
            return self.offline.synth_to_array(text)
        try:
            out = self.client.tts(
                text, self.language, speaker=self.speaker, pace=self.rate, model=self.model
            )
            self._fb.recovered()
            return out
        except SarvamError as e:
            self._fb.fell_back(e, "voice")
            return self.offline.synth_to_array(text)


class SarvamSTT:
    """Saaras speech recognition with offline Whisper as the fallback."""

    def __init__(
        self,
        client: SarvamClient,
        offline_stt,
        model: str = "saaras:v3",
        on_fallback: Callable[[str], None] | None = None,
    ) -> None:
        self.client = client
        self.offline = offline_stt
        self.model = model
        self.last_language = ""
        self._fb = _Fallback(on_fallback)

    def transcribe(self, audio) -> str:
        try:
            text, lang = self.client.stt(float_to_wav(audio), mode="translate", model=self.model)
            self.last_language = lang
            self._fb.recovered()
            return text
        except SarvamError as e:
            self._fb.fell_back(e, "speech recognition")
            return self.offline.transcribe(audio)
