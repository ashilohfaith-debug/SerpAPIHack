"""SERP-Relay Setup & 1-Click Installer.

Installs SERP-Relay to %LOCALAPPDATA%\\Programs\\SERP-Relay,
creates Start Menu and Desktop shortcuts (Ctrl+Alt+R), and launches immediately.
For SerpApi India Hackathon 2026.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def print_banner():
    print("=" * 64)
    print("   SERP-RELAY — Live-World Voice Agent powered by SerpApi")
    print("   SerpApi India Hackathon 2026 (AI Agents Track)")
    print("=" * 64)
    print("\nInstalling SERP-Relay on your computer...\n")


def speak(text: str):
    """Speak using Windows SAPI voice so blind users hear progress immediately."""
    try:
        safe_text = text.replace("'", "''")
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.Speak('{safe_text}')",
        ]
        subprocess.Popen(cmd)
    except Exception:
        pass


def main():
    # Source directory (where installer is running or adjacent payload)
    exe_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent
    )
    meipass = Path(getattr(sys, "_MEIPASS", exe_dir))

    # Target directory: Isolated in %LOCALAPPDATA%\Programs\SERP-Relay
    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    target_dir = local_app_data / "Programs" / "SERP-Relay"
    target_dir.mkdir(parents=True, exist_ok=True)

    cli_exe = target_dir / "relay-cli.exe"
    relay_exe = target_dir / "relay.exe"

    # Forward CLI arguments directly if already installed and called with flags
    args = sys.argv[1:]
    if args and args[0] != "--install" and (relay_exe.exists() or cli_exe.exists()):
        cmd_target = cli_exe if cli_exe.exists() else relay_exe
        try:
            res = subprocess.run([str(cmd_target)] + args, cwd=str(target_dir))
            sys.exit(res.returncode)
        except Exception as e:
            print(f"Error running command: {e}")

    print_banner()
    speak("Installing Serp-Relay. Please wait a moment.")
    print(f"Target folder: {target_dir}")

    # Check for zip payload first
    extracted = False
    zip_candidates = [
        meipass / "downloads" / "relay-windows-x64.zip",
        exe_dir / "downloads" / "relay-windows-x64.zip",
        exe_dir / "relay-windows-x64.zip",
        Path.cwd() / "downloads" / "relay-windows-x64.zip",
        Path.cwd() / "relay-windows-x64.zip",
    ]
    for zfile in zip_candidates:
        if zfile.exists():
            import zipfile
            print(f"Extracting application payload from {zfile.name}...")
            with zipfile.ZipFile(zfile, "r") as z:
                z.extractall(target_dir)
            extracted = True
            break

    # If zip not extracted, look for unpacked folders
    if not extracted:
        src_payload = exe_dir / "dist" / "relay"
        if not src_payload.exists():
            src_payload = exe_dir / "relay"
        if not src_payload.exists():
            src_payload = exe_dir

        if (src_payload / "relay.exe").exists() and src_payload != target_dir:
            print("Copying application files...")
            for item in src_payload.iterdir():
                if item.name.lower() in ("build", ".git", ".venv", "setup.exe", "relay-setup.exe", "serp-relay.exe"):
                    continue
                dest = target_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)

    # Ensure _internal and models runtime folders are copied into target_dir
    internal_candidates = [
        exe_dir / "_internal",
        exe_dir / "dist" / "relay" / "_internal",
        Path("D:/Programs/Relay/_internal"),
        local_app_data / "Programs" / "Relay" / "_internal",
    ]
    for ic in internal_candidates:
        if ic.exists() and not (target_dir / "_internal").exists():
            print(f"Installing runtime dependencies from {ic}...")
            shutil.copytree(ic, target_dir / "_internal", dirs_exist_ok=True)
            break

    models_candidates = [
        exe_dir / "models",
        exe_dir / "dist" / "relay" / "models",
        Path("D:/Programs/Relay/models"),
        local_app_data / "Programs" / "Relay" / "models",
    ]
    for mc in models_candidates:
        if mc.exists() and not (target_dir / "models").exists():
            print(f"Installing models from {mc}...")
            shutil.copytree(mc, target_dir / "models", dirs_exist_ok=True)
            break

    print("Registering system shortcuts (Desktop & Start Menu with Ctrl+Alt+R)...")
    if cli_exe.exists():
        try:
            subprocess.run([str(cli_exe), "--install"], check=True, capture_output=True, timeout=15)
            print("Shortcuts registered successfully via CLI.")
        except Exception as e:
            print(f"CLI shortcut note: {e}")

    # Ensure desktop shortcut is created on active Desktop directly
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("WScript.Shell")
        user_prof = Path(os.environ.get("USERPROFILE", str(Path.home())))
        for dt in [user_prof / "OneDrive" / "Desktop", user_prof / "Desktop"]:
            if dt.exists() and relay_exe.exists():
                lnk = dt / "SERP-Relay.lnk"
                sc = shell.CreateShortCut(str(lnk))
                sc.TargetPath = str(relay_exe)
                sc.Arguments = "--toggle"
                sc.WorkingDirectory = str(target_dir)
                sc.Description = "SERP-Relay — Live-World Voice Agent powered by SerpApi"
                sc.Hotkey = "CTRL+ALT+R"
                sc.save()
                print(f"Desktop shortcut created: {lnk}")
    except Exception as e:
        print(f"Direct shortcut note: {e}")

    # Copy .env or .env.example
    env_src = exe_dir / ".env"
    if not env_src.exists():
        env_src = Path.cwd() / ".env"
    if env_src.exists():
        shutil.copy2(env_src, target_dir / ".env")
        relay_data = local_app_data / "SERP-Relay"
        relay_data.mkdir(parents=True, exist_ok=True)
        shutil.copy2(env_src, relay_data / ".env")
        print("Environment configuration applied.")
    else:
        example_env = exe_dir / ".env.example"
        if not example_env.exists():
            example_env = Path.cwd() / ".env.example"
        if example_env.exists():
            shutil.copy2(example_env, target_dir / ".env.example")

    print("\n" + "=" * 64)
    print("   SERP-RELAY IS INSTALLED AND READY!")
    print("   Shortcut: Ctrl+Alt+R")
    print("   Voice wake: Say 'Relay' or press Ctrl+Alt+Space")
    print("   Powered by SerpApi Live-World Search & Real-Time Data")
    print("=" * 64 + "\n")

    speak("SERP-Relay is installed and ready. Starting now.")

    if relay_exe.exists():
        print("Starting SERP-Relay in background...")
        subprocess.Popen([str(relay_exe), "--toggle"], cwd=str(target_dir))

    time.sleep(2)
    print("You can close this window now.")


if __name__ == "__main__":
    main()
