"""Headphones, audio-device changes, voice barge-in, and closing RELAY by keyboard."""

from __future__ import annotations

import threading
import time
import uuid
from types import SimpleNamespace

import numpy as np

from relay.audio import devices as dv
from relay.audio.devices import DeviceWatch, Endpoint, spoken_name

SPEAKERS = Endpoint("spk", "Speakers (Realtek(R) Audio)", 1)
BOAT = Endpoint("bt-a2dp", "Headphones (boAt Rockerz 450 Stereo)", 3)
BOAT_HF = Endpoint("bt-hfp", "Headset (boAt Rockerz 450 Hands-Free AG Audio)", 5)
LAPTOP_MIC = Endpoint("mic", "Microphone Array (Realtek(R) Audio)", 4)


# ---------------------------------------------------------------- devices
def test_headphones_are_recognised():
    assert BOAT.is_headphones and BOAT_HF.is_headphones and not SPEAKERS.is_headphones
    assert Endpoint("x", "Speakers (Galaxy Buds2)", 1).is_headphones      # by name
    assert Endpoint("x", "Headphones (Realtek(R) Audio)", -1).is_headphones
    assert BOAT_HF.is_hands_free and not BOAT.is_hands_free and not LAPTOP_MIC.is_hands_free


def test_device_names_are_speakable():
    assert spoken_name(BOAT.name) == "boAt Rockerz 450 headphones"
    assert spoken_name(SPEAKERS.name) == "Realtek Audio speakers"
    assert spoken_name(BOAT_HF.name) == "boAt Rockerz 450 headset"
    assert spoken_name("Line Out") == "Line Out" and spoken_name("") == ""


def test_watch_reports_only_real_changes():
    states = [(SPEAKERS, LAPTOP_MIC), (SPEAKERS, LAPTOP_MIC), (BOAT, LAPTOP_MIC),
              (None, None), (SPEAKERS, LAPTOP_MIC)]
    probe = iter(states).__next__
    got = []
    w = DeviceWatch(lambda *a: got.append(a))
    w.prime(probe)
    assert w.check() is False                            # same devices
    assert w.check() is True and got[-1] == (SPEAKERS, BOAT, LAPTOP_MIC, LAPTOP_MIC)
    assert w.check() is False and w.output == BOAT       # a Core Audio hiccup is ignored
    assert w.check() is True and got[-1][:2] == (BOAT, SPEAKERS)


def test_hands_free_mic_is_avoided(monkeypatch):
    monkeypatch.setattr(dv, "laptop_mic", lambda: 1)
    monkeypatch.setattr(dv, "mapper_device", lambda kind: 0)
    assert dv.mic_device_for(BOAT_HF) == 1               # keep the headphones in stereo
    assert dv.mic_device_for(LAPTOP_MIC) == 0            # otherwise follow Windows
    monkeypatch.setattr(dv, "laptop_mic", lambda: None)
    assert dv.mic_device_for(BOAT_HF) == 0               # no other mic: use the headset


def test_real_windows_devices_can_be_read():
    out, inp = dv.default_endpoints()
    if out is None:
        return                                           # no Core Audio (e.g. CI)
    assert out.id and isinstance(out.is_headphones, bool)
    assert dv.mapper_device("output") is not None        # the Sound Mapper exists


# ---------------------------------------------------------------- voice barge-in
class FakeSpeech:
    def __init__(self, speaking=True):
        self.is_speaking = speaking
        self.last_active = time.monotonic() if speaking else 0.0


class Words:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def transcribe(self, audio):
        self.calls += 1
        return self.text


def _loop(headphones=True, speaking=True, stt=None):
    from relay.loop import VoiceLoop
    dispatched, interrupts = [], []
    loop = VoiceLoop(dispatched.append, stt=stt or Words(""), speech=FakeSpeech(speaking),
                     wake_required=True, threaded=False,
                     interrupt=lambda: interrupts.append(1))
    loop.headphones = headphones
    return loop, dispatched, interrupts


def test_on_headphones_a_plain_stop_interrupts_relay():
    loop, dispatched, _ = _loop()
    loop.on_transcript("Stop.")
    assert dispatched == ["Stop."]


def test_on_headphones_a_command_over_relays_voice_interrupts_it_first():
    loop, dispatched, interrupts = _loop()
    loop.on_transcript("Relay, what time is it?")
    assert interrupts == [1] and dispatched == ["what time is it?"]
    loop.on_transcript("Relay")                          # bare wake word: stop and listen
    assert interrupts == [1, 1] and loop._armed


def test_room_talk_is_still_ignored_on_headphones():
    loop, dispatched, interrupts = _loop()
    loop.on_transcript("so what are we having for dinner")
    assert dispatched == [] and interrupts == []
    quiet, dispatched2, _ = _loop(speaking=False)
    quiet.on_transcript("stop")                          # nothing to interrupt: ignored
    assert dispatched2 == []


def test_on_speakers_relay_never_listens_to_itself():
    loop, dispatched, _ = _loop(headphones=False)
    loop.on_transcript("Stop.")
    assert dispatched == []


