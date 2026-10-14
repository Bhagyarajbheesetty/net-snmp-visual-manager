# Changelog

All notable changes to the **SNMP Visual Manager** (Net-SNMP GUI Management Tool) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-10-14

### Added
- **Intuitive SET Options with Integer Enum Hints & Template C Structured Guidance**:
  - Implemented automatic extraction of MIB enumeration hints (`SYNTAX INTEGER { label(val), ... }`) for SNMP SET operations.
  - **Template C Structured Guidance Card**: Dissects complex MIB descriptions into structured visual sections:
    - **Clean Summary**: Core statement of parameter purpose without run-on text.
    - **Interactive Quick-Fill SET Pills**: Clickable pills (`[1: Commit]`, `[2: Temporary Commit]`) that immediately fill and select the value.
    - **GET / Read Status Codes**: Clear tabular display of read status codes (e.g., `200 : Commit Successful`, `201 : Commit Successful and reboot`).
    - **Related OIDs**: Highlighted references to diagnostic/error objects (e.g., `sysMgmtCfgErrorMsg`).
    - **Operational / Timing Callouts**: Prominent warning callout for operations requiring delays or reboot intervals (e.g., commit operations needing 3s–60s).
  - **Smart Free-Text SET Extraction**: For MIB parameters without formal ASN.1 enums (e.g., `sysMgmtCfgCommit` with `SYNTAX Unsigned32`), automatically parses SET options and GET codes directly from description text, populating both the dropdown and quick-fill pills while preserving type safety (`type_char='u'` for `Unsigned32`).
  - Added new REST API endpoint `GET /api/operations/oid-details` that dynamically resolves syntax, enum dictionaries, structured description sections (`description_details`), parameter descriptions, default values (`DEFVAL`), and type flags for any target OID (numeric, instance `.0`, or symbolic name).
  - Redesigned the SNMP SET dialog with modern MIB browser conventions:
    - **Instance**: Target OID / symbol with live syntax inspection.
    - **Syntax Box**: Full ASN.1 syntax badge (e.g., `INTEGER {enable(1), disable(2)}`).
    - **Value Dropdown**: Smart selection of enum values (`enable (1)`, `disable (2)`, etc.) alongside an `"Another value"` option for custom integer input.
    - **Template C Guidance Card**: Structured guidance extracted directly from the MIB `DESCRIPTION`.
    - **Data Type**: Automatically locked to `INTEGER (i)` or `Unsigned32 (u)` according to syntax when an option is chosen to prevent type mismatch errors.
  - Added quick-access triggers for SET operations:
    - **Double-Click**: Double-clicking any row in the walk results table immediately opens the SET dialog for that OID instance with enum options pre-populated.
    - **MIB Tree Context Menu**: Right-clicking any object node in the hierarchical tree and selecting **SET...** opens the dialog with instance targeting (`.0` or `.1`).
  - Added unit test suite `tests/test_set_enum_hints.py` covering numeric OIDs, instance OIDs, symbolic names, free-text extraction on `sysMgmtCfgCommit`, API responses, and tree node structures (10/10 passed).
- **Safe Hash-Based Destination Re-Use in MIB Manager**:
  - Enhanced `check_destination_collision` in `UnifiedRegistry` to compare SHA-256 hashes of destination files. When an identical file already exists on disk from an existing installation or previous reload, it is safely reused without throwing false-positive overwrite collisions.
- **Smart Null-Terminated C-String Decoding**:
  - Added detection for null-padded `OctetString` values in `_format_value` (`snmp_manager/snmp/client.py`) so strings containing trailing `0x00` padding decode cleanly into ASCII text rather than hexadecimal dump format.
- **Smart Table Column Instance Resolution for SNMP GET**:
  - Implemented automatic fallback probing with `snmpgetnext` when an exact SNMP GET is requested on an un-instantiated table column (e.g., `linkProfileDDRSMinDataRate` / `1.3.6.1.4.1.841.1.1.1.1.1.7.1.5`).
  - Automatically resolves and displays the first valid row instance (e.g., `.1.1 = 11`) rather than reporting an unhelpful `No Such Instance` error.
- **Accurate MIB Table Column Detection (`is_column`)**:
  - Updated MIB symbol analysis to inspect `MibTableColumn` directly in symbol class hierarchy (MRO), correctly categorizing multi-index table columns and preventing incorrect `.0` scalar suffixes.
  - Added dedicated `📋` icon in the MIB Tree for columnar table objects.
- **Automated GitHub Release Publishing**:
  - Added `upload_release.py` script for automated creation of GitHub releases, tag management, and multi-part asset uploading for Windows installer binaries.

### Changed
- **MIB Tree Node Structure**:
  - Extended tree node dictionary in `get_tree()` (`snmp_manager/snmp/mib.py`) to include the parsed `enums` map directly for downstream frontend inspection.
- **Data Sanitization & Security**:
  - Replaced all local network IPs and physical hardware MAC addresses in test fixtures, mocks, and documentation with RFC documentation standards (`00:11:22:33:44:55` and `192.0.2.x` / `198.51.100.x`).
  - Preserved privacy and credential separation across all repository commits.

