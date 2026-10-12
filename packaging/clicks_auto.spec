"""PyInstaller spec for Clicks-Auto (portable Windows build).

Build::

    pyinstaller packaging/clicks_auto.spec --noconfirm --clean

Produces ``dist/Clicks-Auto/`` containing ``Clicks-Auto.exe`` (GUI) and
``clicks-auto-cli.exe`` (console runner) plus Playwright's driver and, when
present, the bundled browser in ``ms-playwright``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / "clicks_auto"
VERSION = "1.0.1"

block_cipher = None

# --------------------------------------------------------------------- datas
datas = [
    (str(PACKAGE / "recorder" / "recorder.js"), "clicks_auto/recorder"),
    (str(ROOT / "assets" / "clicks-auto.ico"), "assets"),
    (str(ROOT / "docs" / "SCRIPT_FORMAT.md"), "docs"),
    (str(ROOT / "scripts" / "examples"), "examples"),
]

# Playwright: the driver folder (node + JS) is data, not Python modules.
playwright_dir: Path | None = None
try:
    import playwright

    playwright_dir = Path(playwright.__file__).parent
    datas.append((str(playwright_dir / "driver"), "playwright/driver"))
    # Ship a bundled Chromium when the build machine downloaded one.
    browsers_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if browsers_root and Path(browsers_root).exists() and os.environ.get("BUNDLE_PLAYWRIGHT_BROWSERS") == "1":
        datas.append((browsers_root, "ms-playwright"))
except Exception:  # pragma: no cover - playwright is a hard requirement
    pass

hiddenimports = [
    "playwright",
    "playwright.sync_api",
    "playwright._impl",
    "playwright._impl._driver",
    "pyee",
    "pyee.sync",
    "greenlet",
]

# Optional dependencies the code imports lazily (they may not exist).
for module in ("winreg",):
    if sys.platform == "win32":
        hiddenimports.append(module)

binaries = []
if sys.platform != "win32" and playwright_dir is not None:
    # Keep the bundled node binary executable on Linux/macOS (used for dev builds).
    node = playwright_dir / "driver" / "node"
    if node.exists():
        binaries.append((str(node), "playwright/driver"))

excludes = [
    "tkinter", "matplotlib", "numpy", "pandas", "scipy", "PIL.ImageQt",
    "PyQt6.QtQuick", "PyQt6.QtQml", "PyQt6.Qt3DCore", "PyQt6.QtWebEngineCore",
    "PyQt6.QtDesigner", "PyQt6.QtBluetooth", "PyQt6.QtNfc", "PyQt6.QtPositioning",
    "PyQt6.QtSerialPort", "PyQt6.QtSql", "PyQt6.QtTest", "PyQt6.QtCharts",
    "PyQt6.QtMultimedia", "PyQt6.QtOpenGL", "PyQt6.QtPdf", "PyQt6.QtSensors",
    "PyQt6.QtWebChannel", "PyQt6.QtWebSockets", "PyQt6.QtXml", "PyQt6.QtRemoteObjects",
    "PyQt6.QtSvgWidgets",  # keep PyQt6.QtSvg only if needed for icons
]

hiddenimports += collect_submodules("clicks_auto")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

version_file = ROOT / "packaging" / "version_info.txt"
version_arg = str(version_file) if version_file.exists() and sys.platform == "win32" else None
icon_path = ROOT / "assets" / "clicks-auto.ico"
icon_arg = str(icon_path) if icon_path.exists() else None

exe_gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Clicks-Auto",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
    version=version_arg,
)

cli_script = ROOT / "packaging" / "cli_entry.py"
if not cli_script.exists():
    cli_script.write_text(
        '"""Console entry point so the portable build can run scripts headlessly."""\n'
        "from clicks_auto.cli import main\n\n"
        'if __name__ == "__main__":\n'
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )

analysis_cli = Analysis(
    [str(cli_script)],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_cli = PYZ(analysis_cli.pure, analysis_cli.zipped_data, cipher=block_cipher)

exe_cli = EXE(
    pyz_cli,
    analysis_cli.scripts,
    [],
    exclude_binaries=True,
    name="clicks-auto-cli",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=icon_arg,
    version=version_arg,
)

coll = COLLECT(
    exe_gui,
    a.binaries,
    a.zipfiles,
    a.datas,
    exe_cli,
    analysis_cli.binaries,
    analysis_cli.zipfiles,
    analysis_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Clicks-Auto",
)
