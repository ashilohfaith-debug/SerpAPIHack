# RELAY — packaging & distribution

Goal: an ordinary user installs and runs Essential mode **offline**, without manually
installing Python/Node or starting servers.

## Build (one-folder app)
From `app/`:
```
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```
This installs PyInstaller, ensures Essential models are present (`relay --setup-models`),
runs the tests, builds `dist/relay/relay.exe` from `packaging/relay.spec`, and copies
`models/` beside the exe so the app is offline-ready.

`packaging/relay.spec` uses `collect_all` for the native packages (ctranslate2,
onnxruntime, piper, faster-whisper, rapidocr, sounddevice, soundfile, webrtcvad) and
declares the Win32/UIA hidden imports. It is a **starting configuration**: the first
real build on a clean machine will likely surface one or two more hidden-import / data
files to add — that's expected for a native-heavy app and is why the build script runs
the test suite first.

## Runtime layout (per user)
- App: `dist/relay/` (portable) or an installed location.
- Models: `dist/relay/models/` (bundled) or downloaded on first run to
  `%LOCALAPPDATA%\RELAY\models` via `relay --setup-models`.
- User data (prefs, journal, memory, logs): `%LOCALAPPDATA%\RELAY`.

## Single instance & lifecycle
`relay --start` acquires a single-instance lock (`relay/core/single_instance.py`); a
second launch exits cleanly. Shutdown stops the mic, panel, speech and DB connection.

## Commands
- `relay --setup-models` / `--models-status` — ensure/report Essential models.
- `relay --start` — spoken onboarding + live voice loop (`--with-panel` also serves the panel).
- `relay --panel` — just the accessible panel.
- `relay --selftest`, `--voice-selftest`, `--observe`, `--capabilities`, `--demo-*`.

## Installer & signing (release work, not yet done)
- Wrap `dist/relay/` in an **MSIX** or an **Inno Setup / WiX** installer with a Start-menu
  entry and per-user install (no admin).
- **Code-sign** `relay.exe` and the installer with an EV/OV certificate to avoid
  SmartScreen warnings. (Requires a certificate — not available in this build.)
- Offline model handling: ship models in the package, or download+verify on first run.
- **Reproducible builds & CI:** run `packaging/build.ps1` in CI on a clean Windows runner;
  publish the artifact + SBOM.

## Clean-machine install test (release gate)
On a fresh Windows VM with no Python: install the package, disable networking, run
`relay --start`, and complete the offline acceptance flow (see `docs/ACCEPTANCE.md`).
This has **not** been run yet — it requires a clean VM.
