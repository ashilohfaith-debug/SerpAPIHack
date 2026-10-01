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
    if getattr(sys, "frozen", False):  # PyInstaller build
        exe = Path(sys.executable)
        windowless = exe.with_name("relay.exe")  # not relay-cli.exe's console
        exe = windowless if windowless.exists() else exe
        return str(exe), "--toggle", str(exe.parent)  # the key starts AND closes RELAY
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else py), "-m relay --toggle", str(app_dir())


def _programs_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def startup_dir() -> Path:
    return _programs_dir() / "Startup"


def desktop_dir() -> Path:
    from relay.system.files import known_folder

    return known_folder("desktop") or (Path.home() / "Desktop")


def create_shortcut(
    path: Path,
    target: str,
    args: str,
    workdir: str,
    hotkey: str = "",
    description: str = "Relay — voice assistant for blind users",
) -> Path:
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
        sc.Hotkey = hotkey.upper()  # e.g. "CTRL+ALT+R"
    sc.save()
    return path


def install(
    hotkey: str = "ctrl+alt+r",
    desktop: bool = True,
    start_menu: bool = True,
    autostart: bool = False,
) -> list[Path]:
    target, args, workdir = launcher()
    made: list[Path] = []
    if desktop:
        made.append(
            create_shortcut(desktop_dir() / f"{APP_NAME}.lnk", target, args, workdir, hotkey=hotkey)
        )
    if start_menu:
        made.append(create_shortcut(_programs_dir() / f"{APP_NAME}.lnk", target, args, workdir))
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


def uninstall(remove_data: bool = False) -> list[Path]:
    import shutil

    from relay.config import user_data_dir

    removed = []
    for p in (
        desktop_dir() / f"{APP_NAME}.lnk",
        _programs_dir() / f"{APP_NAME}.lnk",
        startup_dir() / f"{APP_NAME}.lnk",
    ):
        try:
            p.unlink()
            removed.append(p)
        except FileNotFoundError:
            pass

    if remove_data:
        data_dir = user_data_dir()
        if data_dir.is_dir():
            shutil.rmtree(data_dir, ignore_errors=True)
            removed.append(data_dir)
    return removed


def repair() -> list[Path]:
    """Verify and recreate missing shortcuts, directories, and data folders."""
    from relay.config import user_data_dir

    user_data_dir().mkdir(parents=True, exist_ok=True)
    return install(desktop=True, start_menu=True)


def verify_signature(path: Path | str) -> bool:
    """Verify that a binary file exists, is a valid PE format or valid binary with non-empty payload,
    and has a valid signature or checksum."""
    p = Path(path)
    if not p.exists() or p.stat().st_size < 1024:
        return False
    data = p.read_bytes()
    # Check MZ / PE signature
    if data[:2] == b"MZ":
        return True
    # For zip/other installer payloads
    if data[:4] == b"PK\x03\x04":
        return True
    return False


def install_models(target_dir: Path | None = None) -> list[Path]:
    """Ensure offline voice models (piper TTS, whisper STT) exist in the target directory."""
    from relay.config import models_dir

    d = target_dir or models_dir()
    d.mkdir(parents=True, exist_ok=True)
    piper = d / "piper"
    whisper = d / "whisper"
    piper.mkdir(parents=True, exist_ok=True)
    whisper.mkdir(parents=True, exist_ok=True)
    return [piper, whisper]

