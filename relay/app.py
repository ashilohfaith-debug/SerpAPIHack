"""RelayApp — the assembled application: lifecycle, single-instance, real voice.

Wires the Session (with a real Piper voice), the live voice loop (mic + wake), the
emergency stop (which flushes speech), and the optional accessible panel. One
instance at a time. Clean startup and shutdown. This is what ``relay --start`` runs
on a quiet session; it is not started automatically during development because a live
listening loop acts on speech.
"""

from __future__ import annotations

import time

from relay.audio import SpeechQueue, make_tts
from relay.core import EventBus
from relay.core.single_instance import SingleInstance
from relay.diagnostics import get_logger, setup_logging
from relay.loop import VoiceLoop
from relay.memory.db import default_db_path
from relay.session import Session

log = get_logger("app")


class RelayApp:
    def __init__(self, panel: bool = False, wake_required: bool = True) -> None:
        self.panel = panel
        self.wake_required = wake_required
        self.instance = SingleInstance()
        self.bus = EventBus()
        self.tts = make_tts(prefer_piper=True)
        self.speech = SpeechQueue(self.tts)
        self.session = Session(speak=self.speech.say, bus=self.bus,
                               db_path=str(default_db_path()))
        # emergency stop flushes queued speech immediately
        self.session.emergency.register_flush(self.speech.interrupt)
        self.loop = VoiceLoop(self.session, speech=self.speech,
                              wake_required=wake_required)
        self.ipc = None
        if panel:
            from relay.ipc import IpcServer
            self.ipc = IpcServer(self.session, self.bus)

    def run(self) -> int:
        setup_logging("INFO")
        if not self.instance.acquire():
            print("RELAY is already running.")
            return 1
        try:
            self.session.onboard()   # spoken, voice-only
            if self.ipc is not None:
                print("panel:", self.ipc.start())
            mic = self.loop.run()
            print("RELAY is listening. Say 'Relay' then a command. Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nstopping…")
            finally:
                mic.stop()
        finally:
            self.speech.shutdown()
            if self.ipc is not None:
                self.ipc.stop()
            self.session.close()
            self.instance.release()
        return 0
