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
- `relay-cli.exe` — console: `--install`, `--sarvam-selftest`, `--demo-daily`, diagnostics.
In a frozen build `relay.config.models_dir()` resolves to `models/` **beside the exe**
(fixed in 0.2.0 — it previously pointed inside `_internal/`). `relay-cli --install`
points the shortcut at the windowless `relay.exe`.

`packaging/relay.spec` uses `collect_all` for the native packages (ctranslate2,
onnxruntime, piper, faster-whisper, rapidocr, sounddevice, soundfile, pycaw, pypdf),
declares the Win32/UIA hidden imports, and overrides the contributed webrtcvad hook
(`packaging/hooks/`) because RELAY uses the `webrtcvad-wheels` fork.

**Built and run on the development laptop (0.2.0):** PyInstaller 6 produced
`dist/relay/` (463 MB, 598 MB with models). The frozen `relay-cli.exe` passed
`--version`, `--models-status`, `--selftest`, `--voice-selftest` (Piper → faster-whisper
inside the bundle), `--demo-daily` (status, maths, notes, reminders), a live volume read
and a UI Automation screen description. Not yet run from the bundle: the windowless
`relay.exe --start` with speech (it speaks aloud) and anything on a clean machine.

## Runtime layout (per user, no admin)
- App: this folder, or `dist/relay/`.
- Models: `models/` next to the app (Piper voice ~63 MB, whisper tiny.en ~75 MB).
- User data: `%LOCALAPPDATA%\RELAY` — preferences, notes, reminders, action journal,
  app catalogue cache, `relay.log`, optional `config.toml` and `sarvam_key.txt`.

## Single instance & lifecycle
`relay --start` acquires a single-instance lock; a second launch **says** "Relay is
already running" and exits. Shutdown ("quit Relay") stops the mic, hotkeys, dispatcher,
speech and database, and releases the lock.

## Commands
- `--start` (`--with-panel` also serves the accessible panel) · `--install` ·
  `--uninstall` · `--autostart on|off`
- `--setup-models` / `--models-status`
- `--say TEXT` · `--do "COMMAND"` · `--demo-daily` · `--sarvam-selftest`
- `--selftest` · `--voice-selftest` · `--acceptance` · `--observe` · `--capabilities`

## Installer & signing (release work, not yet done)
- Wrap `dist/relay/` in an MSIX or Inno Setup installer (per-user, no admin), which
  also runs `relay-cli --install`.
- Code-sign both exes and the installer (needs an OV/EV certificate).
- Build in CI on a clean Windows runner; publish the artifact + SBOM.

## Clean-machine install test (release gate)
On a fresh Windows VM with no Python: install the package, disable networking, press
Ctrl+Alt+R, and complete the offline acceptance flow (`docs/ACCEPTANCE.md`). **Not run
yet** — it requires a clean VM.
