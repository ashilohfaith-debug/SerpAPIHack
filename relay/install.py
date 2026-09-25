"""Make RELAY launchable without looking: shortcuts, a launch key, start at login.

A blind user can't type ``python -m relay --start`` into a terminal. So, like NVDA
(Ctrl+Alt+N), RELAY installs a desktop shortcut carrying a Windows shortcut key —
Ctrl+Alt+R by default — which Windows honours from anywhere. A Start-menu entry is
added too, and "start with Windows" is a separate, explicit opt-in. Shortcuts run
the windowless interpreter (pythonw) so no console appears; everything is spoken.
Per-user only: no admin rights, nothing written outside the user's own profile.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Relay"


def app_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def launcher() -> tuple[str, str, str]:
    """(target, arguments, working_dir) that starts RELAY with no console window."""
    if getattr(sys, "frozen", False):                   # PyInstaller build
        exe = Path(sys.executable)
        windowless = exe.with_name("relay.exe")         # not relay-cli.exe's console
        exe = windowless if windowless.exists() else exe
        return str(exe), "--start", str(exe.parent)
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else py), "-m relay --start", str(app_dir())


def _programs_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def startup_dir() -> Path:
    return _programs_dir() / "Startup"


def desktop_dir() -> Path:
    from relay.system.files import known_folder
    return known_folder("desktop") or (Path.home() / "Desktop")


def create_shortcut(path: Path, target: str, args: str, workdir: str, hotkey: str = "",
                    description: str = "Relay — voice assistant for blind users") -> Path:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortCut(str(path))
    sc.TargetPath = target
    sc.Arguments = args
    sc.WorkingDirectory = workdir
    sc.Description = description
    if hotkey:
        sc.Hotkey = hotkey.upper()          # e.g. "CTRL+ALT+R"
    sc.save()
    return path


def install(hotkey: str = "ctrl+alt+r", desktop: bool = True, start_menu: bool = True,
            autostart: bool = False) -> list[Path]:
    target, args, workdir = launcher()
    made: list[Path] = []
    if desktop:
        made.append(create_shortcut(desktop_dir() / f"{APP_NAME}.lnk", target, args, workdir,
                                    hotkey=hotkey))
    if start_menu:
        made.append(create_shortcut(_programs_dir() / f"{APP_NAME}.lnk", target, args,
                                    workdir))
    if autostart:
        made.append(set_autostart(True))
    return made


def set_autostart(on: bool) -> Path:
    link = startup_dir() / f"{APP_NAME}.lnk"
    if on:
        target, args, workdir = launcher()
        return create_shortcut(link, target, args, workdir)
    try:
        link.unlink()
    except FileNotFoundError:
        pass
    return link


def uninstall() -> list[Path]:
    removed = []
    for p in (desktop_dir() / f"{APP_NAME}.lnk", _programs_dir() / f"{APP_NAME}.lnk",
              startup_dir() / f"{APP_NAME}.lnk"):
        try:
            p.unlink()
            removed.append(p)
        except FileNotFoundError:
            pass
    return removed
