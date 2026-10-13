# BUILD & PACKAGING GUIDE: SNMP Visual Manager
## Standalone Desktop Distribution (PyInstaller + PyWebView + Inno Setup)

This document provides complete architectural specifications, step-by-step setup, configuration templates, and build commands for packaging the SNMP Visual Manager into a standalone, ready-to-use Windows desktop installer without requiring Python or Node.js on the end-user machine.

---

## 1. Architecture Overview

```
                      +------------------------------------------+
                      |         NetSNMPManager_Setup.exe         |
                      |            (Inno Setup Installer)        |
                      +------------------------------------------+
                                           |
                                installs into Program Files
                                           v
+---------------------------------------------------------------------------------+
| Windows Desktop Application Bundle (dist/NetSNMPManager/)                       |
|                                                                                 |
|  +--------------------+         +--------------------------------------------+  |
|  | NetSNMPManager.exe | ------> | desktop_app.py (PyWebView UI Host)         |  |
|  +--------------------+         +--------------------------------------------+  |
|                                        | spawns background thread               |
|                                        v                                        |
|                                 +--------------------------------------------+  |
|                                 | Uvicorn Server (FastAPI on 127.0.0.1:port) |  |
|                                 +--------------------------------------------+  |
|                                        |                  |                     |
|                                        v                  v                     |
|                                 pysnmp / pysmi      SQLite Database             |
|                                 Net-SNMP Tools      (~/.snmp-manager/)          |
+---------------------------------------------------------------------------------+
```

### Key Components
1. **Desktop Window Shell (`desktop_app.py`)**:
   - Uses `pywebview` with Microsoft Edge WebView2 (native to Windows 10 & 11).
   - Starts the FastAPI/Uvicorn server in a background Python thread on an available loopback port (e.g., dynamically selected or default `8080`).
   - Opens a clean desktop application window (no browser address bar, no browser tabs).
   - Manages graceful shutdown: closing the application window terminates Uvicorn and releases all socket/database locks.
2. **PyInstaller Packager (`net-snmp-manager.spec`)**:
   - Bundles the Python 3.11+ interpreter, dependencies (`fastapi`, `uvicorn`, `pysnmp`, `pysmi`, `pywebview`), static frontend files (`snmp_manager/static/index.html`), standard MIB files, and default templates into a single distribution directory (`dist/NetSNMPManager`).
3. **Inno Setup Installer (`installer.iss`)**:
   - Generates a production-grade Windows setup wizard (`NetSNMPManager_Setup.exe`).
   - Configures Desktop and Start Menu shortcuts.
   - Handles registry keys, standard uninstallation, and permission prompts.

---

## 2. Prerequisites & Environment Setup

### Required Tools (Build Machine)
* **Python**: 3.11+ (64-bit)
* **Inno Setup**: Version 6.x (Free, open-source Windows installer compiler)
  * Download: `https://jrsoftware.org/isdl.php`
  * Default path: `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`
* **Microsoft Edge WebView2**: Pre-installed on Windows 10 (version 1803+) and Windows 11.

### Python Packaging Dependencies
Install the required packaging modules on the build system:
```bash
pip install pyinstaller pywebview
```

---

## 3. Implementation Blueprint

### 3.1 Desktop Runner Entry Point (`desktop_app.py`)
This script serves as the executable entry point when bundled:
```python
import sys
import os
import threading
import socket
import uvicorn
import webview
from pathlib import Path

# Ensure root paths resolve properly inside PyInstaller frozen bundle
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

# Add snmp_manager to sys.path
sys.path.insert(0, str(BASE_DIR / "snmp_manager"))

def find_free_port(start_port=8080):
    """Find an open port on loopback."""
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start_port

def start_server(port):
    """Runs FastAPI via Uvicorn in background."""
    from main import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

def main():
    port = find_free_port()
    
    # Launch uvicorn daemon thread
    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()

    # Create native WebView2 desktop window
    window = webview.create_window(
        title="SNMP Visual Manager",
        url=f"http://127.0.0.1:{port}",
        width=1280,
        height=850,
        min_size=(1024, 680),
        text_select=True,
        confirm_close=True
    )
    
    # Start webview loop (blocks until window is closed)
    webview.start(gui="edgechromium", debug=False)
    sys.exit(0)

if __name__ == "__main__":
    main()
```

---

### 3.2 PyInstaller Specification (`net-snmp-manager.spec`)
The PyInstaller specification file controls file bundling, hidden imports, and metadata:

```python
# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect hidden modules needed by pysnmp, pysmi, and fastapi
hidden_imports = (
    collect_submodules("pysnmp") +
    collect_submodules("pysmi") +
    collect_submodules("uvicorn") +
    collect_submodules("fastapi") +
    collect_submodules("webview") +
    [
        "main",
        "database",
        "models",
        "snmp.client",
        "snmp.walk",
        "snmp.mib",
        "api.devices",
        "api.mibs",
        "api.walk",
        "api.operations",
        "export.formatter",
    ]
)

# Collect static files and standard MIB resources
datas = [
    ("snmp_manager/static", "snmp_manager/static"),
    ("share/snmp/mibs", "mibs"),
]

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
    upx=True,
    console=False,  # No cmd console popup
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
    upx=True,
    upx_exclude=[],
    name='NetSNMPManager',
)
```

---

### 3.3 Inno Setup Script (`installer.iss`)
Compile this script with Inno Setup Compiler (`ISCC.exe`) to generate `NetSNMPManager_Setup.exe`:

```pascal
[Setup]
AppId={{D37D0851-A3D2-4E90-B8B7-3D32F46A19AC}
AppName=SNMP Visual Manager
AppVersion=1.0.0
AppPublisher=Net-SNMP Tooling
DefaultDirName={autopf}\NetSNMPManager
DefaultGroupName=SNMP Visual Manager
AllowNoIcons=yes
OutputDir=dist_installer
OutputBaseFilename=NetSNMPManager_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\NetSNMPManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SNMP Visual Manager"; Filename: "{app}\NetSNMPManager.exe"
Name: "{group}\{cm:UninstallProgram,SNMP Visual Manager}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SNMP Visual Manager"; Filename: "{app}\NetSNMPManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NetSNMPManager.exe"; Description: "{cm:LaunchProgram,SNMP Visual Manager}"; Flags: nowait postinstall skipifsilent
```

---

## 4. Build & Distribution Workflow

When building the release installer, run the following steps in sequence:

### Step 1: Install Build Dependencies
```powershell
pip install pyinstaller pywebview
```

### Step 2: Build Executable Bundle via PyInstaller
```powershell
pyinstaller --clean net-snmp-manager.spec
```
*Output:* `dist/NetSNMPManager/` containing `NetSNMPManager.exe` and bundled libraries.

### Step 3: Compile Setup Wizard via Inno Setup
```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```
*Output:* `dist_installer/NetSNMPManager_Setup.exe` (~45 MB).

---

## 5. Runtime Storage & Data Isolation

To ensure non-destructive upgrades and avoid touching sensitive system directories:
* **Database File:** Stored at `%USERPROFILE%\.snmp-manager\snmp_manager.db`. Upgrading the app retains existing devices, histories, and preferences.
* **Workspace MIBs:** Stored at `%USERPROFILE%\.snmp-manager\workspace\mibs\`.
* **Standard MIBs:** Bundled read-only MIBs accessed via `{app}\mibs\`.
