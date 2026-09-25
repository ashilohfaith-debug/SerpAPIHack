# PyInstaller spec for RELAY (Windows). Starting configuration — build + test on a
# clean Windows machine; native packages (ctranslate2, onnxruntime, piper) need their
# data/binaries collected, which is what collect_all handles below.
#
#   uv run pyinstaller packaging/relay.spec --noconfirm
#
# Produces dist/relay/relay.exe (one-folder — faster start, easier to inspect than
# one-file for a ~400 MB model-bearing app). Models are NOT bundled here; ship them
# beside the exe under models/ or fetch on first run with `relay --setup-models`.

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []
for pkg in ("ctranslate2", "onnxruntime", "piper", "piper_phonemize",
            "faster_whisper", "rapidocr_onnxruntime", "sounddevice", "soundfile",
            "webrtcvad"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# ship the accessible panel next to the exe
datas += [("../frontend/panel.html", "frontend")]

hiddenimports += ["win32com", "win32com.client", "comtypes", "uiautomation",
                  "pywintypes", "pythoncom"]

a = Analysis(
    ["../relay/__main__.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="relay",
          console=True, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, name="relay")
