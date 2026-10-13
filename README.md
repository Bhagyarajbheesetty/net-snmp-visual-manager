# SNMP Visual Manager `v1.0.0`

[![Release](https://img.shields.io/badge/release-v1.0.0-blue.svg)](https://github.com/Bhagyarajbheesetty/net-snmp-visual-manager/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Net-SNMP](https://img.shields.io/badge/Net--SNMP-5.9.5.2-green.svg)](http://www.net-snmp.org/)

A modern, standalone Windows desktop and web application for **Net-SNMP** with live MIB browsing, syntax-aware OID value decoding, SNMPv1/v2c/v3 device management, real-time subtree walks, type-safe GET/SET operations, and structured text exports.

---

## Key Features

- **Device Management (`SNMPv1`, `SNMPv2c`, `SNMPv3`)**:
  - Full support for SNMPv3 USM security (`MD5`, `SHA`, `SHA256`, `DES`, `AES`) as well as community-based v1/v2c.
  - Canonical IPv4/IPv6 validation and duplicate IP protection.
  - Instant one-click connection testing (`sysDescr.0` probe).
- **Intelligent MIB Manager & Object Tree**:
  - Browse 65+ bundled standard IETF/IANA/Net-SNMP MIBs out of the box.
  - Drag-and-drop or load external vendor MIB files with automatic recursive `IMPORTS` dependency resolution.
  - Safe managed-copy tracking: never modifies or deletes your original external MIB files.
  - Interactive hierarchical OID tree and searchable MIB object catalog (`SYNTAX`, `MAX-ACCESS`, `STATUS`, `DESCRIPTION`, and enumeration maps).
- **Syntax-Aware MIB Value Decoding**:
  - Automatically resolves raw SNMP responses against loaded MIB definitions:
    - **Enumerated Integers (`Enum`)**: e.g., `up (1)`, `down (2)`, `enable (1)`
    - **`RowStatus`**: RFC 2579 labels (`active (1)`, `notInService (2)`, etc.)
    - **`MacAddress` / `PhysAddress`**: Colon-separated hex formatting (`00:11:22:33:44:55`)
    - **`TimeTicks`**: Formatted duration (`days-hours:minutes:seconds.hundredths`)
    - **`DisplayString` & Multi-Index Tables**: Clean ASCII decoding and composite table index resolution.
- **Resilient Live OID Walk & Export**:
  - Adaptive `GETBULK` / `GETNEXT` walk engine with automatic fallback when agents time out on specific objects.
  - Strict sequence preservation: timed-out or failed OIDs remain in their exact walk encounter position.
  - Structured text export matching industry-standard MIB browser output formats.
- **Type-Safe SNMP GET & SET**:
  - Direct `snmpget` and `snmpset` execution with post-SET readback verification.

---

## Architecture & Data Storage

```
c:\net-snmp\
├── desktop_app.py             # Native Windows desktop launcher (PyWebView + Edge WebView2)
├── net-snmp-manager.spec      # PyInstaller standalone packaging specification
├── installer.iss              # Inno Setup Windows installer & uninstaller script
├── BUILD.md                   # Detailed packaging and installer build guide
├── bin/                       # Bundled Net-SNMP CLI binaries & OpenSSL DLLs
├── share/snmp/mibs/           # Standard IETF / Net-SNMP MIB definitions
├── snmp_manager/              # Core application package
│   ├── main.py                # FastAPI application entry point
│   ├── database.py            # SQLite operational store (query_history)
│   ├── api/                   # REST API routers (devices, mibs, walk, operations)
│   ├── snmp/                  # SNMP engine, MIB parser, dependency resolver, UnifiedRegistry
│   ├── export/                # Structured walk text export formatter
│   └── static/                # Single-page reactive UI (Alpine.js + HTMX)
└── tests/                     # Automated unit & integration test suites
```

### Data Separation (`register.json` vs `snmp_manager.db`)
All runtime files are stored in `%USERPROFILE%\.snmp-manager\`:
- **`register.json`** (*Configuration & Registration Authority*):
  - Stores registered device configurations, managed MIB copy metadata, and application settings using thread-safe atomic writes.
- **`snmp_manager.db`** (*Operational History Store*):
  - Stores relational `query_history` execution logs and walk metrics.
- **Complete Uninstall Cleanup**:
  - Uninstalling via the Windows uninstaller automatically stops running application processes and cleans up `%USERPROFILE%\.snmp-manager\` (`register.json`, `snmp_manager.db`, logs, and staged caches) while keeping user-owned external MIB files untouched.

---

## Quick Start (Development)

### Prerequisites
- **Windows 10 / 11** (64-bit)
- **Python 3.11+**

### 1. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 2. Run as Web Application
```powershell
cd snmp_manager
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```
Open `http://127.0.0.1:8080` in your browser.

### 3. Run as Native Desktop Window
```powershell
python desktop_app.py
```

---

## Building the Standalone Executable & Windows Installer

No Python installation is required on target machines when using the built installer.

### 1. Build Standalone Executable (`PyInstaller`)
```powershell
pyinstaller --clean -y net-snmp-manager.spec
```
Output: `dist\NetSNMPManager\NetSNMPManager.exe`

### 2. Build Windows Setup Wizard (`Inno Setup 6`)
```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```
Output: `dist_installer\NetSNMPManager_Setup.exe`

See [BUILD.md](BUILD.md) for full packaging details.

---

## Running Automated Tests

Run all verification suites from the repository root:

```powershell
python tests/test_data_architecture_and_uninstall.py
python tests/test_device_duplicate_ip.py
python tests/test_walk_oid_ordering.py
python tests/test_mib_file_management.py
python tests/test_mib_lifecycle_buttons.py
python tests/test_mib_value_decoding.py
python tests/test_oid_counting.py
python tests/test_export_download.py
```

---

## Credits, Contributors & Legal Attribution

This application is built as a free, open-source community interface utilizing the **Net-SNMP** suite:

- **Net-SNMP Core Suite**: Version `5.9.5.2`
- **Net-SNMP Official Website**: [http://www.net-snmp.org/](http://www.net-snmp.org/)
- **Net-SNMP Developer Contact**: `net-snmp-coders@lists.sourceforge.net`

### Copyright Notice
> **All rights, copyrights, and intellectual property for Net-SNMP are strictly reserved by the original Net-SNMP authors, distributors, and contributors** (Carnegie Mellon University, UC Davis, Networks Associates Technology, Inc., Cambridge Broadband Ltd., Sun Microsystems, Sparta, Inc., Cisco Systems, Fabasoft R&D Software GmbH, Apple Inc., and the Net-SNMP community).
>
> Net-SNMP is licensed under the BSD-style Net-SNMP License. This application is an independent, non-commercial graphical management tool built for free public use.

### Authors & Contributors
- **Bhagyaraj Bheesetty** — Creator & Maintainer
- **Antigravity** (Google DeepMind) — Advanced Agentic AI Coding Assistant & Contributor

### Open-Source Libraries
We gratefully acknowledge the developers and maintainers of the following open-source projects:
- **PySNMP & PySMI** (BSD 2-Clause) — Ilya Etingof, LeXtudio Inc.
- **FastAPI** (MIT) — Sebastián Ramírez
- **Starlette & Uvicorn** (BSD 3-Clause) — Encode OSS Ltd.
- **pywebview** (BSD 3-Clause) — Roman Sakno
- **Alpine.js** (MIT) — Caleb Porzio

See [CREDITS.md](CREDITS.md) and [LICENSE](LICENSE) for full legal text and third-party notices.

---

## License

This application is open-source software licensed under the **[MIT License](LICENSE)**. Free for personal, academic, and commercial use. Net-SNMP components remain under their respective BSD-style Net-SNMP licenses.
