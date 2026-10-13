# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect hidden modules needed by pysnmp, pysmi, pyasn1, uvicorn, fastapi, and pywebview
hidden_imports = (
    collect_submodules("pysnmp") +
    collect_submodules("pysmi") +
    collect_submodules("pyasn1") +
    collect_submodules("pyasn1_modules") +
    collect_submodules("uvicorn") +
    collect_submodules("fastapi") +
    collect_submodules("starlette") +
    collect_submodules("webview") +
    collect_submodules("pythonnet") +
    [
        "clr",
        "clr_loader",
        "sqlite3",
        "main",
        "database",
        "models",
        "snmp.client",
        "snmp.walk",
        "snmp.mib",
        "snmp.workspace",
        "snmp.process",
        "snmp.resolver",
        "snmp.registry",
        "api.devices",
        "api.mibs",
        "api.walk",
        "api.operations",
        "export.formatter",
        "export.file_dialog",
    ]
)

# Collect default MIBs (EXCLUDING PROXIM-MIB / PXM-SNMP per user request)
mibs_dir = os.path.abspath("share/snmp/mibs")
mibs_files = []
if os.path.isdir(mibs_dir):
    for f in os.listdir(mibs_dir):
        fpath = os.path.join(mibs_dir, f)
        if os.path.isfile(fpath):
            if any(k in f.upper() for k in ["PROXIM", "PXM"]):
                continue
            mibs_files.append((fpath, "mibs"))

# Collect Net-SNMP binaries and DLLs from bin/
bin_dir = os.path.abspath("bin")
bin_files = []
if os.path.isdir(bin_dir):
    for f in os.listdir(bin_dir):
        fpath = os.path.join(bin_dir, f)
        if os.path.isfile(fpath):
            bin_files.append((fpath, "bin"))

datas = [
    ("snmp_manager/static", "snmp_manager/static"),
    ("snmp_manager/static", "static"),
    ("LICENSE", "."),
    ("CREDITS.md", "."),
] + mibs_files + bin_files + collect_data_files("pysmi") + collect_data_files("webview")

a = Analysis(
    ['desktop_app.py'],
    pathex=['.', 'snmp_manager'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'test', 'unittest', 'playwright'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NetSNMPManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # Desktop mode without CMD popup
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='snmp_manager/static/icon.ico' if os.path.exists('snmp_manager/static/icon.ico') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='NetSNMPManager',
)