### Fixed
- **Playwright E2E Test Suite Robustness**:
  - Upgraded Playwright E2E test suites across all 6 test modules (`01_device_management` through `06_history_and_controls`) to dynamically resolve registered target devices, scope status indicator locators uniquely to `.content .status-dot`, align with `x-model` form bindings, and verify all 17 integration workflows with 100% pass rate.
- **MIB Tree Default Hierarchy Auto-Expansion**:
  - Expanded standard `mib-2` path (`1.3.6.1.2`, `1.3.6.1.2.1`) by default in the MIB Tree view alongside enterprise branches so standard MIB-II nodes (`system`, `interfaces`) are immediately visible upon application load.
- **Value Column Rendering Stability**:
  - Reverted invalid attribute quote escaping in `index.html` that previously caused Alpine.js template evaluation to fail and render walk results table values as blank.
- **Symbol Resolution in `snmptranslate` on Windows**:
  - Updated `translate_oid_details` to use `;` (semicolon) path separators and `-IR` random-access flags so bare and instance symbols (`httpsAccessControl.0`, `ifAdminStatus.1`) resolve reliably.

---

## [1.0.0-rc1] - 2026-10-13

### Added
- **Core SNMP Protocol Operations Engine**:
  - Full support for `SNMPv1`, `SNMPv2c`, and `SNMPv3` protocol versions.
  - Comprehensive SNMPv3 User-based Security Model (USM) support:
    - Authentication protocols: `MD5`, `SHA`, `SHA224`, `SHA256`, `SHA384`, `SHA512`.
    - Privacy/Encryption protocols: `DES`, `AES`, `AES192`, `AES256`.
  - Type-safe SNMP GET and SET operations with optional post-SET readback verification (`verify_get`).
  - Resilient `GETBULK` / `GETNEXT` walk engine with automatic timeout recovery: when agents fail or timeout on specific OIDs, the engine seamlessly steps past them while strictly preserving original sequential encounter order.
- **Authoritative Configuration & Registry Architecture**:
  - Thread-safe `UnifiedRegistry` backed by `%USERPROFILE%\.snmp-manager\register.json` with atomic temp-file replace writes.
  - Strict data architecture separation: configuration and registrations live in `register.json`, while operational execution history lives in SQLite `snmp_manager.db`.
  - Canonical IPv4 and IPv6 address validation with duplicate IP prevention across device registrations.
- **Advanced MIB Manager & Object Tree**:
  - Integrated 65+ standard IETF, IANA, and Net-SNMP packaged MIBs.
  - Safe external MIB file management: tracks application-managed copies and guarantees user original files are never deleted or modified.
  - Recursive `IMPORTS` dependency resolution and PySMI compilation staging.
  - Searchable MIB catalog and interactive hierarchical OID tree browser with node-level inspection (`SYNTAX`, `MAX-ACCESS`, `STATUS`, `DESCRIPTION`, and enum tables).
- **Syntax-Aware MIB Value Decoding Engine**:
  - Automatic translation of raw SNMP bytes into readable presentation values:
    - Enumerated integers (`Enum`): resolves integer to textual labels (e.g., `up (1)`, `down (2)`).
    - `RowStatus`: RFC 2579 state labels (`active (1)`, `notInService (2)`, etc.).
    - `MacAddress` / `PhysAddress`: standard colon-delimited hex formatting (`00:11:22:33:44:55`).
    - `TimeTicks`: human-readable time duration breakdowns (`days-HH:MM:SS.hundredths`).
    - `DisplayString`: ASCII decoding with fallback to hexadecimal representation for binary payloads.
    - Composite Multi-Index Tables: hierarchical index suffix parsing for columnar tables.
- **Export & Windows Native Integration**:
  - Structured text export format matching industry-standard MIB browser outputs.
  - Native Windows **Save-As** file dialog integration using Win32 API (`comdlg32.dll` / `GetSaveFileNameW`) for instant file saving.
  - Browser streaming download fallback for web client deployments.
- **Packaging & Installation**:
  - Standalone single-directory build specification (`net-snmp-manager.spec`) via PyInstaller with bundled Net-SNMP 5.9.5.2 binaries and OpenSSL DLLs.
  - Dual-mode application launcher (`desktop_app.py`): native desktop window using PyWebView (Edge WebView2) or headless web server.
  - Inno Setup Windows installer (`installer.iss`) with full clean-uninstall routines that stop running processes and completely purge `%USERPROFILE%\.snmp-manager\` while preserving external user MIBs.
- **Automated Test Infrastructure**:
  - Comprehensive test suites covering data architecture, duplicate IP rules, export downloads, MIB lifecycle, value decoding, walk ordering, and silent subprocess execution.

---

## [0.1.0] - 2026-10-10

### Added
- Initial project scaffolding: FastAPI backend and single-page reactive user interface.
- Integration with Net-SNMP 5.9.5.2 command-line utilities (`snmpget.exe`, `snmpset.exe`, `snmpwalk.exe`, `snmpbulkwalk.exe`, `snmptranslate.exe`).
- Basic device configuration and history tracking.
