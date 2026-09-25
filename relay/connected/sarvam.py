"""Minimal Sarvam AI client (stdlib HTTP only) for RELAY's opt-in Connected mode.

Endpoints (https://docs.sarvam.ai):
  POST /speech-to-text        Saaras: mode=translate -> English transcript of Indian-
                              language speech (commands); mode=transcribe -> native
                              script (dictation). Detected language_code returned.
  POST /translate             Mayura / Sarvam-Translate: English <-> Indian languages.
  POST /text-to-speech        Bulbul: natural Indian-language voices (base64 WAV).
  POST /v1/chat/completions   Sarvam chat model, used only to map a free-form request
                              onto one of RELAY's fixed commands.
Auth is the ``api-subscription-key`` header. The key is never logged or spoken.
"""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request
import uuid
import wave

import numpy as np

from relay.diagnostics import get_logger

log = get_logger("connected.sarvam")

API_BASE = "https://api.sarvam.ai"


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
        sr = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise SarvamError(-1, f"unexpected sample width {width}")
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    return audio, sr


class SarvamClient:
    def __init__(self, api_key: str, base: str = API_BASE, timeout: float = 20.0,
                 opener=None) -> None:
        if not api_key:
            raise ValueError("Sarvam API key is required")
        self._key = api_key
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def __repr__(self) -> str:        # never leak the key into logs/tracebacks
        return f"SarvamClient(base={self.base!r})"

    # ---- transport ----
    def _request(self, path: str, body: bytes, content_type: str) -> dict:
        req = urllib.request.Request(
            self.base + path, data=body, method="POST",
            headers={"api-subscription-key": self._key, "Content-Type": content_type,
                     "Accept": "application/json", "User-Agent": "RELAY/0.2"})
        try:
            with self._open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            msg = ""
            try:
                err = json.loads(e.read().decode("utf-8") or "{}")
                msg = (err.get("error") or {}).get("message") or err.get("detail") or ""
            except Exception:
                pass
            raise SarvamError(e.code, str(msg or e.reason)[:200]) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SarvamError(0, f"network unavailable ({type(e).__name__})") from None

    def _post_json(self, path: str, payload: dict) -> dict:
        return self._request(path, json.dumps(payload).encode("utf-8"), "application/json")

    def _post_multipart(self, path: str, fields: dict, file_bytes: bytes,
                        filename: str = "audio.wav", mime: str = "audio/wav") -> dict:
        boundary = "----relay" + uuid.uuid4().hex
        out = io.BytesIO()
        for k, v in fields.items():
            out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                      f"{v}\r\n".encode())
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                  f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode())
        out.write(file_bytes)
        out.write(f"\r\n--{boundary}--\r\n".encode())
        return self._request(path, out.getvalue(), f"multipart/form-data; boundary={boundary}")

    # ---- APIs ----
    def stt(self, wav_bytes: bytes, mode: str = "translate", language_code: str = "unknown",
            model: str = "saaras:v3") -> tuple[str, str]:
        """Returns (transcript, detected_language_code)."""
        data = self._post_multipart("/speech-to-text", {
            "model": model, "mode": mode, "language_code": language_code}, wav_bytes)
        return (data.get("transcript") or "").strip(), data.get("language_code") or ""

    def translate(self, text: str, target: str, source: str = "auto",
                  model: str = "mayura:v1") -> str:
        text = text.strip()
        if not text or source == target:
            return text
        if model != "mayura:v1" and source == "auto":
            source = "en-IN"
        pieces = _chunks(text, 900)
        out = []
        for p in pieces:
            data = self._post_json("/translate", {
                "input": p, "source_language_code": source,
                "target_language_code": target, "model": model})
            out.append((data.get("translated_text") or "").strip())
        return " ".join(x for x in out if x)

    def tts(self, text: str, language_code: str, speaker: str = "", pace: float = 1.0,
            model: str = "bulbul:v3") -> tuple[np.ndarray, int]:
        # sample rate is left at the API default (22050 Hz); the real rate is read back
        # from the returned WAV header
        payload = {"text": text[:2400], "language_code": language_code, "model": model,
                   "pace": max(0.5, min(2.0, float(pace)))}
        if speaker:
            payload["speaker"] = speaker
        data = self._post_json("/text-to-speech", payload)
        audios = data.get("audios") or []
        if not audios:
            raise SarvamError(-1, "no audio returned")
        parts, sr = [], 22050
        for b64 in audios:
            a, sr = wav_to_float(base64.b64decode(b64))
            parts.append(a)
        return np.concatenate(parts).astype(np.float32), sr

    def chat(self, messages: list[dict], model: str = "sarvam-105b", max_tokens: int = 200,
             temperature: float = 0.0) -> str:
        data = self._post_json("/v1/chat/completions", {
            "model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "reasoning_effort": "low"})
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise SarvamError(-1, "unexpected chat response") from None
        return re.sub(r"(?s)<think>.*?</think>", "", content).strip()


def _chunks(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?।])\s+", text):
        while len(s) > limit:
            out.append(s[:limit])
            s = s[limit:]
        if len(cur) + len(s) + 1 > limit and cur:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out
