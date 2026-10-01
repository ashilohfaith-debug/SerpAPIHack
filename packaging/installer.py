"""Relay Setup & 1-Click Installer.

Double-click to install Relay to %LOCALAPPDATA%\\Programs\\Relay,
create Start Menu and Desktop shortcuts (Ctrl+Alt+R), and launch immediately.
"""

import os
import sys
import time
import shutil
import subprocess
from pathlib import Path

def print_banner():
    print("=" * 60)
    print("   RELAY — Accessible Windows Voice Assistant (v0.3.3)")
    print("=" * 60)
    print("\nInstalling Relay on your computer...\n")

def speak(text: str):
    """Speak using Windows SAPI voice so blind users hear progress immediately."""
    try:
        cmd = f'powershell -Command "Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.Speak(\'{text}\')"'
        subprocess.Popen(cmd, shell=True)
    except Exception:
        pass

def main():
    print_banner()
    speak("Installing Relay. Please wait a moment.")

    # Source directory (where installer is running or adjacent payload)
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent

    # Target directory: %LOCALAPPDATA%\Programs\Relay
    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    target_dir = local_app_data / "Programs" / "Relay"
    target_dir.mkdir(parents=True, exist_ok=True)

    print(f"Target folder: {target_dir}")

    # Find payload: dist/relay or current folder or adjacent zip
    src_payload = exe_dir / "dist" / "relay"
    if not src_payload.exists():
        src_payload = exe_dir / "relay"
    if not src_payload.exists():
        src_payload = exe_dir

    if (src_payload / "relay.exe").exists():
        print("Copying application files...")
        for item in src_payload.iterdir():
            if item.name.lower() in ("build", ".git", ".venv", "setup.exe", "relay-setup.exe"):
                continue
            dest = target_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
    else:
        # Check for zip
        zip_candidates = list(exe_dir.glob("*.zip")) + list((exe_dir / "downloads").glob("*.zip"))
        if zip_candidates:
            import zipfile
            zfile = zip_candidates[0]
            print(f"Extracting {zfile.name}...")
            with zipfile.ZipFile(zfile, "r") as z:
                z.extractall(target_dir.parent)

    print("Registering system shortcuts (Desktop & Start Menu with Ctrl+Alt+R)...")
    cli_exe = target_dir / "relay-cli.exe"
    relay_exe = target_dir / "relay.exe"

    if cli_exe.exists():
        try:
            subprocess.run([str(cli_exe), "--install"], check=True, capture_output=True, timeout=15)
            print("Shortcuts registered successfully.")
        except Exception as e:
            print(f"Shortcut warning: {e}")

    # Copy .env if available
    env_src = exe_dir / ".env"
    if env_src.exists():
        shutil.copy2(env_src, target_dir / ".env")
        shutil.copy2(env_src, local_app_data / "RELAY" / ".env")

    print("\n" + "=" * 60)
    print("   RELAY IS INSTALLED AND READY!")
    print("   Shortcut: Ctrl+Alt+R")
    print("   Voice wake: Say 'Relay' or press Ctrl+Alt+Space")
    print("=" * 60 + "\n")

    speak("Relay is installed and ready. Starting Relay now.")

    if relay_exe.exists():
        print("Starting Relay in background...")
        subprocess.Popen([str(relay_exe), "--toggle"], cwd=str(target_dir))
    
    time.sleep(2)
    print("You can close this window now.")

if __name__ == "__main__":
    main()