def test_headphones_keep_the_microphone_open_while_relay_talks():
    from tests.test_daily import ScriptSeg
    stt = Words("stop")
    loop, dispatched, _ = _loop(stt=stt)
    loop._seg_factory = lambda: ScriptSeg([True] * 20 + [False])
    loop._custom_seg = True
    loop._reset()
    loud = (6000 * np.sin(np.linspace(0, 300, 480))).astype(np.int16).tobytes()
    for _ in range(21):
        loop.on_frame(loud)
    assert stt.calls == 1 and dispatched == ["stop"]
    speakers, dispatched2, _ = _loop(headphones=False, stt=Words("stop"))
    speakers._seg_factory, speakers._custom_seg = loop._seg_factory, True
    speakers._reset()
    for _ in range(21):
        speakers.on_frame(loud)
    assert dispatched2 == [] and speakers.stt.calls == 0


def test_stop_over_relay_is_handled_locally_with_online_recognition():
    cloud = Words("never used")
    loop, dispatched, _ = _loop(stt=cloud)
    loop.wake_stt = Words("stop")
    loop.on_utterance((8000 * np.ones(16000)).astype(np.int16).tobytes())
    assert dispatched == ["stop"] and cloud.calls == 0


def test_talk_key_also_cancels_a_streaming_answer():
    loop, _, interrupts = _loop()
    loop.push_to_talk()
    assert interrupts == [1]                             # the session's full stop


def test_microphone_reopens_on_a_new_device(monkeypatch):
    import relay.audio
    opened = []

    class FakeMic:
        def __init__(self, cb, device=None):
            self.device = device

        def start(self):
            opened.append(self.device)

        def stop(self):
            opened.append("stopped")

    monkeypatch.setattr(relay.audio, "MicCapture", FakeMic)
    loop, _, _ = _loop()
    loop.run(device=0)
    loop.restart_mic(7)
    assert opened == [0, "stopped", 7]


# ---------------------------------------------------------------- the app's reactions
class _Store:
    def __init__(self):
        self.prefs = {}

    def get_pref(self, k, default=""):
        return self.prefs.get(k, default)

    def set_pref(self, k, v):
        self.prefs[k] = v


def _app(out=SPEAKERS, reading=False, speaking=False):
    from relay.app import RelayApp

    class App:
        _on_audio_change = RelayApp._on_audio_change
        _announce_audio = RelayApp._announce_audio
        _apply_headphone_mode = RelayApp._apply_headphone_mode
        _marks = RelayApp._marks
        _is_headphones = RelayApp._is_headphones
        _guess_line = RelayApp.__dict__["_guess_line"]
        set_headphone_mode = RelayApp.set_headphone_mode
        describe_audio = RelayApp.describe_audio

    app = App()
    said, stops, mics = [], [], []
    app.loop = SimpleNamespace(headphones=False, restart_mic=mics.append)
    app.devices = SimpleNamespace(output=out, input=LAPTOP_MIC)
    app.session = SimpleNamespace(store=_Store(), reader=SimpleNamespace(reading=reading),
                                  stop_speaking=lambda: stops.append(1),
                                  say=lambda t, p=None: said.append(t))
    app.speech = SimpleNamespace(is_speaking=speaking)
    app.cfg = SimpleNamespace(push_to_talk_hotkey="ctrl+alt+space")
    app._announce_timer, app._paused_for_privacy, app._announced_out = None, "", out
    app._apply_headphone_mode()
    return app, said, stops, mics


def _change(app, old_out, new_out, old_in=LAPTOP_MIC, new_in=LAPTOP_MIC):
    app.devices.output, app.devices.input = new_out, new_in
    app._on_audio_change(old_out, new_out, old_in, new_in)
    if app._announce_timer is not None:
        app._announce_timer.cancel()
        app._announce_audio()


def test_plugging_in_headphones_turns_on_voice_interrupt():
    app, said, _, _ = _app()
    _change(app, SPEAKERS, BOAT)
    assert app.loop.headphones
    assert said == ["boAt Rockerz 450 headphones connected. You can interrupt me just by "
                    "talking."]


def test_unplugging_headphones_pauses_private_reading():
    app, said, stops, _ = _app(out=BOAT, reading=True)
    _change(app, BOAT, SPEAKERS)
    assert stops == [1] and not app.loop.headphones
    assert said == ["Headphones disconnected, so I've paused. Say continue to carry on."]


def test_unplugging_while_idle_just_says_where_sound_goes():
    app, said, stops, _ = _app(out=BOAT)
    _change(app, BOAT, SPEAKERS)
    assert stops == [] and said == ["Headphones disconnected. I'll talk through the "
                                    "Realtek Audio speakers."]


def test_headphone_mode_is_remembered_per_device():
    app, said, _, _ = _app(out=BOAT)
    assert app.loop.headphones
    assert "Headphone mode off for boAt Rockerz 450 headphones" in app.set_headphone_mode("off")
    assert not app.loop.headphones
    _change(app, BOAT, SPEAKERS)
    _change(app, SPEAKERS, BOAT)                          # reconnected later: remembered
    assert not app.loop.headphones                        # the user said: not headphones
    assert said[-1] == "Now speaking through boAt Rockerz 450 headphones."
    assert app.set_headphone_mode("auto").endswith("Headphone mode is on.")
    assert app.loop.headphones


