import shutil
from pathlib import Path

dist = Path("dist/relay")
(dist / "models/piper").mkdir(parents=True, exist_ok=True)
for name in ["en_US-ljspeech-medium.onnx", "en_US-ljspeech-medium.onnx.json"]:
    src = Path("models/piper") / name
    if src.exists():
        shutil.copy2(src, dist / "models/piper" / name)

whisper_src = Path("models/whisper")
if whisper_src.exists():
    shutil.copytree(whisper_src, dist / "models/whisper", dirs_exist_ok=True)

if Path(".env.example").exists():
    shutil.copy2(".env.example", dist / ".env.example")

if (dist / ".env").exists():
    (dist / ".env").unlink()

cmd_content = (
    "@echo off\r\n"
    "rem Double-click to install Relay: desktop + Start-menu shortcut (Ctrl+Alt+R), then start it.\r\n"
    'cd /d "%~dp0"\r\n'
    "relay-cli.exe --install\r\n"
    'start "" relay.exe --toggle\r\n'
)
(dist / "Install Relay.cmd").write_text(cmd_content, encoding="ascii")
print("Portable bundle successfully assembled in dist/relay.")
