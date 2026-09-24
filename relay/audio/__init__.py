"""Offline voice I/O: STT (faster-whisper), TTS (Piper + SAPI), VAD (webrtcvad),
wake word + control commands, mic capture, and a speech queue with barge-in."""

from .capture import MicCapture, list_devices
from .speech import SpeechQueue
from .stt import SAMPLE_RATE, WhisperSTT
from .tts import PiperTTS, SapiTTS, make_tts
from .vad import VAD, SpeechSegmenter
from .wake import Command, detect_wake, match_command

__all__ = [
    "SAMPLE_RATE", "WhisperSTT",
    "PiperTTS", "SapiTTS", "make_tts",
    "VAD", "SpeechSegmenter",
    "SpeechQueue",
    "Command", "detect_wake", "match_command",
    "MicCapture", "list_devices",
]
