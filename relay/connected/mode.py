"""Connected mode — Indian languages through Sarvam AI, strictly opt-in.

Essential mode stays fully offline and English. Connected mode lets a user speak and
listen in Hindi, Telugu, Tamil and other Indian languages:
  * speech in  -> Saaras STT (mode=translate) -> English command text, so the SAME
                  offline grammar and safety gate decide what happens; dictation uses
                  mode=transcribe so the user's own words are typed in their script;
  * speech out -> RELAY's English narration translated (Mayura) and spoken by Bulbul;
  * free-form requests the grammar can't parse are mapped by the Sarvam chat model
    onto ONE of RELAY's fixed commands, which is then re-parsed and gated as usual.
Privacy: turning it on requires an explicit spoken consent phrase; anything that
looks like a password/OTP is never sent (the offline voice speaks it instead); if the
network or API fails, RELAY says so once and falls back to the offline voice.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Callable

from relay.config import user_data_dir
from relay.connected.sarvam import SarvamClient, SarvamError, float_to_wav
from relay.diagnostics import get_logger
from relay.memory.store import looks_sensitive

log = get_logger("connected.mode")

LANGS = {
    "english": "en-IN", "hindi": "hi-IN", "telugu": "te-IN", "tamil": "ta-IN",
    "kannada": "kn-IN", "malayalam": "ml-IN", "marathi": "mr-IN", "gujarati": "gu-IN",
    "bengali": "bn-IN", "bangla": "bn-IN", "punjabi": "pa-IN", "odia": "od-IN",
    "oriya": "od-IN",
}
LANG_NAMES = {"en-IN": "English", "hi-IN": "Hindi", "te-IN": "Telugu", "ta-IN": "Tamil",
              "kn-IN": "Kannada", "ml-IN": "Malayalam", "mr-IN": "Marathi",
              "gu-IN": "Gujarati", "bn-IN": "Bengali", "pa-IN": "Punjabi", "od-IN": "Odia"}
TTS_LANGS = set(LANG_NAMES)          # Bulbul voices


def api_key() -> str:
    """SARVAM_API_KEY from the environment, else a one-line file in the RELAY data
    folder (``sarvam_key.txt``) — so a sighted helper can set it up once."""
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if key:
        return key
    try:
        return (user_data_dir() / "sarvam_key.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class _LRU(OrderedDict):
    def __init__(self, cap: int = 256) -> None:
        super().__init__()
        self.cap = cap

    def get_or(self, key, fn):
        if key in self:
            self.move_to_end(key)
            return self[key]
        val = fn()
        self[key] = val
        if len(self) > self.cap:
            self.popitem(last=False)
        return val


class ConnectedVoice:
    """Holds the client + language state and provides STT/TTS adapters with the
    same interfaces as the offline engines, so they can be swapped at runtime."""

    def __init__(self, client: SarvamClient, offline_stt, offline_tts,
                 on_offline: Callable[[str], None] | None = None,
                 tts_model: str = "bulbul:v3", speaker: str = "",
                 chat_model: str = "sarvam-105b") -> None:
        self.client = client
        self.offline_stt = offline_stt
        self.offline_tts = offline_tts
        self.on_offline = on_offline or (lambda msg: None)
        self.tts_model = tts_model
        self.speaker = speaker
        self.chat_model = chat_model
        self.output_language = "auto"     # "auto" = answer in the language the user spoke
        self.last_input_language = "en-IN"
        self.native_dictation = False      # dictation: keep the user's own words/script
        self._warned = False
        self._tr_cache = _LRU()
        self._lock = threading.Lock()

    # ---- language ----
    @property
    def speak_language(self) -> str:
        lang = self.output_language
        if lang == "auto":
            lang = self.last_input_language or "en-IN"
        return lang if lang in TTS_LANGS else "en-IN"

    def _offline(self, err: SarvamError) -> None:
        log.warning("connected mode fallback: %s", err)
        if not self._warned:
            self._warned = True
            self.on_offline("I can't reach Sarvam right now, so I'm using my offline "
                            "English voice." if err.offline else
                            f"Sarvam returned an error, so I'm using my offline voice. "
                            f"{err.message}")

    # ---- STT adapter ----
    def transcribe(self, audio) -> str:
        wav = float_to_wav(audio)
        mode = "transcribe" if self.native_dictation else "translate"
        try:
            text, lang = self.client.stt(wav, mode=mode)
            if lang:
                self.last_input_language = lang if lang in TTS_LANGS else "en-IN"
            self._warned = False
            return text
        except SarvamError as e:
            self._offline(e)
            return self.offline_stt.transcribe(audio)

    # ---- TTS adapter ----
    @property
    def rate(self) -> float:
        return getattr(self.offline_tts, "rate", 1.0)

    def set_rate(self, rate: float) -> None:
        if hasattr(self.offline_tts, "set_rate"):
            self.offline_tts.set_rate(rate)

    def translate_out(self, text: str) -> str:
        lang = self.speak_language
        if lang == "en-IN":
            return text
        return self._tr_cache.get_or((lang, text), lambda: self.client.translate(
            text, target=lang, source="auto"))

    def synth_to_array(self, text: str):
        if looks_sensitive(text):          # never send anything credential-like
            return self.offline_tts.synth_to_array(text)
        try:
            spoken = self.translate_out(text)
            audio, sr = self.client.tts(spoken, self.speak_language, speaker=self.speaker,
                                        pace=self.rate, model=self.tts_model)
            self._warned = False
            return audio, sr
        except SarvamError as e:
            self._offline(e)
            return self.offline_tts.synth_to_array(text)
