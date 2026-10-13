# SNMP Visual Manager

A web-based GUI for net-snmp with live MIB browsing, device management, and walk/export capabilities.

## Features

- **Device Management** — Add/edit/delete SNMP devices (v1, v2c, v3)
- **MIB Module Browser** — Load/unload MIB modules from net-snmp MIB directory
- **Live Walk View** — Real-time walk results with progress
- **Export** — Structured text export matching net-snmp output format
- **Connection Testing** — Test device connectivity

## Quick Start

```bash
cd snmp_manager
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

Or on Windows:
```
run.bat
```

Then open http://127.0.0.1:8080

## Architecture

```
snmp_manager/
├── main.py              # FastAPI app entry
├── database.py          # SQLite layer (built-in sqlite3)
├── models.py            # Dataclasses
├── snmp/
│   ├── client.py        # pysnmp async client + MIB loader
│   ├── walk.py          # Walk engine with sessions
│   └── mib.py           # MIB manager
├── api/
│   ├── devices.py       # Device CRUD + test
│   ├── mibs.py          # MIB load/list/resolve
│   └── walk.py          # Walk start/stop/status/results/export
├── export/
│   └── formatter.py     # Text export formatter
└── static/
    └── index.html       # Single-file frontend (htmx + Alpine.js)
```

## Tech Stack

- **Backend:** FastAPI, pysnmp 7.x (async), pysmi (MIB compilation)
- **Database:** SQLite (built-in)
- **Frontend:** Single HTML file with htmx + Alpine.js (no build step)

## Export Format

Exports match the net-snmp text format:

```
Walk: system to 1.3.6.1.2.1.1, 7 - 192.168.1.1:161- SNMPv2c

[SNMP Agent]
IP Address = 192.168.1.1
Port = 161
...

[Query Parameters]
Type = Walk (6)
From = 1.3.6.1.2.1.1
To = 1.3.6.1.2.1.1
Start Time = 09-06-2026 18:07:22

[Query Results]
Response Time = 09-06-2026 18:07:23
Response Status = End of Walk

sysDescr.0 (DisplayString) = Linux Gateway Router 5.15
sysObjectID.0 (OID) = 1.3.6.1.4.1.8072.3.2.10
sysUpTime.0 (TimeTicks) = 12-04:33:20.00
...
```

## Desktop Application & Packaging

The application can run as a local web service or as a standalone native Windows desktop application bundled with **PyInstaller** and **PyWebView** (Edge WebView2) packaged via **Inno Setup**.

For complete instructions on building the native desktop installer, see the [BUILD.md](../BUILD.md) documentation.

## Roadmap

- **Phase 1 (MVP):** Device CRUD (v1/v2c/v3), MIB loading, walk, export ✅
- **Phase 2:** Application MIB Workspace, drag-and-drop MIB loading, recursive dependency resolution, reload & unload ✅
- **Phase 3:** MIB Object Catalog & Inspector (type, syntax, MAX-ACCESS, table indices, search) ✅
- **Phase 4:** Type-Aware SNMP GET and SET operations with safety checks and confirmation modal ✅
- **Phase 5:** End-to-end Playwright test suite & Standalone Windows Installer Packaging ([BUILD.md](../BUILD.md)) 🚀

## Requirements

- Python 3.11+
- net-snmp MIBs at `C:\net-snmp\share\snmp\mibs\` (configurable)