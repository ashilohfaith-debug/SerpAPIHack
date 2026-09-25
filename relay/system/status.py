"""System status a blind user asks about all day: time, date, battery, internet.

Everything here is a local query — the internet check asks Windows' Network List
Manager / WinINet whether it believes it is online; it does not send packets, so
Essential mode stays offline. Each function returns a short spoken sentence.
"""

from __future__ import annotations

import datetime as _dt
import re
import subprocess

from relay.diagnostics import get_logger

log = get_logger("system.status")


def time_text(now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now()
    hour = now.hour % 12 or 12
    ampm = "AM" if now.hour < 12 else "PM"
    minute = f"{now.minute:02d}"
    spoken = f"{hour} o'clock" if now.minute == 0 else f"{hour}:{minute}"
    return f"It's {spoken} {ampm}."


def date_text(now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now()
    return f"Today is {now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}."


def battery_text() -> str:
    try:
        import psutil
        b = psutil.sensors_battery()
    except Exception as e:
        log.debug("battery read failed: %s", e)
        b = None
    if b is None:
        return "I can't find a battery — this computer may be plugged into mains power only."
    pct = int(round(b.percent))
    if b.power_plugged:
        state = "and charging" if pct < 100 else "and fully charged"
        return f"Battery is at {pct} percent, {state}."
    left = ""
    secs = b.secsleft
    if isinstance(secs, (int, float)) and secs > 0 and secs < 10 * 3600:
        h, m = int(secs // 3600), int((secs % 3600) // 60)
        left = (f" About {h} hour{'s' if h != 1 else ''} and {m} minutes left." if h
                else f" About {m} minutes left.")
    warn = " It's getting low — you may want to plug in." if pct <= 20 else ""
    return f"Battery is at {pct} percent, on battery power.{left}{warn}"


def is_online() -> bool | None:
    """Windows' own view of internet connectivity (no packets sent). None = unknown."""
    try:
        import comtypes
        import comtypes.client
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        nlm = comtypes.client.CreateObject("{DCB00C01-570F-4A9B-8D69-199FDBA5723B}",
                                           dynamic=True)
        return bool(nlm.IsConnectedToInternet)
    except Exception as e:
        log.debug("NLM check failed: %s", e)
    try:
        import ctypes
        flags = ctypes.c_ulong(0)
        return bool(ctypes.windll.wininet.InternetGetConnectedState(ctypes.byref(flags), 0))
    except Exception:
        return None


def wifi_name() -> str | None:
    """SSID of the connected Wi-Fi network, if any (local `netsh` query)."""
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True,
                             text=True, timeout=4, creationflags=0x08000000).stdout
    except Exception:
        return None
    m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.MULTILINE)
    state = re.search(r"^\s*State\s*:\s*(\w+)", out, re.MULTILINE)
    if m and (state is None or state.group(1).lower() == "connected"):
        return m.group(1).strip()
    return None


def internet_text() -> str:
    online = is_online()
    ssid = wifi_name()
    via = f" through the Wi-Fi network {ssid}" if ssid else ""
    if online is True:
        return f"Yes, you're connected to the internet{via}."
    if online is False:
        if ssid:
            return (f"You're connected to the Wi-Fi network {ssid}, but Windows says "
                    "there's no internet access right now.")
        return "You're not connected to the internet right now."
    return "I couldn't check the internet connection."


def status_text() -> str:
    return " ".join([time_text(), battery_text(), internet_text()])
