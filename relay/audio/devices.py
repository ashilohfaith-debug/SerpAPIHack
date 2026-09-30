"""Headphones and other audio devices: RELAY follows whatever Windows is using.

- RELAY plays and records through Windows' Sound Mapper, which always means "the
  current default device" — so when headphones are connected (wired, USB or Bluetooth)
  the next thing RELAY says is in the headphones, and back on the speakers when they're
  removed. (Before, RELAY stayed on whatever device was the default when it started.)
- A light watcher asks Windows for the default devices' IDs twice a second — about
  0.25 ms of CPU each time; names are only looked up when an ID changes — so RELAY can
  say where it is speaking now, reopen the microphone on the new default input, and
  pause reading when headphones are removed (private text is not suddenly read out to
  the room).
- HEADPHONE MODE: with headphones RELAY can't hear itself, so the microphone stays open
  while it talks and the user can interrupt just by speaking ("stop", "Relay, …"). It
  turns on automatically for headphones and headsets; "headphone mode on / off"
  overrides it (earphones in a laptop's combined jack are often reported as speakers).
- A Bluetooth headset's hands-free microphone drops the headset into phone-call audio
  quality for as long as it is open — and RELAY always listens — so in that case RELAY
  keeps using the laptop's own microphone and the headphones stay in full quality.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from relay.diagnostics import get_logger

log = get_logger("audio.devices")

_FORM_FACTOR = "{1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E} 0"  # PKEY_AudioEndpoint_FormFactor
_BUS = "{A45C254E-DF1C-4EFD-8020-67D146A850E0} 24"  # PKEY_Device_EnumeratorName
_PHYSICAL = "{B3F8FA53-0004-438E-9003-51A46E139BFC} 2"  # the physical device behind it
HEADPHONES, HEADSET, HANDSET = 3, 5, 6
_HEAD_WORDS = (
    "headphone",
    "headset",
    "earphone",
    "earbud",
    "buds",
    "airpods",
    "hands-free",
    "handsfree",
    "neckband",
)
_HANDS_FREE = ("hands-free", "handsfree", "hands free")
MAPPER_OUT = "Microsoft Sound Mapper - Output"
MAPPER_IN = "Microsoft Sound Mapper - Input"
_RENDER, _CAPTURE, _CONSOLE = 0, 1, 0  # EDataFlow / ERole


@dataclass(frozen=True)
class Endpoint:
    id: str
    name: str
    form_factor: int = -1
    # a plug-in (USB / Bluetooth) output whose own device also has a microphone: USB-C
    # earphones and headset adapters, which Windows often just calls "Speakers"
    with_mic: bool = False

    @property
    def said_headphones(self) -> bool:
        """Windows (form factor) or the device's name says headphones."""
        if self.form_factor in (HEADPHONES, HEADSET, HANDSET):
            return True
        low = self.name.lower()
        return any(w in low for w in _HEAD_WORDS)

    @property
    def is_headphones(self) -> bool:
        return self.said_headphones or self.with_mic

    @property
    def guessed(self) -> bool:
        """Headphones by inference only (worth saying so, so the user can correct it)."""
        return self.with_mic and not self.said_headphones

    @property
    def is_hands_free(self) -> bool:
        """A Bluetooth headset's call-quality (hands-free profile) microphone."""
        low = self.name.lower()
        return any(w in low for w in _HANDS_FREE)


def same(a: Optional[Endpoint], b: Optional[Endpoint]) -> bool:
    return (a.id if a else None) == (b.id if b else None)


def spoken_name(name: str) -> str:
    """'Headphones (boAt Rockerz 450 Stereo)' -> 'boAt Rockerz 450 headphones'."""
    clean = re.sub(r"\((?:R|TM)\)", "", name or "", flags=re.I).strip()
    m = re.match(r"^([^()]+?)\s*\((.+)\)$", clean)
    if not m:
        return clean
    kind, device = m.group(1).strip(), m.group(2).strip()
    device = re.sub(r"\s+(?:stereo|hands-?free(?:\s+ag\s+audio)?)$", "", device, flags=re.I).strip()
    return f"{device} {kind.lower()}" if device else kind


def device_name(name: str) -> str:
    """'Speakers (AB13X USB Audio)' -> 'AB13X USB Audio' (the product, not Windows' role
    label — which is wrong for earphones Windows calls speakers)."""
    clean = re.sub(r"\((?:R|TM)\)", "", name or "", flags=re.I).strip()
    m = re.match(r"^([^()]+?)\s*\((.+)\)$", clean)
    return m.group(2).strip() if m else clean


