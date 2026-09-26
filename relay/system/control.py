"""Laptop controls a blind user asks for every day — all through Windows' own APIs, no
new dependencies, no keys:

- Bluetooth / Wi-Fi on-off and status (Windows.Devices.Radios, the same switch as the
  quick-settings buttons), screen brightness (WMI), dark mode (the Personalize keys),
  a screenshot (saved to Pictures\\Screenshots), shut down / restart / sleep / sign out
  (shut down and restart wait a minute so they can be cancelled), storage left, network
  and IP address, Windows Update, Settings pages, the Recycle Bin, the weather
  (wttr.in — no key; only when asked), and File Explorer actions on the selected item
  (rename, move, copy, delete to the Recycle Bin) or a new folder.

Every function returns a plain spoken sentence (or raises nothing): a failure is told,
never hidden. Risky ones (power, delete, empty the bin) are confirmed by the caller
with a spoken phrase first.
"""
# ruff: noqa: E501  (the embedded PowerShell script keeps its long lines)

from __future__ import annotations

import ctypes
import re
import shutil
import subprocess
import time
from pathlib import Path

from relay.diagnostics import get_logger

log = get_logger("system.control")
_NO_WINDOW = 0x08000000


def _ps(script: str, timeout: float = 20.0) -> str:
    """Run a PowerShell snippet (no window) and return its output."""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                        "Bypass", "-Command", script], capture_output=True, text=True,
                       timeout=timeout, encoding="utf-8", errors="replace",
                       creationflags=_NO_WINDOW)
    return (r.stdout or "").strip()


