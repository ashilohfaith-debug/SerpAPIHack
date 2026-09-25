"""Opt-in Connected mode: Indian-language voice in/out and free-form understanding
through Sarvam AI. Off by default; enabled only with a spoken consent phrase."""

from .mode import LANG_NAMES, LANGS, ConnectedVoice, api_key
from .sarvam import SarvamClient, SarvamError

__all__ = ["ConnectedVoice", "LANGS", "LANG_NAMES", "SarvamClient", "SarvamError",
           "api_key"]
