"""The live voice loop — microphone to command, safely.

Two ways to talk to RELAY, both always available:
  * push-to-talk — press the talk key anywhere, hear the listening chirp, speak;
  * wake word    — say "Relay" first (hands-free; can be turned off).
A bare "Relay" also works: RELAY chirps and listens for the command that follows.

Safety and reliability rules built in here:
  * half-duplex — while RELAY is speaking (plus a short tail) the microphone is
    ignored, so RELAY never hears and obeys its own voice through the speakers;
    pressing the talk key interrupts RELAY and then listens (keyboard barge-in);
  * a pre-roll buffer keeps the ~300 ms before speech was detected, so the first
    syllable (often the wake word itself) isn't clipped;
  * utterances are capped (15 s) so noise can't grow the buffer forever;
  * in open-mic dictation, common recogniser "hallucinations" on noise ("Thank you.")
    are dropped rather than typed into the user's document;
  * low-power listening: the speech model costs the same ~0.4 s of CPU for any clip
    (it pads to a fixed window), so waiting for the wake word must not run it on every
    noise blip. Unprompted sounds are screened first — aggressive VAD, at least 0.45 s
    of actual voice, and louder than the room's measured noise floor. Measured in a
    normal room: this is the difference between ~47% and a few percent of a core.

Commands go through the Dispatcher: one worker runs them in order, but stop / cancel
/ pause / emergency stop are handled immediately — they never wait behind a running
action.
"""

from __future__ import annotations

import collections
import queue
import re
import threading
import time
from typing import Callable

from relay.audio.vad import FRAME_BYTES, SpeechSegmenter
from relay.audio.wake import Command, detect_wake, detect_wake_near_miss, match_command
from relay.diagnostics import get_logger
from relay.intent.normalize import normalize

log = get_logger("loop")

FRAME_S = 0.03
PREROLL_FRAMES = 10  # 300 ms kept before speech onset
MAX_UTTERANCE_S = 15.0
PTT_WAIT_S = 6.0  # after the chirp, how long to wait for speech to start
SPEAKING_TAIL_S = 0.35  # ignore the mic this long after RELAY stops talking
MIN_VOICED_S = 0.45  # "Relay, …" has at least this much actual voice
MIN_RMS = 0.004  # absolute floor (~ -48 dBFS)
NOISE_MARGIN = 2.5  # speech must be this much louder than the room noise

_HALLUCINATIONS = {
    "",
    "you",
    "thank you",
    "thanks",
    "thank you very much",
    "thanks for watching",
    "thank you for watching",
    "bye",
    "bye bye",
    "so",
    "okay",
    "oh",
    "uh",
    "um",
    "music",
    "applause",
    "silence",
    "the end",
    "subtitles by the amara.org community",
}


def is_hallucination(text: str) -> bool:
    t = re.sub(r"[\[\]()♪*.,!?\"']", " ", (text or "").lower())
    t = " ".join(t.split())
    return t in _HALLUCINATIONS or len(t) < 2


_IMMEDIATE = {Command.EMERGENCY_STOP, Command.STOP_TALKING, Command.CANCEL_TASK, Command.PAUSE}


def immediate_control(text: str) -> str | None:
    """Control words that must act NOW, even while another command is running."""
    low = normalize(text)
    if "emergency" in low:
        return Command.EMERGENCY_STOP
    if len(low.split()) > 3:
        return None
    cmd = match_command(low)
    if cmd in _IMMEDIATE and low.split()[0] in (
        "stop",
        "cancel",
        "never",
        "nevermind",
        "pause",
        "wait",
        "hold",
        "quiet",
        "be",
        "shush",
        "halt",
        "abort",
        "emergency",
    ):
        return cmd
    return None


