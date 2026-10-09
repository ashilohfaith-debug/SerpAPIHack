"""Minimal Sarvam AI client (stdlib only) — the Bulbul voice and Saaras speech-to-text.

Endpoints (https://docs.sarvam.ai):
  POST /text-to-speech   Bulbul: natural Indian voices (returns base64 WAV).
  POST /speech-to-text   Saaras: transcribe (or translate to English) Indian speech.
Auth is the ``api-subscription-key`` header; the key comes from the .env file and is
never logged, spoken, or shown in ``repr``.

Latency: every spoken sentence is one request, so the client keeps ONE persistent
HTTPS connection (no TCP/TLS handshake per sentence) and can pre-open it (``warm``).
"""

from __future__ import annotations

import base64
import http.client
import io
import json
import threading
import uuid
import wave
from urllib.parse import urlparse

import numpy as np

API_BASE = "https://api.sarvam.ai"


def resolve_tts_model(speaker: str, model: str | None = None) -> str:
    """Keep saved legacy speakers on v3 unless a model is explicitly chosen."""
    if model and model.strip():
        return model.strip()
    return "bulbul:v4-flash" if "_" in speaker or not speaker else "bulbul:v3"


class SarvamError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Sarvam API {status}: {message}")
        self.status = status
        self.message = message

    @property
    def offline(self) -> bool:
        return self.status == 0


def float_to_wav(audio: np.ndarray, sr: int = 16000) -> bytes:
    pcm = (np.clip(np.asarray(audio, dtype=np.float32), -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def wav_to_float(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise SarvamError(-1, f"unexpected sample width {width}")
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    return audio, sr


class SarvamClient:
    def __init__(self, api_key: str, base: str = API_BASE, timeout: float = 15.0) -> None:
        if not api_key:
            raise ValueError("SARVAM_API_KEY is empty")
        self._key = api_key
        u = urlparse(base)
        self._https = u.scheme == "https"
        self._host = u.hostname or "api.sarvam.ai"
        self._port = u.port or (443 if self._https else 80)
        self._prefix = u.path.rstrip("/")  # e.g. a gateway at https://host/sarvam
        self.timeout = timeout
        self._conn: http.client.HTTPConnection | None = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:  # never leak the key into logs/tracebacks
        return f"SarvamClient(host={self._host!r})"

    # ---- transport (one kept-alive connection) ----
    def _connection(self) -> http.client.HTTPConnection:
        if self._conn is None:
            cls = http.client.HTTPSConnection if self._https else http.client.HTTPConnection
            self._conn = cls(self._host, self._port, timeout=self.timeout)
        return self._conn

    def _drop(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def warm(self) -> None:
        """Open the connection (DNS + TCP + TLS) before the first sentence needs it."""
        with self._lock:
            try:
                c = self._connection()
                c.request("GET", self._prefix + "/", headers={"User-Agent": "RELAY/0.3"})
                c.getresponse().read()
            except Exception:
                self._drop()

    def _request(self, path: str, body: bytes, content_type: str) -> dict:
        headers = {
            "api-subscription-key": self._key,
            "Content-Type": content_type,
            "Accept": "application/json",
            "User-Agent": "RELAY/0.3",
        }
        with self._lock:
            for attempt in (0, 1):  # one retry if a kept-alive socket went stale
                try:
                    c = self._connection()
                    c.request("POST", self._prefix + path, body=body, headers=headers)
                    resp = c.getresponse()
                    data = resp.read()
                    break
                except (
                    http.client.RemoteDisconnected,
                    ConnectionResetError,
                    BrokenPipeError,
                    http.client.CannotSendRequest,
                ):
                    self._drop()
                    if attempt:
                        raise SarvamError(0, "connection lost") from None
                except (OSError, http.client.HTTPException) as e:
                    self._drop()
                    raise SarvamError(0, f"network unavailable ({type(e).__name__})") from None
        if resp.status != 200:
            msg = ""
            try:
                err = json.loads(data.decode("utf-8") or "{}")
                msg = (err.get("error") or {}).get("message") or err.get("detail") or ""
            except Exception:
                pass
            raise SarvamError(resp.status, str(msg or resp.reason)[:200])
        try:
            return json.loads(data.decode("utf-8") or "{}")
        except ValueError:
            raise SarvamError(-1, "unexpected response") from None

    # ---- APIs ----
    def tts(
        self,
        text: str,
        language_code: str = "en-IN",
        speaker: str = "aparna_en_companion",
        pace: float = 1.0,
        model: str | None = None,
    ) -> tuple[np.ndarray, int]:
        payload = {
            "text": text[:2400],
            "language_code": language_code,
            "model": resolve_tts_model(speaker, model),
            "pace": max(0.5, min(2.0, float(pace))),
        }
        if speaker:
            payload["speaker"] = speaker
        data = self._request(
            "/text-to-speech", json.dumps(payload).encode("utf-8"), "application/json"
        )
        audios = data.get("audios") or []
        if not audios:
            raise SarvamError(-1, "no audio returned")
        parts, sr = [], 22050
        for b64 in audios:
            a, sr = wav_to_float(base64.b64decode(b64))
            parts.append(a)
        return np.concatenate(parts).astype(np.float32), sr

    def stt(
        self,
        wav_bytes: bytes,
        mode: str = "transcribe",
        language_code: str = "unknown",
        model: str = "saaras:v4",
    ) -> tuple[str, str]:
        """Returns (transcript, detected_language_code)."""
        boundary = "----relay" + uuid.uuid4().hex
        out = io.BytesIO()
        for k, v in {"model": model, "mode": mode, "language_code": language_code}.items():
            out.write(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'
                f"{v}\r\n".encode()
            )
        out.write(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
        )
        out.write(wav_bytes)
        out.write(f"\r\n--{boundary}--\r\n".encode())
        data = self._request(
            "/speech-to-text", out.getvalue(), f"multipart/form-data; boundary={boundary}"
        )
        return (data.get("transcript") or "").strip(), data.get("language_code") or ""
