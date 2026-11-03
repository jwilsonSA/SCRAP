# -*- mode: python ; coding: utf-8 -*-

import glob
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


project_dir = Path(SPECPATH).resolve()
assets_dir = project_dir / "assets"
icon_path = assets_dir / "icon.ico"

datas = [(str(assets_dir), "assets")]
binaries = []

# These are bundled both to provide a complete Python runtime and to cover
# Tcl/Tk libraries for applications that import tkinter or use PyInstaller splash.
for dll in glob.glob(str(Path(sys.base_prefix) / "*.dll")):
    dll_name = Path(dll).name.lower()
    if dll_name.startswith(("python3", "tcl86", "tk86")):
        binaries.append((dll, "."))

dll_dir = Path(sys.base_prefix) / "DLLs"
if dll_dir.exists():
    for dll in dll_dir.glob("*.dll"):
        dll_name = dll.name.lower()
        if dll_name.startswith(("python3", "tcl86", "tk86", "_tkinter")):
            binaries.append((str(dll), "."))

# Tkinter package data and Tcl/Tk shared libraries, when the selected Python
# installation contains them. This also gives the EXE a complete tkinter runtime.
datas += collect_data_files("tkinter", include_py_files=True)
binaries += collect_dynamic_libs("tkinter")

# Standard Python installations store Tcl/Tk data under base_prefix/tcl or
# base_prefix/Lib/tcl*. Copy those trees with their correct relative layout.
tcl_root = Path(sys.base_prefix) / "tcl"
if tcl_root.exists():
    for child in tcl_root.iterdir():
        if child.is_dir():
            datas.append((str(child), f"tcl/{child.name}"))

lib_dir = Path(sys.base_prefix) / "Lib"
if lib_dir.exists():
    for child in lib_dir.glob("tcl*"):
        if child.is_dir():
            datas.append((str(child), f"Lib/{child.name}"))

a = Analysis(
    [str(project_dir / "app_gui.py")],
    pathex=[str(project_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["tkinter", "_tkinter"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SCRAP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(icon_path)] if icon_path.exists() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SCRAP",
)
