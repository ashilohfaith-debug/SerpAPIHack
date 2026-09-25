# RELAY — packaging & distribution

Goal: an ordinary user installs and runs RELAY **offline**, starts it without looking
(Ctrl+Alt+R), and never has to open a terminal.

## Two ways to run
**A. From this folder (works today, verified).** A sighted helper sets it up once:
```
uv venv --python 3.12 .venv
uv pip install -e ".[dev,voice,percept,daily]"
.venv\Scripts\python.exe -m relay --setup-models
RELAY.cmd --install            # desktop shortcut with Ctrl+Alt+R + Start-menu entry
RELAY.cmd --autostart on       # optional: start at sign-in
```
The shortcut runs the windowless interpreter (`pythonw -m relay --start`), so no console
appears; everything — including start-up problems — is spoken. Verified: shortcut
creation (target, arguments, Ctrl+Alt+R hotkey) and the full app lifecycle
(`scripts/live_app_check.py`).

**B. One-folder build (PyInstaller).**
```
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```
Installs PyInstaller, ensures models, runs the tests, builds `dist/relay/`, and copies
`models/` beside the exe. The build contains two launchers sharing one runtime:
- `relay.exe` — windowless, what the Ctrl+Alt+R shortcut starts;
- `relay-cli.exe` — console: `--check`, `--install`, `--demo-daily`, diagnostics.
In a frozen build `relay.config.models_dir()` resolves to `models/` **beside the exe**
(fixed in 0.2.0 — it previously pointed inside `_internal/`). `relay-cli --install`
points the shortcut at the windowless `relay.exe`.

`packaging/relay.spec` uses `collect_all` for the native packages (ctranslate2,
onnxruntime, piper, faster-whisper, rapidocr, sounddevice, soundfile, pycaw, pypdf),
declares the Win32/UIA hidden imports, and overrides the contributed webrtcvad hook
(`packaging/hooks/`) because RELAY uses the `webrtcvad-wheels` fork.

**Built and checked on the development laptop (0.2.1):** `dist/relay/` is 597 MB with
models. `scripts/clean_machine_check.py` copies it to a fresh folder and runs it with no
Python on PATH, an empty data folder, empty model caches and dead HTTP proxies: all 129
DLLs the bundle imports are inside it or part of Windows (the Visual C++ runtime is
bundled), `relay-cli --check` passes every check, and the windowless `relay.exe --start`
comes up, stays up, logs no errors and opens no internet connections. A real clean VM
(different Windows build, nothing ever installed) is still the release gate.

The build bundles only model files (voice `.onnx` + `.json`, the whisper folder) and
prefers the public-domain voice `en_US-ljspeech-medium`; if it isn't downloaded yet it
bundles the research-only Lessac voice and prints a warning not to distribute that build.

## Runtime layout (per user, no admin)
- App: this folder, or `dist/relay/`.
- Models: `models/` next to the app (Piper voice ~63 MB, whisper tiny.en ~75 MB).
- User data: `%LOCALAPPDATA%\RELAY` — preferences, notes, reminders, action journal,
  app catalogue cache, `relay.log`, optional `config.toml`.

## Single instance & lifecycle
`relay --start` acquires a single-instance lock; a second launch **says** "Relay is
already running" and exits. Shutdown ("quit Relay") stops the mic, hotkeys, dispatcher,
speech and database, and releases the lock.

## Commands
- `--start` (`--with-panel` also serves the accessible panel) · `--install` ·
  `--uninstall` · `--autostart on|off`
- `--setup-models` / `--models-status`
- `--check` (spoken health check) · `--say TEXT` · `--do "COMMAND"` · `--demo-daily`
- `--selftest` · `--voice-selftest` · `--acceptance` · `--observe` · `--capabilities`

## Installer & signing (release work)
- Signing: `packaging\sign.ps1 -Thumbprint <cert>` (or `-PfxPath`) signs and verifies both
  exes with SHA-256 and a timestamp. **Needs a code-signing certificate** (free options
  for open-source projects exist, e.g. SignPath Foundation; otherwise an OV certificate
  or a cloud signing service). Until then a *downloaded* copy shows SmartScreen's "More
  info → Run anyway"; a copy from a USB stick, or the from-source setup, does not.
- Installer: wrap `dist/relay/` in MSIX or Inno Setup (per-user, no admin) that also runs
  `relay-cli --install`.
- CI: run `packaginguild.ps1` on a clean Windows runner and publish the artifact + SBOM.

## Clean-machine install test (release gate)
On a fresh Windows VM with no Python: install the package, disable networking, press
Ctrl+Alt+R, and complete the offline acceptance flow (`docs/ACCEPTANCE.md`). **Not run
yet** — it requires a clean VM.
