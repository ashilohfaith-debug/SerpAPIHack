# PyInstaller spec for RELAY (Windows). Starting configuration — build + test on a
# clean Windows machine; native packages (ctranslate2, onnxruntime, piper) need their
# data/binaries collected, which is what collect_all handles below.
#
#   uv run pyinstaller packaging/relay.spec --noconfirm
#
# Produces a one-folder app with two launchers sharing one runtime:
#   dist/relay/relay.exe      windowless — what the Ctrl+Alt+R shortcut starts
#   dist/relay/relay-cli.exe  console    — self-tests, demos, --install, diagnostics
# Models are NOT bundled by this spec; build.ps1 copies models/ beside the exe (where
# relay.config.models_dir() looks in a frozen build), or run `relay-cli --setup-models`.

import os

from PyInstaller.utils.hooks import collect_all

# PyInstaller resolves relative spec paths against the spec's own folder
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821 (SPEC injected)
os.chdir(SPEC_DIR)

datas, binaries, hiddenimports = [], [], []
for pkg in ("ctranslate2", "onnxruntime", "piper", "piper_phonemize",
            "faster_whisper", "rapidocr_onnxruntime", "sounddevice", "soundfile",
            "pycaw", "pypdf"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# ship the accessible panel next to the package
datas += [("../frontend/panel.html", "frontend")]

hiddenimports += ["win32com", "win32com.client", "comtypes", "comtypes.client",
                  "uiautomation", "pywintypes", "pythoncom", "pyperclip", "pyautogui",
                  "mss", "psutil"]

a = Analysis(
    ["../relay/__main__.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=["hooks"],          # local overrides (webrtcvad-wheels metadata)
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="relay",
          console=False, disable_windowed_traceback=False)
exe_cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="relay-cli",
              console=True, disable_windowed_traceback=False)
coll = COLLECT(exe, exe_cli, a.binaries, a.datas, name="relay")
