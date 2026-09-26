"""RelayApp — the assembled application a blind user actually runs.

Wires the Session (offline Piper voice), the live
voice loop (talk key + wake word, half-duplex), system-wide hotkeys, earcons, the
reminder scheduler, the emergency stop (which flushes speech), and the optional
accessible panel. One instance at a time; a second launch says "Relay is already
running" out loud and exits. Every problem a blind user needs to know about at
startup (no microphone, a hotkey taken by another program) is SPOKEN, not printed.
"""

from __future__ import annotations

import os
import threading
import time

from relay.audio import SpeechQueue, WhisperSTT, make_tts
from relay.audio.devices import (
    DeviceWatch,
    default_endpoints,
    device_name,
    laptop_mic,
    mic_device_for,
    same,
    spoken_name,
    use_windows_defaults,
)
from relay.audio.earcons import earcon
from relay.audio.hotkeys import HotkeyManager, spoken_combo
from relay.config import Config
from relay.core import EventBus
from relay.core.single_instance import QuitSignal, SingleInstance
from relay.diagnostics import get_logger, setup_logging
from relay.loop import Dispatcher, VoiceLoop
from relay.memory.db import default_db_path
from relay.narration import policy as pol
from relay.session import Session
from relay.system.apps import AppCatalog

log = get_logger("app")


class _PanelBridge:
    """Panel commands join the same ordered queue as voice commands."""

    def __init__(self, dispatcher, session) -> None:
        self._d, self._s = dispatcher, session

    def handle(self, text: str):
        self._d.submit(text)
        return []

    def onboard(self) -> None:
        self._s.onboard()


def speak_once(text: str) -> None:
    """Say one thing without the full app (used when another instance is running)."""
    try:
        import sounddevice as sd
        tts = make_tts(prefer_piper=True)
        audio, sr = tts.synth_to_array(text)
        sd.play(audio, sr)
        sd.wait()
    except Exception:
        try:
            from relay.audio import SapiTTS
            SapiTTS().speak_blocking(text)
        except Exception:
            print(text)


