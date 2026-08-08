# PyInstaller spec for the RearAware detection sidecar.
#
# Build (from the engine/ directory):
#   pyinstaller rearaware-engine.spec --noconfirm
#
# Output lands in engine/dist/rearaware-engine/ - an onedir build (not
# onefile), since onefile self-extracts to a temp dir on every single launch,
# which is a real startup-latency cost with torch/ultralytics in the mix.
# electron-builder bundles this whole folder as an extraResource; see
# desktop/src/main/sidecar.js's _resolveCommand() for how Electron finds the
# executable inside it once packaged.

import sys
from pathlib import Path

block_cipher = None

ENGINE_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = ENGINE_DIR.parent

a = Analysis(
    ["main.py"],
    pathex=[str(ENGINE_DIR)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "models" / "30-cfb.pt"), "models"),
        (str(PROJECT_ROOT / "assets"), "assets"),
    ],
    hiddenimports=[
        # Defensive - static analysis should already catch these via camera.py's
        # conditional imports, but they're cheap insurance against a build that
        # "succeeds" but is silently missing the actual virtual-cam backend.
        "pyvirtualcam._native_macos_obs_cmioextension",
        "pyvirtualcam._native_macos_obs_dal",
        "pyvirtualcam._native_windows_obs",
        "pyvirtualcam._native_windows_unity_capture",
        "pyvirtualcam._native_linux_v4l2loopback",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rearaware-engine",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # no GUI of its own - stdout/stderr are the protocol, see protocol.py
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="rearaware-engine",
)
