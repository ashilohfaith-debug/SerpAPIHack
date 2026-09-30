"""Live desktop check against a window RELAY's test creates itself.

Opens a small "RELAY Test Window" (a PowerShell WinForms form with a text box, a
harmless button and a "Delete Everything" button), then drives it through the real
Session by voice commands: switch to it, read it with the reader, list the options,
click the harmless button (verified by the label changing), try the dangerous button
(must ask for the spoken phrase and NOT click), cancel, and close the window BY NAME.
Only this test window is touched.

    uv run python scripts/live_window_check.py      (uses scripts/test_window.ps1)
"""

from __future__ import annotations

import subprocess
import sys
import time

from relay.session import Session
from relay.system import windows


def main(ps1: str) -> int:
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", ps1]
    )
    lines: list[str] = []

    def speak(t: str) -> None:
        lines.append(t)
        print(f"  RELAY: {t}")

    for _ in range(40):
        if windows.find("relay test window"):
            break
        time.sleep(0.25)
    time.sleep(0.5)
    s = Session(speak=speak, db_path=":memory:")
    results = {}
    try:

        def run(cmd: str) -> list[str]:
            print(f"\nUSER: {cmd}")
            start = len(lines)
            s.handle(cmd)
            return lines[start:]

        out = run("switch to relay test window")
        time.sleep(0.5)
        fg = windows.foreground()
        results["switch"] = bool(fg and "relay test window" in fg.title.lower())
        out = run("read the page")
        joined = " ".join(out)
        results["read"] = "quick brown fox" in joined and "last one" in joined
        out = run("what are my options")
        results["options"] = any("Say Hello" in o for o in out)
        out = run("click say hello")
        after = s.worker.observe(3.0)
        label_changed = bool(
            after and any("hello clicked" in (e.name or "").lower() for e in after.elements)
        )
        results["click_verified"] = label_changed and any("Done" in o for o in out)
        out = run("click delete everything")
        results["danger_needs_phrase"] = s._pending is not None and any(
            "confirm delete" in o for o in out
        )
        run("cancel")
        after = s.worker.observe(3.0)
        results["danger_not_clicked"] = not any(
            "delete was clicked" in (e.name or "").lower()
            for e in (after.elements if after else [])
        )
        run("close relay test window")
        time.sleep(0.5)
        results["closed"] = windows.find("relay test window") is None
    finally:
        s.close()
        if proc.poll() is None:
            proc.terminate()  # our own test process only
    print("\nResults:")
    for k, v in results.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    ok = all(results.values())
    print("Live window check", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    from pathlib import Path

    default = Path(__file__).with_name("test_window.ps1")
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(default)))
