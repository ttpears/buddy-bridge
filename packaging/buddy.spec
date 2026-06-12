# PyInstaller onedir build of the Windows tray app → buddy.exe
#
#   pip install -e ".[gui]" pyinstaller
#   pyinstaller packaging/buddy.spec
#
# Output: dist/buddy/  (buddy.exe + _internal/)  — zip the folder for release.
# Onedir (not onefile) so `buddy.exe hook` starts fast: the hook fires on every
# tool call and onefile would re-extract the bundle each run.
import os

root = os.path.dirname(SPECPATH)            # repo root (this spec lives in packaging/)

a = Analysis(
    [os.path.join(root, "buddybridge", "winapp.py")],
    pathex=[root],
    binaries=[],
    datas=[],
    # lazy/platform imports PyInstaller may miss by static analysis
    hiddenimports=["tkinter", "pystray._win32", "PIL._tkinter_finder"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="buddy",
    console=False,                          # windowed: no console window for the tray
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="buddy",
)
