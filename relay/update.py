"""In-place auto-update mechanism for Relay across Windows PCs.

Supports:
1. Binary auto-update: Checks GitHub releases / repository for newer version,
   downloads the updated relay.exe, renames current executable to relay.exe.old,
   places the new binary, and restarts seamlessly.
2. Git-based auto-update: If the machine was installed via git clone, performs
   a fast background `git pull` and sync.
3. Spoken commands: "Relay, check for updates" or "Relay, update".
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from relay import __version__
from relay.diagnostics import get_logger

log = get_logger("update")

GITHUB_REPO = "nagasaipradhyumnapoola/relay"
API_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RAW_VERSION_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/pyproject.toml"


def get_current_version() -> str:
    return __version__


def parse_version_tuple(v: str) -> tuple[int, ...]:
    cleaned = v.lstrip("v").strip()
    parts = []
    for p in cleaned.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_for_updates() -> dict:
    """Check GitHub for newer versions. Returns dict with:
    { 'has_update': bool, 'current': str, 'latest': str, 'download_url': str, 'notes': str }
    """
    res = {
        "has_update": False,
        "current": __version__,
        "latest": __version__,
        "download_url": "",
        "notes": "",
    }
    
    # 1. Try GitHub Releases API
    try:
        req = urllib.request.Request(
            API_RELEASE_URL,
            headers={"User-Agent": f"RELAY-Updater/{__version__}", "Accept": "application/vnd.github.v3+json"}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                tag = data.get("tag_name", "").lstrip("v")
                if tag and parse_version_tuple(tag) > parse_version_tuple(__version__):
                    res["has_update"] = True
                    res["latest"] = tag
                    res["notes"] = data.get("body", "")
                    for asset in data.get("assets", []):
                        name = asset.get("name", "").lower()
                        if name in ("relay.exe", "relay-setup.exe", "relay.zip"):
                            res["download_url"] = asset.get("browser_download_url", "")
                            break
                    return res
    except Exception as e:
        log.debug(f"GitHub Releases check error: {e}")

    # 2. Fallback: Check raw repository pyproject.toml
    try:
        req = urllib.request.Request(
            RAW_VERSION_URL,
            headers={"User-Agent": f"RELAY-Updater/{__version__}"}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status == 200:
                text = resp.read().decode("utf-8")
                for line in text.splitlines():
                    if line.strip().startswith('version = "'):
                        remote_v = line.split('"')[1]
                        if parse_version_tuple(remote_v) > parse_version_tuple(__version__):
                            res["has_update"] = True
                            res["latest"] = remote_v
                            res["download_url"] = f"https://github.com/{GITHUB_REPO}/releases/latest/download/relay.exe"
                        return res
    except Exception as e:
        log.debug(f"Raw repo check error: {e}")

    return res


def is_git_install() -> bool:
    app_dir = Path(__file__).resolve().parent.parent
    return (app_dir / ".git").exists() or (app_dir.parent / ".git").exists()


def update_git_install() -> tuple[bool, str]:
    """Run git pull for source / git installs."""
    app_dir = Path(__file__).resolve().parent.parent
    if not (app_dir / ".git").exists() and (app_dir.parent / ".git").exists():
        app_dir = app_dir.parent
    try:
        proc = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode == 0:
            if "Already up to date" in proc.stdout:
                return True, "Relay is already on the latest commit."
            return True, "Relay updated successfully from git repository."
        return False, f"Git pull failed: {proc.stderr[:100]}"
    except Exception as e:
        return False, f"Git update error: {str(e)[:100]}"


def apply_binary_update(download_url: str, speak_cb=None) -> bool:
    """Download updated relay.exe, rename running exe to .old, place new exe, and restart."""
    if not getattr(sys, "frozen", False):
        if is_git_install():
            ok, msg = update_git_install()
            if speak_cb:
                speak_cb(msg)
            return ok
        if speak_cb:
            speak_cb("Auto-update is designed for packaged Relay installations or git clones.")
        return False

    current_exe = Path(sys.executable).resolve()
    temp_download = current_exe.with_suffix(".tmp")
    old_exe = current_exe.with_suffix(".old")

    if speak_cb:
        speak_cb("Downloading update. Please wait a moment.")

    try:
        # Download new binary
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": f"RELAY-Updater/{__version__}"}
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp, open(temp_download, "wb") as f:
            shutil.copyfileobj(resp, f)

        # On Windows, rename active exe, replace with downloaded exe
        if old_exe.exists():
            try:
                old_exe.unlink()
            except OSError:
                pass

        current_exe.rename(old_exe)
        temp_download.rename(current_exe)

        if speak_cb:
            speak_cb("Relay updated successfully. Restarting now.")

        # Restart updated Relay
        subprocess.Popen([str(current_exe), "--start"], cwd=str(current_exe.parent))
        sys.exit(0)
    except Exception as e:
        log.error(f"Binary update failed: {e}")
        if temp_download.exists():
            try:
                temp_download.unlink()
            except OSError:
                pass
        if speak_cb:
            speak_cb(f"Update failed: {str(e)[:80]}. Keeping current version.")
        return False


def handle_update_command(speak_cb=None) -> None:
    """Handle spoken or CLI update request."""
    if speak_cb:
        speak_cb("Checking for updates.")
    info = check_for_updates()
    if info["has_update"]:
        msg = f"A new version of Relay is available: version {info['latest']}."
        if speak_cb:
            speak_cb(msg)
        if info["download_url"]:
            apply_binary_update(info["download_url"], speak_cb=speak_cb)
        elif is_git_install():
            ok, gmsg = update_git_install()
            if speak_cb:
                speak_cb(gmsg)
    else:
        if is_git_install():
            ok, gmsg = update_git_install()
            if speak_cb:
                speak_cb(gmsg)
        else:
            if speak_cb:
                speak_cb(f"You are running the latest version of Relay, version {__version__}.")
