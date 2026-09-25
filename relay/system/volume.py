"""System volume — read and set the real master level, so RELAY can say the result.

Uses Windows Core Audio (via pycaw) to get/set the exact level and mute state; if
that is unavailable it falls back to the media volume keys, which change the level
but can't report it (RELAY then says so rather than inventing a number).
"""

from __future__ import annotations

from relay.diagnostics import get_logger

log = get_logger("system.volume")


def _endpoint():
    import comtypes
    try:
        comtypes.CoInitialize()           # this may run on any thread
    except OSError:
        pass
    from pycaw.pycaw import AudioUtilities
    dev = AudioUtilities.GetSpeakers()
    ev = getattr(dev, "EndpointVolume", None)
    if ev is not None:
        return ev
    # older pycaw API
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def get_volume() -> tuple[int, bool] | None:
    """(percent, muted), or None if the level can't be read."""
    try:
        ev = _endpoint()
        return int(round(ev.GetMasterVolumeLevelScalar() * 100)), bool(ev.GetMute())
    except Exception as e:
        log.debug("get volume failed: %s", e)
        return None


def set_volume(percent: int) -> bool:
    try:
        ev = _endpoint()
        ev.SetMasterVolumeLevelScalar(max(0, min(100, int(percent))) / 100.0, None)
        if percent > 0 and ev.GetMute():
            ev.SetMute(0, None)
        return True
    except Exception as e:
        log.debug("set volume failed: %s", e)
        return False


def set_mute(muted: bool) -> bool:
    try:
        _endpoint().SetMute(1 if muted else 0, None)
        return True
    except Exception as e:
        log.debug("set mute failed: %s", e)
        return False


def describe(level: tuple[int, bool] | None) -> str:
    if level is None:
        return "I couldn't read the volume level."
    pct, muted = level
    return f"Volume is at {pct} percent" + (", and muted." if muted else ".")