def test_usb_earphones_that_windows_calls_speakers():
    ab13x = Endpoint("usb", "Speakers (AB13X USB Audio)", 1, with_mic=True)
    assert ab13x.is_headphones and ab13x.guessed
    assert dv.device_name(ab13x.name) == "AB13X USB Audio"
    app, said, _, _ = _app()
    _change(app, SPEAKERS, ab13x)
    assert app.loop.headphones and said == [
        "AB13X USB Audio has its own microphone, so I think it's headphones or earphones: "
        "you can interrupt me just by talking. If it's a speaker, say headphone mode off."]
    app.set_headphone_mode("off")                         # they were USB speakers after all
    _change(app, ab13x, SPEAKERS)
    _change(app, SPEAKERS, ab13x)
    assert not app.loop.headphones and said[-1] == "Now speaking through AB13X USB Audio speakers."


def test_saying_im_using_headphones_does_not_touch_the_laptop_speakers():
    app, _, _, _ = _app()                                 # laptop speakers in use
    app.devices.output = Endpoint("usb2", "Speakers (USB Audio Device)", 1)
    assert not app._is_headphones(app.devices.output)
    app.set_headphone_mode("on")                          # "I'm using headphones"
    assert app.loop.headphones
    _change(app, app.devices.output, SPEAKERS)
    assert not app.loop.headphones                        # speakers: still half-duplex


def test_a_bluetooth_double_switch_is_announced_once():
    app, said, _, _ = _app()
    app.devices.output = BOAT_HF
    app._on_audio_change(SPEAKERS, BOAT_HF, LAPTOP_MIC, LAPTOP_MIC)
    first = app._announce_timer
    app.devices.output = BOAT
    app._on_audio_change(BOAT_HF, BOAT, LAPTOP_MIC, LAPTOP_MIC)
    assert first.finished.is_set() and app._announce_timer is not first   # replaced
    app._announce_timer.cancel()
    app._announce_audio()
    assert said == ["boAt Rockerz 450 headphones connected. You can interrupt me just by "
                    "talking."]


def test_a_new_default_microphone_is_opened(monkeypatch):
    import relay.app
    monkeypatch.setattr(relay.app, "mic_device_for", lambda ep: f"device-for-{ep.id}")
    app, _, _, mics = _app()
    _change(app, SPEAKERS, SPEAKERS, LAPTOP_MIC, BOAT_HF)
    assert mics == ["device-for-bt-hfp"]


def test_where_is_the_sound_going(monkeypatch):
    import relay.app
    monkeypatch.setattr(relay.app, "laptop_mic", lambda: 1)
    app, _, _, _ = _app(out=BOAT)
    app.devices.input = BOAT_HF
    text = app.describe_audio()
    assert text.startswith("I'm speaking through boAt Rockerz 450 headphones")
    assert "laptop's own microphone" in text and "Headphone mode is on" in text


def test_headphone_commands_reach_the_audio_control():
    from relay.session import Session

    class Audio:
        def set_headphone_mode(self, mode):
            return f"mode {mode}"

        def describe_audio(self):
            return "speaking through test headphones"

    spoken = []
    s = Session(speak=spoken.append, db_path=":memory:", audio=Audio())
    try:
        s.handle("headphone mode off")
        s.handle("where is the sound going")
        assert "mode off" in spoken and "speaking through test headphones" in spoken
    finally:
        s.close()


# ---------------------------------------------------------------- closing by keyboard
def test_launch_key_again_closes_relay():
    from relay.core.single_instance import QuitSignal
    name = "Local\\RelayQuitTest-" + uuid.uuid4().hex
    assert QuitSignal.request(name) is False             # nothing running yet
    fired = threading.Event()
    sig = QuitSignal(name)
    assert sig.listen(fired.set)
    try:
        assert QuitSignal.request(name) is True
        assert fired.wait(2.0)
    finally:
        sig.stop()


def test_shortcut_toggles_relay():
    from relay.install import launcher
    assert launcher()[1].endswith("--toggle")


# ---------------------------------------------------------------- one .env for both copies
def test_installed_copy_reads_the_project_env(tmp_path, monkeypatch):
    import os

    from relay.envfile import load_env
    monkeypatch.delenv("RELAY_OFFLINE")
    monkeypatch.delenv("RELAY_T9", raising=False)
    project = tmp_path / "project.env"
    project.write_text("RELAY_T9=from_project\n", encoding="utf-8")
    installed = tmp_path / "installed" / ".env"
    installed.parent.mkdir()
    installed.write_text(f"RELAY_ENV_FILE={project}\n", encoding="utf-8")
    loop_back = tmp_path / "loop.env"
    loop_back.write_text(f"RELAY_ENV_FILE={installed}\n", encoding="utf-8")
    loaded = load_env([installed, loop_back])
    assert os.environ["RELAY_T9"] == "from_project"
    assert loaded == [installed, project, loop_back]      # each file once, no loop