class RelayApp:
    def __init__(self, panel: bool = False, wake_required: bool | None = None,
                 config: Config | None = None) -> None:
        self.cfg = config or Config.load()
        self.panel = panel
        self.instance = SingleInstance()
        self.bus = EventBus()
        self._quit = threading.Event()
        use_windows_defaults()          # follow the default device: headphones just work
        self.devices = DeviceWatch(self._on_audio_change)
        self.quit_signal = QuitSignal()
        self._announce_timer: threading.Timer | None = None
        self._paused_for_privacy = ""
        self._announced_out = None
        self.tts = make_tts(prefer_piper=True)            # offline voice, always present
        self.speech = SpeechQueue(self.tts)
        self.apps = AppCatalog()
        self.stt = WhisperSTT()                             # offline recogniser
        # Sarvam voice / recognition from the .env file (offline engines as fallback)
        self.sarvam = None
        self.sarvam_stt = None
        from relay.sarvam import SarvamClient, SarvamSTT, SarvamTTS, settings
        sv = settings()
        if sv["key"]:
            self.sarvam = SarvamTTS(SarvamClient(sv["key"], base=sv["base"]), self.tts,
                                    language=sv["language"], speaker=sv["speaker"],
                                    model=sv["tts_model"], on_fallback=self._cloud_fallback)
            self.speech.set_tts(self.sarvam)
            if sv["stt"]:
                self.sarvam_stt = SarvamSTT(SarvamClient(sv["key"], base=sv["base"]), self.stt,
                                            model=sv["stt_model"],
                                            on_fallback=self._cloud_fallback)
        from relay.llm import Assistant, Router, routes_from_config
        routes = routes_from_config(self.cfg)
        self.router = Router(routes) if routes else None
        self.assistant = Assistant(self.router) if self.router else None
        self.session = Session(speak=self.speech.say, bus=self.bus,
                               db_path=str(default_db_path()), speech=self.speech,
                               apps=self.apps, on_quit=self.request_quit,
                               on_wake_word=self._set_wake,
                               talk_key=self.cfg.push_to_talk_hotkey,
                               assistant=self.assistant, audio=self)
        # emergency stop flushes queued speech immediately
        self.session.emergency.register_flush(self.speech.interrupt)
        self.dispatcher = Dispatcher(self.session)
        wake = wake_required
        if wake is None:
            pref = self.session.store.get_pref("wake_word_enabled", default="")
            wake = self.cfg.wake_word_enabled if pref == "" else pref == "1"
        self.loop = VoiceLoop(self.dispatcher.submit, stt=self.sarvam_stt or self.stt,
                              speech=self.speech,
                              wake_required=wake, bus=self.bus, play_earcon=self.earcon,
                              say=lambda t: self.session.say(t, pol.Priority.REQUESTED),
                              open_mic=lambda: self.session.dictation,
                              interrupt=self.session.stop_speaking)
        if self.sarvam_stt is not None:
            self.loop.wake_stt = self.stt   # wake word checked on this PC before any upload
        # the on-screen palette: status light, "You: …" / "Relay: …", On/Off, Talk, ✕
        self._voice_state = "idle"
        self.palette = None
        if (os.environ.get("RELAY_PALETTE", "1") != "0"
                and self.session.store.get_pref("palette", default="1") == "1"):
            from relay.ui.palette import Palette
            self.palette = Palette(status=self._palette_status,
                                   on_toggle=lambda: self._palette_say(
                                       self.set_listening(not self.loop.enabled)),
                                   on_talk=self.loop.push_to_talk,
                                   on_quit=self._quit_requested)
        self.bus.subscribe("voice.state",
                           lambda e: setattr(self, "_voice_state", e.data.get("to", "idle")))
        self.bus.subscribe("voice.heard", lambda e: self.palette and self.palette.heard(
            e.data.get("text", "")))
        self.bus.subscribe("narration.say", lambda e: self.palette and self.palette.said(
            e.data.get("text", "")))
        self.hotkeys = HotkeyManager()
        self.hotkeys.add(self.cfg.push_to_talk_hotkey, self.loop.push_to_talk)
        self.hotkeys.add(self.cfg.stop_hotkey, self.session.stop_speaking)
        self.hotkeys.add(self.cfg.emergency_hotkey, self.session.emergency_stop)
        self.ipc = None
        if panel:
            from relay.ipc import IpcServer
            self.ipc = IpcServer(_PanelBridge(self.dispatcher, self.session), self.bus)

    # ---- callbacks ----
    def earcon(self, name: str) -> None:
        audio, sr = earcon(name)
        self.speech.play(audio, sr)

    def request_quit(self) -> None:
        self._quit.set()

    def _cloud_fallback(self, message: str) -> None:
        try:
            self.session.say(message, pol.Priority.CRITICAL)
        except AttributeError:          # during start-up, before the session exists
            pass

    def _set_wake(self, on: bool) -> None:
        self.loop.wake_enabled = on

    def _tune_routes_if_needed(self) -> None:
        """No fresh ranking of the router's models yet: time them in the background and
        switch to the fastest when done (the first questions use auto:fast meanwhile)."""
        routes = self.router.routes
        if not routes or self.cfg.llm_models not in (["auto:fast", "auto"], None, []):
            return
        from relay.llm import routes_from_config
        from relay.llm.tune import needs_tuning, tune_in_background
        url, key = routes[0].base_url, routes[0].api_key
        if needs_tuning(url):
            tune_in_background(url, key, on_done=lambda _r: self.router.replace_routes(
                routes_from_config(self.cfg)))

    # ---- on-screen palette and listening on/off ----
    def _palette_status(self) -> str:
        if not self.loop.enabled and not self.loop._armed:
            return "off"
        if self.speech.is_speaking:
            return "speaking"
        if self._voice_state == "transcribing":
            return "hearing"
        if self.loop._armed:
            return "listening"
        if self.dispatcher.busy:
            return "working"
        return "ready"

    def _palette_say(self, text: str) -> None:
        self.session.say(text, pol.Priority.REQUESTED)

    def set_listening(self, on: bool) -> str:
        """Listening on/off (palette switch, "stop listening"). Off: the microphone is
        ignored except right after the talk key."""
        self.loop.enabled = on
        key = spoken_combo(self.cfg.push_to_talk_hotkey)
        return ("I'm listening again. Say Relay, or press " + key + "." if on else
                "Okay, I've stopped listening. Press " + key + " when you need me, and say "
                "start listening to turn me back on.")

    def set_palette(self, visible: bool) -> str:
        self.session.store.set_pref("palette", "1" if visible else "0")
        if self.palette is None and visible:
            from relay.ui.palette import Palette
            self.palette = Palette(status=self._palette_status,
                                   on_toggle=lambda: self._palette_say(
                                       self.set_listening(not self.loop.enabled)),
                                   on_talk=self.loop.push_to_talk,
                                   on_quit=self._quit_requested)
            self.palette.start()
        elif self.palette is not None:
            self.palette.show(visible)
        return "The palette is showing at the top of the screen." if visible else \
            "The palette is hidden. Say show the palette to bring it back."

    def _quit_requested(self) -> None:
        """The launch key (Ctrl+Alt+R) pressed while RELAY runs: close, like 'quit Relay'."""
        self.session.stop_speaking()
        self.session.say("Closing Relay. Goodbye.", pol.Priority.CRITICAL)
        self.request_quit()

    # ---- headphones and audio devices ----
    def _marks(self) -> dict:
        """What the user told us per device: {endpoint id: True (headphones) / False}."""
        import json
        try:
            marks = json.loads(self.session.store.get_pref("headphone_devices", default="{}"))
            return marks if isinstance(marks, dict) else {}
        except ValueError:
            return {}

    def _is_headphones(self, ep) -> bool:
        if ep is None:                     # devices unknown: the user's general choice
            return self.session.store.get_pref("headphone_mode", default="auto") == "on"
        marks = self._marks()
        return bool(marks[ep.id]) if ep.id in marks else ep.is_headphones

    def _apply_headphone_mode(self) -> None:
        self.loop.headphones = self._is_headphones(self.devices.output)

    def set_headphone_mode(self, mode: str) -> str:
        """'on' | 'off' | 'auto' for the device in use now, remembered for that device
        ("I'm using headphones" once for USB-C earphones Windows calls speakers; the
        laptop's own speakers are not affected). Returns what to say."""
        import json
        mode = mode if mode in ("on", "off", "auto") else "auto"
        out = self.devices.output
        if out is None:
            self.session.store.set_pref("headphone_mode", mode)
            name = "the sound device"
        else:
            marks = self._marks()
            if mode == "auto":
                marks.pop(out.id, None)
            else:
                marks[out.id] = mode == "on"
            self.session.store.set_pref("headphone_devices", json.dumps(marks))
            name = spoken_name(out.name) or "this device"
        self._apply_headphone_mode()
        if mode == "on":
            return (f"Headphone mode on for {name}, and I'll remember it. I'll keep listening "
                    "while I talk, so you can interrupt me just by speaking.")
        if mode == "off":
            return (f"Headphone mode off for {name}. While I'm talking I won't listen; press "
                    f"{spoken_combo(self.cfg.push_to_talk_hotkey)} to interrupt me.")
        return (f"Okay, for {name} I'll go by what Windows says. Headphone mode is "
                + ("on." if self.loop.headphones else "off."))

    def describe_audio(self) -> str:
        """Where RELAY's voice goes and where it listens ("where is the sound going")."""
        out, inp = self.devices.output, self.devices.input
        if out is None and inp is None:
            out, inp = default_endpoints()
        said = (f"I'm speaking through {spoken_name(out.name)}" if out and out.name
                else "I'm speaking through the default speakers")
        if inp is not None and inp.is_hands_free and laptop_mic() is not None:
            said += (", and listening through the laptop's own microphone, so your headset "
                     "keeps its full sound quality")
        elif inp is not None and inp.name:
            said += f", and listening through {spoken_name(inp.name)}"
        told = out is not None and out.id in self._marks()
        return (said + f". Headphone mode is {'on' if self.loop.headphones else 'off'}"
                + (", as you told me for this device." if told else "."))

    def _on_audio_change(self, old_out, new_out, old_in, new_in) -> None:
        """Windows' default device changed: headphones plugged in or out, a headset's
        microphone, a TV over HDMI…"""
        if not same(old_in, new_in):
            try:
                self.loop.restart_mic(mic_device_for(new_in))
            except Exception as e:
                log.warning("could not reopen the microphone: %s", e)
        if same(old_out, new_out):
            return
        self._apply_headphone_mode()
        if (old_out is not None and self._is_headphones(old_out)
                and not (new_out is not None and self._is_headphones(new_out))):
            # headphones removed: never carry on reading private text out loud
            reading = self.session.reader.reading
            if reading or self.speech.is_speaking:
                self.session.stop_speaking()
                self._paused_for_privacy = "reading" if reading else "talking"
        # one announcement after things settle (a Bluetooth headset can switch twice)
        if self._announce_timer is not None:
            self._announce_timer.cancel()
        self._announce_timer = threading.Timer(1.0, self._announce_audio)
        self._announce_timer.daemon = True
        self._announce_timer.start()

    @staticmethod
    def _guess_line(out) -> str:
        return (f"{device_name(out.name) or 'This device'} has its own microphone, so I think "
                "it's headphones or earphones: you can interrupt me just by talking. If it's "
                "a speaker, say headphone mode off.")

    def _announce_audio(self) -> None:
        out, before = self.devices.output, self._announced_out
        paused, self._paused_for_privacy = self._paused_for_privacy, ""
        self._announced_out = out
        name = spoken_name(out.name) if out is not None else ""
        if out is not None and self._is_headphones(out):
            if out.guessed and out.id not in self._marks():
                line = self._guess_line(out)
            else:
                line = f"{name or 'Headphones'} connected."
            if self.loop.headphones and not (out.guessed and out.id not in self._marks()):
                line += " You can interrupt me just by talking."
            if paused == "reading":
                line += " I paused the reading; say continue to carry on."
        elif paused:
            line = ("Headphones disconnected, so I've paused. Say continue to carry on."
                    if paused == "reading" else
                    "Headphones disconnected, so I stopped talking.")
        elif before is not None and self._is_headphones(before):
            line = f"Headphones disconnected. I'll talk through the {name or 'speakers'}."
        elif out is not None and not same(before, out):
            line = f"Now speaking through {name or 'a different device'}."
        else:
            return
        self.session.say(line, pol.Priority.CRITICAL)

    # ---- lifecycle ----
    def _startup_checks(self) -> list[str]:
        problems = []
        registered = self.hotkeys.start()
        talk = self.cfg.push_to_talk_hotkey
        if not registered.get(talk, False):
            problems.append(f"Another program is using {spoken_combo(talk)}, so the talk key "
                            "won't work. You can still say Relay to get my attention.")
        try:
            self.loop.run(device=mic_device_for(self.devices.input))
        except Exception as e:
            log.error("microphone failed: %s", e)
            problems.append("I can't use the microphone. Please check that one is connected "
                            "and allowed in Windows privacy settings. You can still use my "
                            "panel, and I'll keep speaking.")
        return problems

    def _warm_up(self) -> None:
        """Load the speech model in the background so the first command is quick."""
        try:
            import numpy as np
            self.stt.transcribe(np.zeros(8000, dtype=np.float32))
        except Exception as e:
            log.warning("STT warm-up failed: %s", e)

    def run(self) -> int:
        setup_logging("INFO")
        if not self.instance.acquire():
            speak_once("Relay is already running. Press "
                       f"{spoken_combo(self.cfg.push_to_talk_hotkey)} to talk to it.")
            return 1
        try:
            threading.Thread(target=self._warm_up, name="stt-warmup", daemon=True).start()
            if self.router is not None:
                self.router.warm()              # DNS + TCP + TLS before the first question
                self._tune_routes_if_needed()   # find the fastest models (cached for days)
            for cloud in (self.sarvam, self.sarvam_stt):
                if cloud is not None:
                    threading.Thread(target=cloud.client.warm, daemon=True).start()
            self.apps.start()
            self.devices.start()                   # which speaker / mic / headphones now
            self._announced_out = self.devices.output
            self._apply_headphone_mode()
            self.quit_signal.listen(self._quit_requested)   # Ctrl+Alt+R again = close
            if self.palette is not None:
                self.palette.start()                        # the bar at the top
            problems = self._startup_checks()
            self.session.onboard()
            if self.loop.headphones:
                out = self.devices.output
                self.session.say(self._guess_line(out) if out is not None and out.guessed
                                 and out.id not in self._marks() else
                                 "You're on headphones, so you can interrupt me just by "
                                 "talking.", pol.Priority.REQUESTED)
            for p in problems:
                self.session.say(p, pol.Priority.CRITICAL)
            self.session.reminders.check_now()     # announce any missed while closed
            self.session.reminders.start()
            if self.ipc is not None:
                print("panel:", self.ipc.start())
            print(f"RELAY is running. Talk key: {self.cfg.push_to_talk_hotkey}. "
                  "Say 'quit relay' or press Ctrl+C here to stop.")
            try:
                while not self._quit.wait(0.5):
                    pass
            except KeyboardInterrupt:
                print("\nstopping…")
            self.speech.wait_idle(6.0)             # let "Goodbye" finish
        finally:
            self.shutdown()
        return 0

    def shutdown(self) -> None:
        if self._announce_timer is not None:
            self._announce_timer.cancel()
        if self.palette is not None:
            self.palette.stop()
        for fn in (self.devices.stop, self.quit_signal.stop, self.loop.stop, self.hotkeys.stop,
                   self.dispatcher.stop, self.speech.shutdown):
            try:
                fn()
            except Exception:
                pass
        if self.ipc is not None:
            try:
                self.ipc.stop()
            except Exception:
                pass
        self.session.close()
        self.instance.release()
        time.sleep(0.1)
