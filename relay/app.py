"""RelayApp — the assembled application a blind user actually runs.

Wires the Session (offline Piper voice), the live
voice loop (talk key + wake word, half-duplex), system-wide hotkeys, earcons, the
reminder scheduler, the emergency stop (which flushes speech), and the optional
accessible panel. One instance at a time; a second launch says "Relay is already
running" out loud and exits. Every problem a blind user needs to know about at
startup (no microphone, a hotkey taken by another program) is SPOKEN, not printed.
"""

from __future__ import annotations

import threading
import time

from relay.audio import SpeechQueue, WhisperSTT, make_tts
from relay.audio.earcons import earcon
from relay.audio.hotkeys import HotkeyManager, spoken_combo
from relay.config import Config
from relay.core import EventBus
from relay.core.single_instance import SingleInstance
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
                               assistant=self.assistant)
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
                              open_mic=lambda: self.session.dictation)
        if self.sarvam_stt is not None:
            self.loop.wake_stt = self.stt   # wake word checked on this PC before any upload
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

    # ---- lifecycle ----
    def _startup_checks(self) -> list[str]:
        problems = []
        registered = self.hotkeys.start()
        talk = self.cfg.push_to_talk_hotkey
        if not registered.get(talk, False):
            problems.append(f"Another program is using {spoken_combo(talk)}, so the talk key "
                            "won't work. You can still say Relay to get my attention.")
        try:
            self.loop.run()
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
            for cloud in (self.sarvam, self.sarvam_stt):
                if cloud is not None:
                    threading.Thread(target=cloud.client.warm, daemon=True).start()
            self.apps.start()
            problems = self._startup_checks()
            self.session.onboard()
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
        for fn in (self.loop.stop, self.hotkeys.stop, self.dispatcher.stop,
                   self.speech.shutdown):
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
