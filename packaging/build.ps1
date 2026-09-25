# RELAY Windows build script (PowerShell). Run from the app/ directory.
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"

Write-Host "== RELAY build =="
uv pip install --python .venv\Scripts\python.exe pyinstaller

Write-Host "== ensure Essential models present =="
.venv\Scripts\python.exe -m relay --setup-models

Write-Host "== run tests (must pass before packaging) =="
.venv\Scripts\python.exe -m pytest -q -m "not integration"

Write-Host "== build one-folder app =="
.venv\Scripts\python.exe -m PyInstaller packaging\relay.spec --noconfirm

Write-Host "== copy models beside the exe (offline-ready) =="
$dist = "dist\relay"
if (Test-Path "models") { Copy-Item -Recurse -Force "models" "$dist\models" }

Write-Host "Done. Portable app at $dist\relay.exe"
Write-Host "Next: sign relay.exe with a code-signing cert, then wrap in an MSIX/Inno installer."
