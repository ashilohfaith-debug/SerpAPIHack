"""Closest honest stand-in for "install on a clean PC" without a VM.

Copies the packaged app (dist/relay) to a fresh folder and runs it the way a new
user's machine would: no Python or dev folders on PATH, no Python env variables, an
empty user-data folder, empty model caches, and HTTP(S) proxies pointed at a dead
port so any attempt to reach the internet fails loudly. Then:

  1. DLL scan — every .exe/.pyd/.dll in the bundle is parsed and each DLL it imports
     must be either inside the bundle or a stock Windows DLL. Visual C++ runtime DLLs
     count as "missing" unless bundled, because a fresh Windows may not have them.
  2. `relay-cli --check --quiet` in that environment must pass every check.
  3. `relay.exe --start` (windowless) is launched, must stay up, write a clean log,
     and open no network connections; then this test instance is stopped.

It cannot reproduce a different Windows build or missing Windows features — a real
clean-VM run is still the release gate — but it catches the classic packaging faults.

    uv run python scripts/clean_machine_check.py
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
VC_RUNTIME = ("msvcp140", "vcruntime140", "concrt140", "vcomp140", "msvcp140_1",
              "msvcp140_2", "vcruntime140_1", "vccorlib140")


def pe_imports(path: Path) -> list[str]:
    """Names of DLLs a PE file imports (normal + delay-load), parsed directly."""
    data = path.read_bytes()
    if data[:2] != b"MZ":
        return []
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return []
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (112 if magic == 0x20B else 96)            # data directories
    sections = []
    sec = opt + opt_size
    for i in range(nsec):
        va, vsize, raw_size, raw_ptr = (struct.unpack_from("<I", data, sec + 40 * i + 12)[0],
                                        struct.unpack_from("<I", data, sec + 40 * i + 8)[0],
                                        struct.unpack_from("<I", data, sec + 40 * i + 16)[0],
                                        struct.unpack_from("<I", data, sec + 40 * i + 20)[0])
        sections.append((va, max(vsize, raw_size), raw_ptr))

    def off(rva):
        for va, size, raw in sections:
            if va <= rva < va + size:
                return rva - va + raw
        return None

    def cstr(o):
        end = data.index(b"\0", o)
        return data[o:end].decode("ascii", "replace")

    names = []
    for index, entry_size, name_field in ((1, 20, 12), (13, 32, 4)):   # imports, delay
        rva = struct.unpack_from("<I", data, dd + 8 * index)[0]
        o = off(rva) if rva else None
        while o is not None and o + entry_size <= len(data):
            name_rva = struct.unpack_from("<I", data, o + name_field)[0]
            if name_rva == 0:
                break
            no = off(name_rva)
            if no is not None:
                names.append(cstr(no).lower())
            o += entry_size
    return names


def dll_scan(bundle: Path) -> list[str]:
    present = {p.name.lower() for p in bundle.rglob("*") if p.suffix.lower() in
               (".dll", ".pyd", ".exe")}
    problems = []
    for f in bundle.rglob("*"):
        if f.suffix.lower() not in (".dll", ".pyd", ".exe"):
            continue
        for dll in pe_imports(f):
            if dll in present or dll.startswith(("api-ms-win-", "ext-ms-")):
                continue
            stem = dll.rsplit(".", 1)[0]
            if stem in VC_RUNTIME:
                problems.append(f"{f.relative_to(bundle)} needs {dll} (Visual C++ runtime) "
                                "— not bundled")
            elif not (SYSTEM32 / dll).exists():
                problems.append(f"{f.relative_to(bundle)} needs {dll} — not bundled and not "
                                "in Windows")
    return sorted(set(problems))


def clean_env(data_dir: Path, cache: Path) -> dict:
    keep = {k: v for k, v in os.environ.items() if k.upper() in (
        "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "USERNAME",
        "LOCALAPPDATA", "APPDATA", "HOMEDRIVE", "HOMEPATH", "PROGRAMDATA", "PATHEXT",
        "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "SYSTEMDRIVE")}
    keep["PATH"] = f"{SYSTEM32};{SYSTEM32.parent};{SYSTEM32 / 'WindowsPowerShell' / 'v1.0'}"
    keep["RELAY_DATA_DIR"] = str(data_dir)
    keep["HF_HOME"] = str(cache)
    keep["HTTP_PROXY"] = keep["HTTPS_PROXY"] = "http://127.0.0.1:9"
    keep["NO_PROXY"] = ""
    keep["RELAY_OFFLINE"] = "1"      # a bundled .env must not turn this offline proof online
    keep["RELAY_PALETTE"] = "0"      # no on-screen palette from this background test
    return keep


def main() -> int:
    src = ROOT / "dist" / "relay"
    if not (src / "relay-cli.exe").exists():
        print("No packaged build found — run packaging/build.ps1 first.")
        return 2
    (ROOT / "build").mkdir(exist_ok=True)       # same drive as dist; never fills up C:
    work = Path(tempfile.mkdtemp(prefix="relay_clean_", dir=str(ROOT / "build")))
    app = work / "Relay"
    shutil.copytree(src, app)
    data, cache = work / "userdata", work / "cache"
    data.mkdir()
    cache.mkdir()
    env = clean_env(data, cache)
    results = {}

    problems = dll_scan(app)
    results["DLL dependencies all present"] = not problems
    for p in problems[:15]:
        print("   ", p)

    r = subprocess.run([str(app / "relay-cli.exe"), "--check", "--quiet"], env=env,
                       cwd=str(work), capture_output=True, text=True, timeout=600)
    print(r.stdout[-2500:])
    results["--check passes on a clean profile"] = r.returncode == 0

    import psutil
    (data / ".onboarded").write_text("1", encoding="utf-8")    # short greeting only
    proc = subprocess.Popen([str(app / "relay.exe"), "--start"], env=env, cwd=str(work))
    conns = []
    try:
        deadline = time.time() + 45
        ready = False
        while time.time() < deadline and proc.poll() is None:
            log = data / "relay.log"
            if log.exists() and "mic capture started" in log.read_text(encoding="utf-8",
                                                                        errors="replace"):
                ready = True
                break
            time.sleep(1)
        time.sleep(5)
        alive = proc.poll() is None
        try:
            conns = [c for c in psutil.Process(proc.pid).net_connections(kind="inet")
                     if c.raddr and not str(c.raddr.ip).startswith(("127.", "::1"))]
        except psutil.Error:
            pass
        results["windowless relay.exe starts and stays up"] = ready and alive
        results["no internet connections while running"] = not conns
        log_text = (data / "relay.log").read_text(encoding="utf-8", errors="replace") \
            if (data / "relay.log").exists() else ""
        errors = [ln for ln in log_text.splitlines() if " ERROR " in ln or "Traceback" in ln]
        results["start-up log has no errors"] = not errors
        for ln in errors[:5]:
            print("   ", ln[:160])
    finally:
        if proc.poll() is None:
            proc.terminate()                       # our own test instance only
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("\nClean-profile check of the packaged app:")
    for k, v in results.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    ok = all(results.values())
    if "--keep" in sys.argv:
        print("PASSED" if ok else "FAILED", f"(scratch copy kept: {work})")
    else:
        time.sleep(1)                              # let the test instance release files
        shutil.rmtree(work, ignore_errors=True)    # ~600 MB: never leave it behind
        print("PASSED" if ok else "FAILED", "(scratch copy removed; --keep to inspect)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
