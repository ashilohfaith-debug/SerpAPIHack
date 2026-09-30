"""End-to-end voice check without a human: real speech in, real narration out.

Synthesizes spoken commands with the offline Piper voice, slices them into 30 ms
microphone frames, and feeds them to the REAL voice loop: webrtcvad segmentation
(with pre-roll), faster-whisper STT, wake-word gating, the grammar, the Session and
its skills. RELAY's replies go through the real SpeechQueue with a silent player, so
the half-duplex rule (RELAY must not hear itself) is exercised too. Only read-only
commands are used — nothing on the desktop changes.

    uv run python scripts/e2e_voice.py
"""

from __future__ import annotations

import sys
import threading
import time

import numpy as np

from relay.audio import SpeechQueue, WhisperSTT, make_tts
from relay.audio.vad import FRAME_BYTES
from relay.loop import Dispatcher, VoiceLoop
from relay.session import Session

SR = 16000


def to_frames(audio: np.ndarray, sr: int, pad_s: float = 0.6) -> list[bytes]:
    if sr != SR:
        n = int(len(audio) * SR / sr)
        audio = np.interp(
            np.linspace(0, len(audio), n, endpoint=False), np.arange(len(audio)), audio
        )
    pad = np.zeros(int(SR * pad_s))
    pcm = (np.clip(np.concatenate([pad, audio, pad, pad]), -1, 1) * 32767).astype(np.int16)
    raw = pcm.tobytes()
    return [raw[i : i + FRAME_BYTES] for i in range(0, len(raw) - FRAME_BYTES, FRAME_BYTES)]


def main() -> int:
    tts = make_tts(prefer_piper=True)
    spoken: list[str] = []
    speaking_gate = threading.Event()
    speaking_gate.set()

    def silent_player(audio, sr, stop):
        # pretend to play for a realistic (shortened) duration
        stop.wait(min(0.4, len(audio) / sr / 4))

    speech = SpeechQueue(tts, player=silent_player)
    from relay.config import Config
    from relay.envfile import load_env
    from relay.llm import Assistant, Router, routes_from_config

    load_env()
    routes = routes_from_config(Config.load())  # AI answers too, if a router is set
    assistant = Assistant(Router(routes)) if routes else None
    s = Session(
        speak=lambda t: (spoken.append(t), speech.say(t)), db_path=":memory:", assistant=assistant
    )
    d = Dispatcher(s)
    loop = VoiceLoop(d.submit, stt=WhisperSTT(), speech=speech, wake_required=True, threaded=False)

    def feed(text: str, ptt: bool = False) -> list[str]:
        spoken.clear()
        if ptt:
            loop.push_to_talk()
            time.sleep(0.05)
        audio, sr = tts.synth_to_array(text)
        for f in to_frames(audio, sr):
            loop.on_frame(f)
        time.sleep(0.2)
        for _ in range(200):  # wait for the command to finish
            if not d.busy and not speech.is_speaking:
                break
            time.sleep(0.05)
        time.sleep(0.4)  # clear the half-duplex tail
        return list(spoken)

    cases = [
        ("Relay, what time is it?", False, "It's"),
        ("Relay, what is twenty five times four?", False, "is 100"),
        ("Relay, take a note, buy milk.", False, "Noted"),
        ("Relay, read my notes.", False, "milk"),  # "buy"/"by" sound alike to Whisper
        ("Relay, how much battery do I have?", False, "Battery"),
        ("What's the date today?", True, "Today is"),  # push-to-talk, no wake word
        ("Open notepad and type something.", False, None),  # NOT addressed: ignored
    ]
    if assistant is not None:  # not a built-in command: answered by the AI router
        cases.insert(-1, ("Relay, what is the capital of Japan?", False, "Tokyo"))
    ok_all = True
    try:
        for text, ptt, expect in cases:
            out = feed(text, ptt)
            if expect is None:
                ok = not out
                verdict = "ignored (correct)" if ok else f"WRONGLY acted: {out}"
            else:
                ok = any(expect.lower() in o.lower() for o in out)
                verdict = " | ".join(out) if out else "(nothing heard)"
            ok_all &= ok
            mode = "PTT " if ptt else ""
            print(f"[{'PASS' if ok else 'FAIL'}] {mode}{text!r}\n        -> {verdict}")

        # half-duplex: while RELAY is talking, even a wake-word command is not captured
        spoken.clear()
        speech.set_tts(tts)
        long_audio, sr = tts.synth_to_array("relay what time is it")

        def slow_player(audio, sr_, stop):
            stop.wait(3.0)

        speech._player = slow_player
        speech.say("I am speaking a long sentence right now.")
        time.sleep(0.3)
        for f in to_frames(long_audio, sr):
            loop.on_frame(f)
        time.sleep(0.5)
        heard_self = any(o.startswith("It's") for o in spoken)
        speech.interrupt()
        print(
            f"[{'PASS' if not heard_self else 'FAIL'}] half-duplex: mic ignored while "
            f"RELAY speaks ({'no command captured' if not heard_self else 'captured!'})"
        )
        ok_all &= not heard_self
    finally:
        d.stop()
        speech.shutdown()
        s.close()
    print("\nE2E voice check", "PASSED" if ok_all else "FAILED")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