class Dispatcher:
    """Runs commands one at a time, in order; control words jump the queue."""

    def __init__(self, session) -> None:
        self.session = session
        self._q: "queue.Queue[str | None]" = queue.Queue()
        self._busy = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="dispatch", daemon=True)
        self._thread.start()

    @property
    def busy(self) -> bool:
        return self._busy.is_set() or not self._q.empty()

    def submit(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if immediate_control(text) is not None:
            try:
                self.session.handle(text)  # flips flags / interrupts speech only
            except Exception as e:
                log.warning("control command failed: %s", e)
            return
        self._q.put(text)

    def _worker(self) -> None:
        while True:
            text = self._q.get()
            if text is None:
                return
            self._busy.set()
            try:
                self.session.handle(text)
            except Exception as e:  # one bad command must never kill the assistant
                log.exception("command failed: %s", e)
                try:
                    self.session.say(
                        "Sorry, something went wrong with that command. I've stopped it."
                    )
                except Exception:
                    pass
            finally:
                self._busy.clear()

    def stop(self) -> None:
        self._q.put(None)


class VoiceLoop:
    def __init__(
        self,
        dispatch: Callable[[str], None],
        stt=None,
        speech=None,
        wake_required: bool = True,
        bus=None,
        segmenter_factory: Callable[[], SpeechSegmenter] | None = None,
        play_earcon: Callable[[str], None] | None = None,
        say: Callable[[str], None] | None = None,
        open_mic: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        threaded: bool = True,
        interrupt: Callable[[], None] | None = None,
    ) -> None:
        if stt is None:
            from relay.audio import WhisperSTT

            stt = WhisperSTT()

        def _dispatch(text: str, _send=dispatch) -> None:
            if self.bus is not None:  # the palette shows "You: …"
                self.bus.emit("voice.heard", text=text)
            _send(text)

        self.dispatch = _dispatch
        # listening on/off (palette switch, "stop listening"); the talk key still works
        self.enabled = True
        self.stt = stt
        # With an online recogniser, the wake word is first checked by this local one,
        # so room conversation is never uploaded — only speech addressed to RELAY.
        self.wake_stt = None
        self.speech = speech
        self.wake_enabled = wake_required
        self.bus = bus
        self._seg_factory = segmenter_factory or SpeechSegmenter
        self._earcon = play_earcon or (lambda name: None)
        self._say = say or (lambda text: None)
        self._open_mic = open_mic or (lambda: False)
        # silence RELAY: the session's stop also cancels a streaming answer and pauses
        # reading; on its own the speech queue would only drop the current sentence
        self._interrupt = interrupt or (
            lambda: self.speech.interrupt() if self.speech is not None else None
        )
        # HEADPHONE MODE: RELAY can't hear itself, so keep listening while it talks and
        # let the user interrupt by voice ("stop", "Relay, ...")
        self.headphones = False
        self._clock = clock
        self._threaded = threaded
        self._lock = threading.Lock()
        self._custom_seg = segmenter_factory is not None
        self._mic = None
        self._armed = False  # listening for a command without a wake word
        self._armed_until = 0.0
        self._silent_tries = 0  # talk key pressed but nothing heard, in a row
        self._noise_rms = 0.0  # running estimate of the room's background level
        self.screened_out = 0  # unprompted sounds dropped before the speech model
        if self.bus is not None:
            self.bus.subscribe("voice.rearm", lambda _e: self.rearm())
        self._reset()

    # ---- state ----
    def _reset(self) -> None:
        if self._custom_seg:
            self.seg = self._seg_factory()
        elif self._armed:  # talk key: sensitive VAD, and end the command after 0.45 s quiet
            self.seg = SpeechSegmenter(aggressiveness=2, end_frames=15)
        else:  # waiting for the wake word: aggressive, noise-proof, 0.6 s
            self.seg = SpeechSegmenter(aggressiveness=3, end_frames=20)
        self._preroll: collections.deque[bytes] = collections.deque(maxlen=PREROLL_FRAMES)
        self._buf = bytearray()
        self._in_utt = False
        self._voiced = 0

    @staticmethod
    def _rms(frame: bytes) -> float:
        import numpy as np

        x = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(x * x))) / 32768.0 if len(x) else 0.0

    def _worth_transcribing(self, pcm: bytes) -> bool:
        """Screen an UNPROMPTED sound before paying for the speech model."""
        if self._voiced * FRAME_S < MIN_VOICED_S:
            return False
        return self._rms(pcm) >= max(MIN_RMS, NOISE_MARGIN * self._noise_rms)

    def _state(self, state: str) -> None:
        if self.bus is not None:
            self.bus.emit("voice.state", to=state)

    def _relay_is_talking(self) -> bool:
        if self.speech is None:
            return False
        if self.speech.is_speaking:
            return True
        return (self._clock() - self.speech.last_active) < SPEAKING_TAIL_S

    # ---- push-to-talk ----
    def push_to_talk(self) -> None:
        """Talk key pressed: stop RELAY talking, chirp, and listen for one command."""
        self._interrupt()
        with self._lock:
            self._armed = True
            self._reset()
            self._armed_until = self._clock() + PTT_WAIT_S + 0.4
        self._earcon("listen")
        self._state("listening")

    # ---- audio ----
    def on_frame(self, frame: bytes) -> None:
        if len(frame) != FRAME_BYTES:
            return
        if not self.enabled and not self._armed:  # switched off: only the talk key
            return
        now = self._clock()
        with self._lock:
            if self._relay_is_talking() and not self.headphones:
                if self._in_utt or self._preroll:
                    self._reset()  # never capture RELAY's own voice
                if self._armed:
                    self._armed_until = max(self._armed_until, now + PTT_WAIT_S)
                return
            listening = self._armed or self.wake_enabled or self._open_mic()
            if not listening:
                return
            if self._armed and not self._in_utt and now > self._armed_until:
                self._armed = False
                self._reset()
                timed_out = True
            else:
                timed_out = False
                ev = self.seg.push(frame)
                voiced = getattr(self.seg, "last_speech", True)
                pcm = None
                if not self._in_utt:
                    self._preroll.append(frame)
                    if not voiced and not self._custom_seg:  # learn the room's noise
                        self._noise_rms = 0.95 * self._noise_rms + 0.05 * self._rms(frame)
                    if ev == "start":
                        self._in_utt = True
                        # the consecutive voiced frames that triggered the start
                        self._voiced = getattr(self.seg, "start_frames", 1)
                        self._buf = bytearray(b"".join(self._preroll))
                        self._preroll.clear()
                else:
                    self._buf.extend(frame)
                    self._voiced += 1 if voiced else 0
                    if ev == "end" or len(self._buf) >= MAX_UTTERANCE_S / FRAME_S * FRAME_BYTES:
                        pcm = bytes(self._buf)
                        was_armed = self._armed
                        if (
                            not was_armed
                            and not self._open_mic()
                            and not self._worth_transcribing(pcm)
                        ):
                            self.screened_out += 1
                            pcm = None  # a noise blip: never reaches the model
                        self._armed = False
                        self._reset()
        if timed_out:
            self._earcon("nothing")
            self._state("idle")
            self._silent_tries += 1
            if self._silent_tries >= 2:  # likely a muted / blocked microphone
                self._silent_tries = 0
                self._say(
                    "I'm not hearing anything from the microphone. Check that it "
                    "isn't muted or turned off in Windows privacy settings, then "
                    "speak right after the chirp."
                )
            return
        if pcm is not None:
            self._silent_tries = 0
            if was_armed:
                self._earcon("heard")
            self._state("transcribing")
            if self._threaded:
                threading.Thread(
                    target=self.on_utterance, args=(pcm, was_armed), name="stt", daemon=True
                ).start()
            else:
                self.on_utterance(pcm, was_armed)

    def on_utterance(self, pcm_bytes: bytes, prompted: bool = False) -> None:
        import numpy as np

        if not pcm_bytes:
            return
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        gated = False
        try:
            local = self.wake_stt
            if (
                not prompted
                and local is not None
                and local is not self.stt
                and not self._open_mic()
            ):
                local_text = local.transcribe(audio)
                if self.headphones and self._relay_is_talking() and immediate_control(local_text):
                    self._state("idle")  # "stop" over RELAY: handled on this PC
                    self.on_transcript(local_text, False)
                    return
                woke, rest = detect_wake(local_text)
                if not woke and self.wake_enabled:
                    # "Really, what time is it?" counts only when the rest is a real
                    # command — so room talk that starts with "really" is never uploaded
                    near, near_rest = detect_wake_near_miss(local_text)
                    if near and near_rest:
                        from relay.intent import Kind, parse

                        woke = parse(near_rest).kind != Kind.UNKNOWN
                        rest = near_rest
                if not woke or not self.wake_enabled:
                    self._state("idle")
                    return  # not for RELAY: nothing is uploaded
                if not rest:
                    self._state("idle")
                    self.rearm()
                    return
                prompted = gated = True  # addressed to RELAY: use the online one
            text = self.stt.transcribe(audio)
        except Exception as e:  # a bad decode must not kill the loop
            log.warning("STT failed: %s", e)
            if prompted:
                self._say("Sorry, I couldn't process that. Please try again.")
            self._state("idle")
            return
        if gated:  # drop "Really," the online one also heard
            near, near_rest = detect_wake_near_miss(text or "")
            if near and near_rest and not detect_wake(text)[0]:
                text = near_rest
        self._state("idle")
        self.on_transcript(text, prompted)

    def on_transcript(self, text: str, prompted: bool = False) -> None:
        """Dispatch one recognised utterance. Unprompted speech must start with the
        wake word (or arrive in open-mic dictation); prompted speech (talk key, or
        after a bare 'Relay') is a command as-is."""
        text = (text or "").strip()
        if not text or (not prompted and is_hallucination(text)):
            if prompted:
                self._say("I didn't catch that.")
            return
        woke, rest = detect_wake(text)
        if prompted:
            if woke and not rest:
                self._say("Yes? What would you like to do?")
                self.rearm()
                return
            self.dispatch(rest if woke else text)
            return
        if self._open_mic():
            self.dispatch(rest if woke and rest else text)
            return
        talking = self.headphones and self._relay_is_talking()
        if talking and not woke and self.wake_enabled and immediate_control(text):
            self.dispatch(text)  # headphones: a plain "stop" interrupts RELAY
            return
        if not woke and self.wake_enabled:
            near, near_rest = detect_wake_near_miss(text)  # "Really, what time is it?"
            if near and near_rest:
                from relay.intent import Kind, parse

                if parse(near_rest).kind != Kind.UNKNOWN:
                    woke, rest = True, near_rest
        if not self.wake_enabled or not woke:
            log.debug("ignored (not addressed to RELAY)")
            return
        if talking and not (rest and immediate_control(rest)):
            self._interrupt()  # "Relay, ..." over RELAY's own voice: stop first
        if rest:
            self.dispatch(rest)
        else:
            self.rearm()  # "Relay" ... (pause) ... "open notepad"

    def rearm(self) -> None:
        """Arm one listening turn without requiring the wake word.
        Waits for active speech to finish before playing the listening earcon."""
        if not self._threaded or not self._relay_is_talking():
            self._rearm()
            return

        def _arm() -> None:
            if self.speech is not None:
                end_t = time.monotonic() + 10.0
                while self._relay_is_talking() and time.monotonic() < end_t:
                    time.sleep(0.05)
            self._rearm()

        threading.Thread(target=_arm, name="rearm-wait", daemon=True).start()

    def _rearm(self) -> None:
        with self._lock:
            self._armed = True
            self._reset()
            self._armed_until = self._clock() + PTT_WAIT_S + 1.5
        self._earcon("listen")
        self._state("listening")

    # ---- microphone ----
    def run(self, device: int | None = None):
        """Start listening on the default microphone (or ``device``). Returns the
        MicCapture (call .stop() to end). Non-blocking."""
        from relay.audio import MicCapture

        self._mic = MicCapture(self.on_frame, device=device)
        self._mic.start()
        return self._mic

    def restart_mic(self, device: int | None = None) -> None:
        """Reopen the microphone — e.g. a headset became the default input."""
        if self._mic is None:
            return
        self._mic.stop()
        with self._lock:
            self._reset()  # don't join audio from two devices
        self.run(device)

    def stop(self) -> None:
        if self._mic is not None:
            self._mic.stop()
            self._mic = None
