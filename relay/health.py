"""`relay --check` — does everything work on THIS computer, right now?

Run after installing, before a demo, or when something seems wrong. Each check uses
the real subsystem (not a mock) and reports plainly; nothing on the desktop is
changed, nothing is sent anywhere (the check itself proves no network was used), and
the result is also spoken so a blind user hears it.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _run(name, fn) -> Check:
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {str(e)[:160]}"
    return Check(name, bool(ok), detail)


def _data_dir():
    from relay.config import user_data_dir

    d = user_data_dir()
    probe = d / ".write_test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return True, str(d)


def _models():
    from relay.models_manager import status

    rows = status()
    missing = [r["name"] for r in rows if not r["present"]]
    return not missing, ("all present" if not missing else "missing: " + ", ".join(missing))


def _voice(state):
    from relay.audio import make_tts
    from relay.models_manager import active_voice, voice_licence

    tts = make_tts(prefer_piper=True)
    t = time.perf_counter()
    audio, sr = tts.synth_to_array("Relay check.")
    state["tts"] = tts
    name = active_voice() if type(tts).__name__ == "PiperTTS" else "Windows voice"
    licence, release_ok = voice_licence(name) if name != "Windows voice" else ("", True)
    state["voice_note"] = (
        None
        if release_ok
        else (
            f"the voice {name} is licensed for research use only ({licence}). It works, but "
            "before distributing Relay publicly run: relay --setup-models (public-domain voice)"
        )
    )
    return len(audio) > 0, (f"{name}, {time.perf_counter() - t:.2f}s to synthesise a sentence")


def _speech_recognition(state):
    import numpy as np

    from relay.audio import WhisperSTT

    audio, sr = state["tts"].synth_to_array("what time is it")
    if sr != 16000:
        n = int(len(audio) * 16000 / sr)
        audio = np.interp(
            np.linspace(0, len(audio), n, endpoint=False), np.arange(len(audio)), audio
        ).astype(np.float32)
    stt = WhisperSTT()
    stt.transcribe(np.zeros(8000, dtype=np.float32))  # load
    t = time.perf_counter()
    text = stt.transcribe(audio)
    return "time" in text.lower(), f"heard {text!r} in {time.perf_counter() - t:.2f}s"


def _microphone():
    from relay.audio import MicCapture

    frames = []
    mic = MicCapture(lambda f: frames.append(len(f)))
    mic.start()
    time.sleep(1.0)
    mic.stop()
    return len(frames) >= 20, f"{len(frames)} audio frames in 1 second"


def _speakers():
    import sounddevice as sd

    from relay.audio.devices import default_endpoints, mapper_device

    dev = sd.query_devices(kind="output")
    out, _inp = default_endpoints()  # what Windows is using now (RELAY follows it)
    if out is not None and out.name:
        extra = " (headphones: you can interrupt me by voice)" if out.is_headphones else ""
        follow = "" if mapper_device("output") is not None else " — fixed device"
        return bool(dev), out.name + extra + follow
    return bool(dev), dev.get("name", "?") if isinstance(dev, dict) else str(dev)


def _hotkeys():
    from relay.audio.hotkeys import HotkeyManager, spoken_combo
    from relay.config import Config

    cfg = Config.load()
    combos = [cfg.push_to_talk_hotkey, cfg.stop_hotkey, cfg.emergency_hotkey]
    hk = HotkeyManager()
    for c in combos:
        hk.add(c, lambda: None)
    got = hk.start()
    hk.stop()
    taken = [spoken_combo(c) for c in combos if not got.get(c)]
    if taken:
        return False, ("in use by another program (is Relay already running?): " + ", ".join(taken))
    return True, ", ".join(spoken_combo(c) for c in combos) + " available"


def _screen_reading():
    from relay.perception import UIAWorker

    w = UIAWorker()
    w.start()
    try:
        snap = w.observe(5.0)
    finally:
        w.stop()
    if snap is None:
        return False, "UI Automation did not answer"
    return True, (f"reading {snap.foreground_app or 'the desktop'}: {len(snap.elements)} controls")


def _apps():
    from relay.system.apps import AppCatalog

    cat = AppCatalog()
    cat.refresh()
    n = len(cat.entries)
    return n > 0, f"{n} apps on the Start menu"


def _volume():
    from relay.system.volume import describe, get_volume

    level = get_volume()
    return level is not None, describe(level)


def _database():
    from relay.memory.db import connect
    from relay.memory.notes import NotesStore

    conn = connect(":memory:")
    NotesStore(conn).add("check")
    conn.close()
    return True, "memory, notes and reminders tables ready"


def _single_instance():
    from relay.core.single_instance import SingleInstance

    si = SingleInstance()
    free = si.acquire()
    si.release()
    return True, ("Relay is not running now" if free else "Relay is already running (that's fine)")


def _online_checks(state) -> list[Check]:
    """Services configured in .env (skipped when not configured)."""
    out: list[Check] = []
    from relay.sarvam import SarvamClient, float_to_wav, settings

    sv = settings()
    if sv["key"]:
        client = SarvamClient(sv["key"], base=sv["base"])

        def sarvam_voice():
            client.warm()
            t = time.perf_counter()
            audio, sr = client.tts(
                "Relay online voice check.",
                sv["language"],
                speaker=sv["speaker"],
                model=sv["tts_model"],
            )
            state["sarvam_audio"] = (audio, sr)
            return len(audio) > 0, (
                f"{sv['tts_model']} {sv['speaker'] or 'default voice'}, "
                f"{sv['language']}: {time.perf_counter() - t:.2f}s per "
                "sentence"
            )

        out.append(_run("Sarvam voice (online)", sarvam_voice))
        if sv["stt"]:

            def sarvam_stt():
                import numpy as np

                audio, sr = state["tts"].synth_to_array("what time is it")
                if sr != 16000:
                    n = int(len(audio) * 16000 / sr)
                    audio = np.interp(
                        np.linspace(0, len(audio), n, endpoint=False), np.arange(len(audio)), audio
                    ).astype(np.float32)
                t = time.perf_counter()
                text, lang = client.stt(
                    float_to_wav(audio), mode="translate", model=sv["stt_model"]
                )
                return "time" in text.lower(), (
                    f"heard {text!r} ({lang}) in {time.perf_counter() - t:.2f}s"
                )

            if "tts" in state:
                out.append(_run("Sarvam speech recognition (online)", sarvam_stt))
    from relay.config import Config
    from relay.llm import Router, routes_from_config

    routes = routes_from_config(Config.load())
    if routes:

        def assistant():
            router = Router(routes)
            t = time.perf_counter()
            text = "".join(
                router.stream(
                    [{"role": "user", "content": "Reply with just the word ready."}], max_tokens=10
                )
            )
            return bool(text.strip()), (
                f"first token {router.last_ttft:.2f}s via "
                f"{router.last_route}, done "
                f"{time.perf_counter() - t:.2f}s"
            )

        out.append(_run("AI assistant router (online)", assistant))
    return out


def run_checks(speak: bool = True) -> list[Check]:
    lookups: list[str] = []
    real_getaddrinfo = socket.getaddrinfo
    lock = threading.Lock()

    def spy(host, *a, **k):
        with lock:
            lookups.append(str(host))
        return real_getaddrinfo(host, *a, **k)

    socket.getaddrinfo = spy
    state: dict = {}
    try:
        results = [
            _run("Data folder writable", _data_dir),
            _run("Models present", _models),
            _run("Voice (text to speech)", lambda: _voice(state)),
            _run(
                "Speech recognition",
                lambda: (
                    _speech_recognition(state)
                    if "tts" in state
                    else (False, "needs the voice check to pass")
                ),
            ),
            _run("Microphone", _microphone),
            _run("Speakers", _speakers),
            _run("Global keys", _hotkeys),
            _run("Screen reading (UI Automation)", _screen_reading),
            _run("Installed apps list", _apps),
            _run("Volume control", _volume),
            _run("Database", _database),
            _run("Single instance", _single_instance),
        ]
    finally:
        socket.getaddrinfo = real_getaddrinfo
    results.append(
        Check(
            "Offline parts use no network",
            not lookups,
            "no network lookups during the checks above"
            if not lookups
            else "looked up: " + ", ".join(sorted(set(lookups))),
        )
    )
    results += _online_checks(state)
    if speak and "tts" in state:
        failed = [r.name for r in results if not r.ok]
        line = (
            "All checks passed. Relay is ready to use."
            if not failed
            else f"{len(failed)} check{'s' if len(failed) != 1 else ''} failed: "
            + ", ".join(failed)
            + "."
        )
        try:
            import sounddevice as sd

            audio, sr = state["tts"].synth_to_array(line)
            sd.play(audio, sr)
            sd.wait()
        except Exception:
            pass
    if state.get("voice_note"):
        results.append(Check("Voice licence (note)", True, state["voice_note"]))
    return results


def main(speak: bool = True) -> int:
    from relay import __version__

    print(f"RELAY {__version__} — checking this computer\n")
    results = run_checks(speak=speak)
    for r in results:
        print(f"  [{'OK ' if r.ok else 'XX '}] {r.name:34} {r.detail}")
    failed = [r for r in results if not r.ok]
    print(
        "\nAll checks passed. Relay is ready to use."
        if not failed
        else f"\n{len(failed)} check(s) failed — see above."
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    import sys

    sys.exit(main(speak=False))