# ---------------------------------------------------------------- radios
_RADIO_PS = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) {
  $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
[Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioState, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$r = $radios | Where-Object { $_.Kind -eq '__KIND__' } | Select-Object -First 1
if (-not $r) { 'NONE'; exit }
if ('__STATE__' -ne 'status') {
  $res = Await ($r.SetStateAsync('__STATE__')) ([Windows.Devices.Radios.RadioAccessStatus]); "SET:$res" }
"STATE:$($r.State)"
"""
_RADIO_NAMES = {"bluetooth": ("Bluetooth", "Bluetooth"), "wifi": ("WiFi", "Wi-Fi")}


def radio(kind: str, state: str = "status") -> str:
    """kind: 'bluetooth' | 'wifi'; state: 'on' | 'off' | 'status'."""
    winrt, spoken = _RADIO_NAMES[kind]
    want = {"on": "On", "off": "Off"}.get(state, "status")
    try:
        out = _ps(_RADIO_PS.replace("__KIND__", winrt).replace("__STATE__", want))
    except Exception as e:
        log.warning("radio %s failed: %s", kind, e)
        return f"I couldn't reach the {spoken} switch."
    if "NONE" in out.split():
        return f"This computer doesn't seem to have {spoken}."
    m = re.search(r"STATE:(\w+)", out)
    now = (m.group(1) if m else "").lower()
    if want == "status":
        return f"{spoken} is {now}." if now in ("on", "off") else f"I couldn't tell if {spoken} is on."
    if "SET:Allowed" not in out:
        return (f"Windows didn't let me turn {spoken} {state}. It may be controlled by "
                "airplane mode or your organisation.")
    if kind == "wifi" and state == "off":
        return "Wi-Fi is off. You won't have internet until you turn it back on."
    return f"{spoken} is {state}."


# ---------------------------------------------------------------- brightness
def brightness() -> int | None:
    try:
        out = _ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
                  "-ErrorAction Stop | Select-Object -First 1).CurrentBrightness", 10)
        return int(out) if out.isdigit() else None
    except Exception:
        return None


def set_brightness(level: int) -> str:
    level = max(0, min(100, int(level)))
    try:
        _ps("$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods "
            "-ErrorAction Stop | Select-Object -First 1; Invoke-CimMethod -InputObject $m "
            f"-MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness=[byte]{level}}} "
            "| Out-Null", 10)
    except Exception as e:
        log.warning("brightness failed: %s", e)
    now = brightness()
    if now is None:
        return "I can't change the brightness of this screen from here."
    return f"Brightness is {now} percent."


def change_brightness(action: str, level: int | None = None) -> str:
    cur = brightness()
    if cur is None:
        return "I can't read the brightness of this screen. It may be an external monitor."
    if action == "get":
        return f"Brightness is {cur} percent."
    if action == "set" and level is not None:
        return set_brightness(level)
    step = 20 if action == "up" else -20
    return set_brightness(cur + step)


# ---------------------------------------------------------------- dark mode
def set_dark_mode(on: bool) -> str:
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 0 if on else 1)
        # tell open windows the colours changed (WM_SETTINGCHANGE "ImmersiveColorSet")
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet",
                                                 0x0002, 200, None)
    except Exception as e:
        log.warning("dark mode failed: %s", e)
        return "I couldn't change dark mode."
    return "Dark mode is on." if on else "Dark mode is off; light mode is on."


# ---------------------------------------------------------------- screenshot
def screenshot() -> tuple[str, Path | None]:
    from relay.system.files import known_folder
    folder = (known_folder("pictures") or Path.home() / "Pictures") / "Screenshots"
    try:
        from PIL import ImageGrab
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / time.strftime("Relay screenshot %Y-%m-%d %H-%M-%S.png")
        ImageGrab.grab(all_screens=True).save(path)
    except Exception as e:
        log.warning("screenshot failed: %s", e)
        return "I couldn't take a screenshot.", None
    return (f"Screenshot saved in your Pictures, in the Screenshots folder, as "
            f"{path.stem}."), path


# ---------------------------------------------------------------- power
def power(action: str) -> str:
    """shutdown / restart wait one minute ('cancel shutdown' stops them)."""
    try:
        if action == "cancel":
            r = subprocess.run(["shutdown", "/a"], capture_output=True, creationflags=_NO_WINDOW)
            return ("Cancelled. The computer will stay on." if r.returncode == 0 else
                    "There was no shutdown or restart to cancel.")
        if action in ("shutdown", "restart"):
            flag = "/s" if action == "shutdown" else "/r"
            subprocess.run(["shutdown", flag, "/t", "60", "/c",
                            "Relay: say cancel shutdown to stop this."],
                           capture_output=True, creationflags=_NO_WINDOW)
            word = "shut down" if action == "shutdown" else "restart"
            return (f"The computer will {word} in one minute. Save your work. Say cancel "
                    "shutdown to stop it.")
        if action == "signout":
            subprocess.Popen(["shutdown", "/l"], creationflags=_NO_WINDOW)
            return "Signing you out."
        if action == "sleep":
            ctypes.windll.powrprof.SetSuspendState(False, False, False)
            return "Good morning — the computer is awake again."
    except Exception as e:
        log.warning("power %s failed: %s", action, e)
    return "I couldn't do that."


# ---------------------------------------------------------------- information
def _gb(n: int) -> str:
    g = n / 1e9
    return f"{g:.1f}" if g < 10 else f"{g:.0f}"


def storage_text() -> str:
    parts = []
    for letter in "CDEFGHIJ":
        root = f"{letter}:\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) != 3:          # DRIVE_FIXED
            continue
        try:
            u = shutil.disk_usage(root)
        except OSError:
            continue
        parts.append(f"drive {letter} has {_gb(u.free)} gigabytes free of {_gb(u.total)}")
    if not parts:
        return "I couldn't read the drives."
    text = "; ".join(parts) + "."
    return text[0].upper() + text[1:]


def network_text() -> str:
    import socket
    ip = ""
    try:                                            # route lookup only: nothing is sent
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
    except OSError:
        pass
    ssid = ""
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True,
                             text=True, timeout=8, creationflags=_NO_WINDOW,
                             errors="replace").stdout
        m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
        ssid = m.group(1).strip() if m else ""
    except Exception:
        pass
    if not ip or ip.startswith("127."):
        return "You're not connected to a network."
    said = f"You're connected to the Wi-Fi network {ssid}. " if ssid else "You're connected. "
    return said + "Your address on this network is " + " dot ".join(ip.split(".")) + "."


# ---------------------------------------------------------------- settings pages
SETTINGS_PAGES = {
    "bluetooth": "bluetooth", "devices": "bluetooth", "wifi": "network-wifi",
    "wi-fi": "network-wifi", "wi fi": "network-wifi", "network": "network-status",
    "internet": "network-status", "display": "display", "screen": "display",
    "brightness": "display", "sound": "sound", "audio": "sound", "volume": "sound",
    "battery": "batterysaver", "power": "powersleep", "sleep": "powersleep",
    "update": "windowsupdate", "updates": "windowsupdate", "windows update": "windowsupdate",
    "accessibility": "easeofaccess", "ease of access": "easeofaccess",
    "narrator": "easeofaccess-narrator", "magnifier": "easeofaccess-magnifier",
    "mouse": "mousetouchpad", "touchpad": "devices-touchpad", "keyboard": "typing",
    "typing": "typing", "language": "regionlanguage", "time": "dateandtime",
    "date": "dateandtime", "date and time": "dateandtime", "apps": "appsfeatures",
    "privacy": "privacy", "microphone": "privacy-microphone", "camera": "privacy-webcam",
    "storage": "storagesense", "personalization": "personalization",
    "background": "personalization-background", "wallpaper": "personalization-background",
    "colors": "colors", "colours": "colors", "dark mode": "colors", "theme": "themes",
    "night light": "nightlight", "notifications": "notifications", "focus": "quiethours",
    "do not disturb": "quiethours", "default apps": "defaultapps", "printers": "printers",
    "printer": "printers", "vpn": "network-vpn", "airplane mode": "network-airplanemode",
    "hotspot": "network-mobilehotspot", "mobile hotspot": "network-mobilehotspot",
    "account": "yourinfo", "accounts": "yourinfo", "sign in": "signinoptions",
    "password": "signinoptions", "about": "about", "system": "about",
    "startup apps": "startupapps", "multitasking": "multitasking",
}


def settings_uri(topic: str) -> str | None:
    t = re.sub(r"\b(?:the|my|settings?|page|options?)\b", " ", topic.lower())
    t = " ".join(t.split())
    page = SETTINGS_PAGES.get(t)
    return f"ms-settings:{page}" if page else None


# ---------------------------------------------------------------- recycle bin
def empty_recycle_bin() -> str:
    try:
        hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    except Exception:
        hr = -1
    if hr in (0, -2147418113):          # S_OK, or E_UNEXPECTED when it's already empty
        return "The Recycle Bin is empty."
    return "I couldn't empty the Recycle Bin."


# ---------------------------------------------------------------- weather
def weather_text(place: str = "") -> str:
    import urllib.parse
    import urllib.request

    from relay.envfile import offline_forced
    if offline_forced():
        return "I can't check the weather while I'm set to stay offline."
    fmt = "%l: %C, %t, feels like %f, humidity %h, wind %w"
    url = "https://wttr.in/" + urllib.parse.quote(place.strip()) + "?format=" + \
        urllib.parse.quote(fmt)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8", "replace").strip()
    except Exception as e:
        log.info("weather unavailable: %s", e)
        return "I can't reach the weather service right now. Check your internet."
    if not text or "unknown location" in text.lower() or "<html" in text.lower():
        return f"I couldn't find the weather for {place}." if place else \
            "I couldn't get the weather."
    text = re.sub(r"\+?(-?\d+)°C", r"\1 degrees", text)
    text = re.sub(r"[↑↓←→↖↗↘↙]", "", text).replace("km/h", " kilometres an hour")
    text = re.sub(r"\s+", " ", text).replace(" ,", ",")
    return text if text.endswith(".") else text + "."


# ---------------------------------------------------------------- File Explorer
def explorer_window(hwnd: int | None = None):
    """The File Explorer window in front (or with ``hwnd``) as a Shell COM object."""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    if hwnd is None:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
    for w in win32com.client.Dispatch("Shell.Application").Windows():
        try:
            if int(w.HWND) == int(hwnd):
                return w
        except Exception:
            continue
    return None


def explorer_selection() -> tuple[Path | None, list[Path]]:
    """(current folder, selected items) of the File Explorer window in front."""
    w = explorer_window()
    if w is None:
        return None, []
    try:
        folder = Path(w.Document.Folder.Self.Path)
        items = w.Document.SelectedItems()
        return folder, [Path(items.Item(i).Path) for i in range(items.Count)]
    except Exception as e:
        log.debug("explorer selection failed: %s", e)
        return None, []


def recycle(path: Path) -> bool:
    """Send a file or folder to the Recycle Bin (undo-able), never a permanent delete."""
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint),
                    ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]
    op = SHFILEOPSTRUCTW(None, 3, str(path) + "\0", None,     # FO_DELETE
                         0x0040 | 0x0010 | 0x0004 | 0x0400,   # ALLOWUNDO|NOCONFIRM|SILENT|NOERRUI
                         0, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return rc == 0 and not op.fAnyOperationsAborted and not path.exists()
