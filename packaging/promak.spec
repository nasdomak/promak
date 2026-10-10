# PyInstaller recipe for the Windows program (no Python needed to run it).
#
#     pip install pyinstaller
#     pyinstaller packaging/promak.spec --noconfirm
#
# The result is the folder dist/Promak, which packaging/promak.iss turns into
# an installer.  Built by .github/workflows/release.yml on every version tag.
# -*- mode: python -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
# collect_submodules imports Promak, so its source must be importable now
sys.path.insert(0, str(ROOT))

datas = [(str(ROOT / "assets"), "assets")]
binaries = []
hiddenimports = collect_submodules("promak")
assert any(name.endswith(".renamer.tool") for name in hiddenimports), "Promak tools not found"
for package in ("yt_dlp", "faster_whisper", "ctranslate2", "imageio_ffmpeg", "vtracer", "curl_cffi", "pikepdf", "pypdfium2", "send2trash", "imagehash", "rapidocr", "onnxruntime", "docx", "openpyxl", "segno", "barcode"):
    try:
        d, b, h = collect_all(package)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Promak",
    icon=str(ROOT / "assets" / "promak.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Promak", upx=False)
