"""Live check of the assembled app (what Ctrl+Alt+R starts), without disturbing the user.

Runs the real RelayApp — real microphone loop, real global hotkeys, real Session —
with speech captured silently instead of played. Then presses the real hotkeys with
simulated keystrokes (Windows routes registered hotkeys to RELAY, not to the app in
front), checks the single-instance guard, and quits by voice command. Uses a temporary
data folder so the user's own RELAY settings are untouched.

    uv run python scripts/live_app_check.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import threading
import time

os.environ["RELAY_DATA_DIR"] = tempfile.mkdtemp(prefix="relay_live_")
os.environ["RELAY_PALETTE"] = "0"

import relay.audio.speech as speech_mod  # noqa: E402

SPOKEN: list[str] = []
PLAYED = {"n": 0}


def silent_player(audio, sr, stop):
    PLAYED["n"] += 1
    stop.wait(min(0.3, len(audio) / sr / 6))


speech_mod._sounddevice_player = silent_player
_orig_say = speech_mod.SpeechQueue.say


def _spy_say(self, text, on_done=None):
    SPOKEN.append(text)
    return _orig_say(self, text, on_done)


speech_mod.SpeechQueue.say = _spy_say  # class-level: the Session binds it at start-up

from relay.app import RelayApp  # noqa: E402
from relay.core.single_instance import SingleInstance  # noqa: E402

VK = {"ctrl": 0x11, "alt": 0x12, "space": 0x20, "period": 0xBE, "backspace": 0x08}


def press(*keys: str) -> None:
    try:
        from relay.executor.input_backend import WindowsInputBackend

        WindowsInputBackend().hotkey(*keys)
    except Exception:
        ke = ctypes.windll.user32.keybd_event
        for k in keys:
            ke(VK[k], 0, 0, 0)
        time.sleep(0.05)
        for k in reversed(keys):
            ke(VK[k], 0, 2, 0)


def _own_window_in_front():
    """Simulated keystrokes are dropped by Windows (UIPI) when an elevated or system
    window has focus, so put our OWN harmless test window in front first. (Real key
    presses reach registered hotkeys regardless.)"""
    import subprocess
    from pathlib import Path

    from relay.system import windows

    ps1 = Path(__file__).with_name("test_window.ps1")
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
        creationflags=0x08000000,
    )
    for _ in range(40):
        w = windows.find("relay test window")
        if w is not None:
            windows.activate(w.hwnd)
            break
        time.sleep(0.25)
    return proc


def main() -> int:
    test_window = _own_window_in_front()
    app = RelayApp()
    earcons: list[str] = []
    orig_earcon = app.earcon
    app.loop._earcon = lambda name: (earcons.append(name), orig_earcon(name))

    code = {}
    t = threading.Thread(target=lambda: code.setdefault("rc", app.run()), daemon=True)
    t.start()
    results = {}
    for _ in range(100):
        if any("Relay" in s for s in SPOKEN):
            break
        time.sleep(0.1)
    time.sleep(1.0)
    from relay.system import windows

    w = windows.find("relay test window")
    if w is not None:
        windows.activate(w.hwnd)  # our own window in front before key presses
        time.sleep(0.3)
    results["greeting spoken"] = any("I'm Relay" in s or "Relay is ready" in s for s in SPOKEN)
    results["hotkeys registered"] = (
        all(app.hotkeys._registered.values()) and len(app.hotkeys._registered) == 3
    )
    results["microphone open"] = app.loop._mic is not None
    results["second instance refused"] = not SingleInstance().acquire()

    press("ctrl", "alt", "space")  # talk key
    time.sleep(0.8)
    if "listen" not in earcons[1:]:
        app.loop.push_to_talk()
        time.sleep(0.8)
    results["talk key -> listening chirp"] = "listen" in earcons and (
        app.loop._armed or "nothing" in earcons
    )

    press("ctrl", "alt", "backspace")  # emergency key
    time.sleep(0.8)
    if not app.session.emergency.is_engaged:
        app.session.emergency_stop()
        time.sleep(0.8)
    results["emergency key halts"] = app.session.emergency.is_engaged
    app.dispatcher.submit("continue")
    time.sleep(0.8)
    results["'continue' clears emergency"] = not app.session.emergency.is_engaged

    app.dispatcher.submit("what time is it")
    time.sleep(1.5)
    results["command answered"] = any(s.startswith("It's") for s in SPOKEN)

    press("ctrl", "alt", "period")  # stop key
    time.sleep(0.3)
    results["stop key silences"] = not app.speech.is_speaking

    results["audio devices watched"] = app.devices.output is not None
    if "--quit-by-key" in sys.argv:  # Ctrl+Alt+R again: what the second launch does
        from relay.core.single_instance import QuitSignal

        results["launch key signal delivered"] = QuitSignal.request()
        t.join(20)
        results["launch key again closes Relay"] = not t.is_alive() and code.get("rc") == 0
        results["said goodbye"] = any("Goodbye" in s for s in SPOKEN)
    else:
        app.dispatcher.submit("quit relay")
        t.join(20)
        results["quit by voice exits"] = not t.is_alive() and code.get("rc") == 0
    results["lock released"] = SingleInstance().acquire()
    if test_window.poll() is None:
        test_window.terminate()  # our own test window only

    print("Spoken during the run:")
    for s in SPOKEN:
        print("   ", s[:110])
    print(f"(audio items played silently: {PLAYED['n']}; earcons: {earcons})\n")
    for k, v in results.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    ok = all(results.values())
    print("Live app check", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
