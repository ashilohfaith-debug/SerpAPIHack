"""Optional Sarvam AI voice (Bulbul) and speech recognition (Saaras), configured by
the developer in the .env file. Offline Piper/Whisper remain the fallback."""

from .client import SarvamClient, SarvamError, float_to_wav, wav_to_float
from .voice import SarvamSTT, SarvamTTS, settings

__all__ = [
    "SarvamClient",
    "SarvamError",
    "SarvamSTT",
    "SarvamTTS",
    "float_to_wav",
    "settings",
    "wav_to_float",
]
