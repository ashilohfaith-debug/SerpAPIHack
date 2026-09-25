# RELAY ships the maintained ``webrtcvad-wheels`` fork, whose distribution name differs
# from the module name, so the contributed hook's copy_metadata("webrtcvad") fails the
# build. This override (found first via hookspath) copies the fork's metadata instead.
from PyInstaller.utils.hooks import copy_metadata

try:
    datas = copy_metadata("webrtcvad-wheels")
except Exception:
    datas = []
