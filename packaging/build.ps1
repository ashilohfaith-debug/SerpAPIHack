# RELAY Windows build script (PowerShell). Run from the app/ directory.
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"

Write-Host "== RELAY build =="
uv pip install --python .venv\Scripts\python.exe pyinstaller

Write-Host "== ensure models present (voice + speech model; no keys, no accounts) =="
.venv\Scripts\python.exe -m relay --setup-models

Write-Host "== run tests (must pass before packaging) =="
.venv\Scripts\python.exe -m pytest -q -m "not integration"
if ($LASTEXITCODE -ne 0) { throw "tests failed - not packaging" }

Write-Host "== software bill of materials =="
.venv\Scripts\python.exe scripts\sbom.py

Write-Host "== build one-folder app =="
.venv\Scripts\python.exe -m PyInstaller packaging\relay.spec --noconfirm --distpath "$PWD\dist" --workpath "$PWD\build"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "== copy models beside the exe (offline-ready; model files only) =="
$dist = "dist\relay"
New-Item -ItemType Directory -Force "$dist\models\piper" | Out-Null
$voice = "en_US-ljspeech-medium"                 # public domain, trained from scratch
if (-not (Test-Path "models\piper\$voice.onnx")) {
    $voice = "en_US-lessac-medium"
    Write-Warning "Public-domain voice missing; bundling $voice, whose training data is licensed for RESEARCH USE ONLY. Do not distribute this build publicly."
}
Copy-Item "models\piper\$voice.onnx", "models\piper\$voice.onnx.json" "$dist\models\piper\"
Copy-Item -Recurse -Force "models\whisper" "$dist\models\whisper"

Write-Host "== online settings (.env) =="
Copy-Item ".env.example" "$dist\.env.example"
if (Test-Path ".env") {
    Copy-Item ".env" "$dist\.env"
    Write-Warning "Bundled your .env into $dist - anyone who gets this folder can read those keys. For a public release put the keys behind a gateway (docs\AI_AND_VOICE.md)."
} else {
    Write-Host "No .env: this build is offline-only (voice commands, Piper voice)."
}

Write-Host "== check the packaged app on a clean profile =="
.venv\Scripts\python.exe scripts\clean_machine_check.py

Write-Host "Done. Portable app at $dist\relay.exe (voice: $voice)"
Write-Host "Next: sign the exes (packaging\sign.ps1), then wrap in an installer."