class _Probe:
    """Windows' default output/input endpoints. Cheap (IDs only) unless a device is new.
    COM objects belong to the thread that made them: use one _Probe per thread."""

    def __init__(self) -> None:
        import comtypes

        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        from pycaw.pycaw import AudioUtilities

        self._au = AudioUtilities
        self._enum = AudioUtilities.GetDeviceEnumerator()
        self._known: dict[str, Endpoint] = {}

    def __call__(self) -> tuple[Optional[Endpoint], Optional[Endpoint]]:
        return self._one(_RENDER), self._one(_CAPTURE)

    def _one(self, flow: int) -> Optional[Endpoint]:
        try:
            dev = self._enum.GetDefaultAudioEndpoint(flow, _CONSOLE)
            dev_id = str(dev.GetId())
        except Exception:
            return None  # no device of this kind right now
        ep = self._known.get(dev_id)
        if ep is None:  # a device we haven't seen: read its details
            name, ff, with_mic = "", -1, False
            try:
                name, props = self._details(dev)
                v = props.get(_FORM_FACTOR, -1)
                ff = v if isinstance(v, int) else -1
                if flow == _RENDER:
                    with_mic = self._has_own_mic(props)
            except Exception as e:
                log.debug("device details unavailable: %s", e)
            ep = self._known[dev_id] = Endpoint(dev_id, name, ff, with_mic)
        return ep

    def _details(self, dev) -> tuple[str, dict]:
        import warnings

        with warnings.catch_warnings():  # pycaw warns about unreadable properties
            warnings.simplefilter("ignore")
            d = self._au.CreateDevice(dev)
        return str(d.FriendlyName or ""), dict(d.properties or {})

    def _has_own_mic(self, props: dict) -> bool:
        """USB/Bluetooth output whose physical device also records (the laptop's own
        audio chip has speakers and microphones too, so internal buses don't count)."""
        bus = str(props.get(_BUS, "")).upper()
        physical = props.get(_PHYSICAL)
        if not physical or not (bus == "USB" or bus.startswith("BTH")):
            return False
        try:
            mics = self._enum.EnumAudioEndpoints(_CAPTURE, 1)  # DEVICE_STATE_ACTIVE
            for i in range(mics.GetCount()):
                if self._details(mics.Item(i))[1].get(_PHYSICAL) == physical:
                    return True
        except Exception as e:
            log.debug("could not list microphones: %s", e)
        return False


def default_endpoints() -> tuple[Optional[Endpoint], Optional[Endpoint]]:
    """One-off look at Windows' default (output, input) devices; (None, None) if Core
    Audio isn't available."""
    try:
        return _Probe()()
    except Exception as e:
        log.debug("Core Audio unavailable: %s", e)
        return None, None


def _mme_devices():
    import sounddevice as sd

    try:
        mme = next(i for i, h in enumerate(sd.query_hostapis()) if h["name"] == "MME")
    except StopIteration:
        return []
    return [(i, d) for i, d in enumerate(sd.query_devices()) if d["hostapi"] == mme]


def mapper_device(kind: str) -> Optional[int]:
    """PortAudio index of Windows' Sound Mapper — 'whatever the default device is'."""
    want = MAPPER_OUT if kind == "output" else MAPPER_IN
    try:
        return next((i for i, d in _mme_devices() if d["name"] == want), None)
    except Exception:
        return None


def laptop_mic() -> Optional[int]:
    """A real microphone that is not a headset's hands-free one (the laptop's own)."""
    try:
        for i, d in _mme_devices():
            low = d["name"].lower()
            if d["max_input_channels"] < 1 or "sound mapper" in low or "virtual" in low:
                continue
            if any(w in low for w in _HANDS_FREE + ("headset",)):
                continue
            return i
    except Exception:
        pass
    return None


def mic_device_for(default_input: Optional[Endpoint]) -> Optional[int]:
    """Where to listen: the Windows default microphone, except a Bluetooth hands-free
    one (it would turn the headphones' audio into phone-call quality)."""
    if default_input is not None and default_input.is_hands_free:
        own = laptop_mic()
        if own is not None:
            return own
    return mapper_device("input")


def use_windows_defaults() -> None:
    """Make every stream follow Windows' default devices (the Sound Mapper)."""
    try:
        import sounddevice as sd

        cur_in, cur_out = sd.default.device
        i, o = mapper_device("input"), mapper_device("output")
        sd.default.device = (cur_in if i is None else i, cur_out if o is None else o)
    except Exception as e:
        log.debug("could not select the Sound Mapper: %s", e)


Change = Callable[
    [Optional[Endpoint], Optional[Endpoint], Optional[Endpoint], Optional[Endpoint]], None
]


class DeviceWatch:
    """Reports when Windows' default output or input device changes:
    ``on_change(old_output, new_output, old_input, new_input)``."""

    def __init__(
        self,
        on_change: Change,
        probe_factory: Callable[[], Callable] = _Probe,
        interval: float = 0.5,
    ) -> None:
        self.on_change = on_change
        self._factory = probe_factory
        self.interval = interval
        self.output: Optional[Endpoint] = None
        self.input: Optional[Endpoint] = None
        self._probe: Optional[Callable] = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def prime(self, probe: Callable) -> None:
        self._probe = probe
        self.output, self.input = probe()

    def check(self) -> bool:
        """Look once; True if something changed (and ``on_change`` was called)."""
        if self._probe is None:
            return False
        out, inp = self._probe()
        if out is None and inp is None and (self.output or self.input):
            return False  # a Core Audio hiccup, not "no devices"
        if same(out, self.output) and same(inp, self.input):
            return False
        old_out, old_in = self.output, self.input
        self.output, self.input = out, inp
        try:
            self.on_change(old_out, out, old_in, inp)
        except Exception as e:
            log.warning("audio device change handler failed: %s", e)
        return True

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="audio-devices", daemon=True)
        self._thread.start()
        self._ready.wait(3.0)  # initial devices known before start-up goes on

    def _run(self) -> None:
        try:
            self.prime(self._factory())
        except Exception as e:
            log.info("audio device watch unavailable: %s", e)
            return
        finally:
            self._ready.set()
        while not self._stop.wait(self.interval):
            try:
                self.check()
            except Exception as e:
                log.debug("audio device check failed: %s", e)

    def stop(self) -> None:
        self._stop.set()
