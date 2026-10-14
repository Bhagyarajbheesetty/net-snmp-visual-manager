import os
import json
import hashlib
import threading
from typing import List, Dict, Optional, Tuple, Set, Any
from dataclasses import dataclass, asdict
from datetime import datetime

REGISTRY_DIR = os.path.expanduser("~/.snmp-manager")
REGISTRY_FILE = os.path.join(REGISTRY_DIR, "register.json")
LEGACY_REGISTRY_FILE = os.path.join(REGISTRY_DIR, "managed_copies.json")


def is_in_directory(file_path: str, directory_path: str) -> bool:
    """Return True strictly if file_path is inside directory_path."""
    if not file_path or not directory_path:
        return False
    try:
        norm_file = os.path.realpath(os.path.abspath(file_path)).lower()
        norm_dir = os.path.realpath(os.path.abspath(directory_path)).lower()
        if norm_file == norm_dir:
            return False
        common = os.path.commonpath([norm_file, norm_dir]).lower()
        return common == norm_dir
    except (ValueError, Exception):
        return False


def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file for integrity tracking."""
    if not os.path.isfile(file_path):
        return ""
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


@dataclass
class ManagedCopyRecord:
    module_name: str
    original_path: str
    copied_paths: List[str]
    is_managed: bool = True
    loaded: bool = False
    file_hash: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ManagedCopyRecord":
        return cls(
            module_name=data.get("module_name", ""),
            original_path=data.get("original_path", ""),
            copied_paths=data.get("copied_paths", []),
            is_managed=data.get("is_managed", True),
            loaded=data.get("loaded", False),
            file_hash=data.get("file_hash", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class DeviceRecord:
    id: int
    name: str
    ip_address: str
    port: int = 161
    version: str = "v2c"
    read_community: str = "public"
    write_community: str = "private"
    retries: int = 2
    timeout: int = 2
    username: Optional[str] = None
    auth_protocol: Optional[str] = None
    auth_password: Optional[str] = None
    privacy_protocol: Optional[str] = None
    privacy_password: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceRecord":
        return cls(
            id=int(data.get("id", 0)),
            name=data.get("name", ""),
            ip_address=data.get("ip_address", ""),
            port=int(data.get("port", 161)),
            version=data.get("version", "v2c"),
            read_community=data.get("read_community", "public"),
            write_community=data.get("write_community", "private"),
            retries=int(data.get("retries", 2)),
            timeout=int(data.get("timeout", 2)),
            username=data.get("username"),
            auth_protocol=data.get("auth_protocol"),
            auth_password=data.get("auth_password"),
            privacy_protocol=data.get("privacy_protocol"),
            privacy_password=data.get("privacy_password"),
            created_at=data.get("created_at") or datetime.utcnow().isoformat(),
            updated_at=data.get("updated_at") or datetime.utcnow().isoformat(),
        )


class UnifiedRegistry:
    """
    Authoritative application registry stored in register.json.
    
    Responsibilities:
    - Device configurations and registration records.
    - Application-managed MIB file tracking and loaded states.
    - Application settings.
    
    Guarantees:
    - register.json is the single source of truth for registrations.
    - Thread-safe in-memory caching with atomic file persistence.
    - Zero duplication between register.json and snmp_manager.db.
    - Never delete or modify user's original MIB files.
    - Idempotent migration from legacy managed_copies.json or database.
    """

    def __init__(self, registry_file: str = REGISTRY_FILE):
        self.registry_file = registry_file
        self._lock = threading.RLock()
        self._records: Dict[str, ManagedCopyRecord] = {}  # module_name -> record
        self._devices: Dict[int, DeviceRecord] = {}        # device_id -> record
        self._settings: Dict[str, Any] = {}
        self._load()

    def _load(self):
        """Load records from register.json, with idempotent migration support."""
        with self._lock:
            self._records.clear()
            self._devices.clear()
            self._settings.clear()

            # 1. Primary: load register.json if present
            if os.path.isfile(self.registry_file):
                try:
                    with open(self.registry_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        if "devices" in data or "mibs" in data or "version" in data:
                            mibs_dict = data.get("mibs", {})
                            devs_dict = data.get("devices", {})
                            self._settings = data.get("settings", {})
                        else:
                            # Legacy format: top-level mibs dictionary
                            mibs_dict = data
                            devs_dict = {}

                        for mod, rec_dict in mibs_dict.items():
                            if isinstance(rec_dict, dict):
                                self._records[mod] = ManagedCopyRecord.from_dict(rec_dict)
                        for dev_id_str, dev_dict in devs_dict.items():
                            if isinstance(dev_dict, dict):
                                dev_rec = DeviceRecord.from_dict(dev_dict)
                                self._devices[dev_rec.id] = dev_rec
                    return
                except Exception as e:
                    print(f"Warning: Failed to load register.json: {e}")

            # 2. Idempotent migration: check for legacy managed_copies.json
            migrated = False
            legacy_file = os.path.join(os.path.dirname(self.registry_file), "managed_copies.json")
            if os.path.isfile(legacy_file):
                try:
                    with open(legacy_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        for mod, rec_dict in data.items():
                            if isinstance(rec_dict, dict):
                                self._records[mod] = ManagedCopyRecord.from_dict(rec_dict)
                        migrated = True
                except Exception as e:
                    print(f"Warning: Failed to migrate legacy managed_copies.json: {e}")

            # 3. Idempotent migration: check for legacy devices in SQLite database
            db_path = os.path.join(os.path.dirname(self.registry_file), "snmp_manager.db")
            if os.path.isfile(db_path):
                try:
                    import sqlite3
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='devices'")
                    if cur.fetchone():
                        rows = cur.execute("SELECT * FROM devices").fetchall()
                        for r in rows:
                            d = dict(r)
                            dev_rec = DeviceRecord.from_dict(d)
                            if dev_rec.id > 0:
                                self._devices[dev_rec.id] = dev_rec
                                migrated = True
                    conn.close()
                except Exception as e:
                    print(f"Warning: Failed to migrate legacy devices from db: {e}")

            # Persist migrated state to register.json
            if migrated:
                try:
                    self._save()
                except Exception as e:
                    print(f"Warning: Failed to persist migrated register.json: {e}")

    def _save(self):
        """Atomically persist tracking records to JSON file."""
        os.makedirs(os.path.dirname(self.registry_file), exist_ok=True)
        temp_file = f"{self.registry_file}.tmp.{os.getpid()}"
        try:
            data = {
                "version": "1.0",
                "devices": {str(k): v.to_dict() for k, v in sorted(self._devices.items())},
                "mibs": {k: v.to_dict() for k, v in self._records.items()},
                "settings": self._settings,
            }
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            for attempt in range(5):
                try:
                    os.replace(temp_file, self.registry_file)
                    break
                except (PermissionError, OSError):
                    if attempt == 4:
                        raise
                    import time
                    time.sleep(0.05)
        except Exception as e:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
            print(f"Error saving register.json: {e}")
            raise

    # -------------------------------------------------------------------------
    # Device Registration Management
    # -------------------------------------------------------------------------

    def normalize_ip(self, ip_str: str) -> str:
        """Validates and formats an IPv4/IPv6 address to canonical representation."""
        import ipaddress
        if not ip_str or not isinstance(ip_str, str) or not ip_str.strip():
            raise ValueError("IP address is required.")
        cleaned = ip_str.strip()
        try:
            ip_obj = ipaddress.ip_address(cleaned)
            return str(ip_obj)
        except ValueError:
            raise ValueError(f"Invalid IP address format: '{ip_str}'")

    def check_ip_exists(self, normalized_ip: str, exclude_device_id: Optional[int] = None) -> bool:
        """Return True if normalized_ip is already registered to another device."""
        with self._lock:
            for dev in self._devices.values():
                if exclude_device_id is not None and dev.id == exclude_device_id:
                    continue
                try:
                    existing_norm = self.normalize_ip(dev.ip_address)
                except Exception:
                    existing_norm = dev.ip_address.strip().lower()
                if existing_norm == normalized_ip:
                    return True
            return False

    def list_devices(self) -> List[dict]:
        """List all registered devices sorted alphabetically by name."""
        with self._lock:
            devs = [dev.to_dict() for dev in self._devices.values()]
            return sorted(devs, key=lambda d: d.get("name", "").lower())

    def get_device(self, device_id: int) -> Optional[dict]:
        """Get a single device by integer ID."""
        with self._lock:
            dev = self._devices.get(device_id)
            return dev.to_dict() if dev else None

    def add_device(self, device_data: dict) -> dict:
        """Register a new device record with unique IP enforcement and auto-increment ID."""
        with self._lock:
            raw_ip = device_data.get("ip_address", "")
            norm_ip = self.normalize_ip(raw_ip)

            for dev in self._devices.values():
                try:
                    existing_norm = self.normalize_ip(dev.ip_address)
                except Exception:
                    existing_norm = dev.ip_address.strip().lower()
                if existing_norm == norm_ip:
                    raise ValueError("A device with this IP address already exists.")

            existing_ids = list(self._devices.keys())
            new_id = max(existing_ids) + 1 if existing_ids else 1

            now = datetime.utcnow().isoformat()
            dev_rec = DeviceRecord(
                id=new_id,
                name=str(device_data.get("name", "")).strip(),
                ip_address=norm_ip,
                port=int(device_data.get("port", 161)),
                version=str(device_data.get("version", "v2c")),
                read_community=str(device_data.get("read_community", "public")),
                write_community=str(device_data.get("write_community", "private")),
                retries=int(device_data.get("retries", 2)),
                timeout=int(device_data.get("timeout", 2)),
                username=device_data.get("username"),
                auth_protocol=device_data.get("auth_protocol"),
                auth_password=device_data.get("auth_password"),
                privacy_protocol=device_data.get("privacy_protocol"),
                privacy_password=device_data.get("privacy_password"),
                created_at=now,
                updated_at=now,
            )
            self._devices[new_id] = dev_rec
            self._save()
            return dev_rec.to_dict()

    def update_device(self, device_id: int, updates: dict) -> Optional[dict]:
        """Update an existing device record with duplicate IP checking."""
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                return None

            if "ip_address" in updates:
                norm_ip = self.normalize_ip(updates["ip_address"])
                for other_id, other_dev in self._devices.items():
                    if other_id == device_id:
                        continue
                    try:
                        existing_norm = self.normalize_ip(other_dev.ip_address)
                    except Exception:
                        existing_norm = other_dev.ip_address.strip().lower()
                    if existing_norm == norm_ip:
                        raise ValueError("A device with this IP address already exists.")
                dev.ip_address = norm_ip

            if "name" in updates and updates["name"] is not None:
                dev.name = str(updates["name"]).strip()
            if "port" in updates and updates["port"] is not None:
                dev.port = int(updates["port"])
            if "version" in updates and updates["version"] is not None:
                dev.version = str(updates["version"])
            if "read_community" in updates and updates["read_community"] is not None:
                dev.read_community = str(updates["read_community"])
            if "write_community" in updates and updates["write_community"] is not None:
                dev.write_community = str(updates["write_community"])
            if "retries" in updates and updates["retries"] is not None:
                dev.retries = int(updates["retries"])
            if "timeout" in updates and updates["timeout"] is not None:
                dev.timeout = int(updates["timeout"])

            for v3_col in ["username", "auth_protocol", "auth_password", "privacy_protocol", "privacy_password"]:
                if v3_col in updates:
                    setattr(dev, v3_col, updates[v3_col])

            dev.updated_at = datetime.utcnow().isoformat()
            self._save()
            return dev.to_dict()

    def delete_device(self, device_id: int) -> bool:
        """Delete a device record by integer ID."""
        with self._lock:
            if device_id in self._devices:
                del self._devices[device_id]
                self._save()
                return True
            return False

    def clear_devices(self):
        """Clears all device registrations (useful for test isolation)."""
        with self._lock:
            self._devices.clear()
            self._save()

    # -------------------------------------------------------------------------
    # Settings Management
    # -------------------------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any):
        with self._lock:
            self._settings[key] = value
            self._save()

    # -------------------------------------------------------------------------
    # MIB Registration & Managed Copy Management
    # -------------------------------------------------------------------------

    def get_record(self, module_name: str) -> Optional[ManagedCopyRecord]:
        target = module_name.strip().lower()
        with self._lock:
            if module_name in self._records:
                return self._records[module_name]
            for mod, rec in self._records.items():
                if mod.strip().lower() == target:
                    return rec
            return None

    def get_record_by_original_path(self, orig_path: str) -> Optional[ManagedCopyRecord]:
        norm_orig = os.path.realpath(os.path.abspath(orig_path)).lower()
        with self._lock:
            for rec in self._records.values():
                if os.path.realpath(os.path.abspath(rec.original_path)).lower() == norm_orig:
                    return rec
        return None

    def get_record_by_copied_path(self, copied_path: str) -> Optional[ManagedCopyRecord]:
        norm_copy = os.path.realpath(os.path.abspath(copied_path)).lower()
        with self._lock:
            for rec in self._records.values():
                for cp in rec.copied_paths:
                    if os.path.realpath(os.path.abspath(cp)).lower() == norm_copy:
                        return rec
        return None

    def is_managed_copy(self, file_path: str) -> bool:
        """Return True if file_path is explicitly tracked as an application-managed copy."""
        return self.get_record_by_copied_path(file_path) is not None

    def is_managed_module(self, module_name: str) -> bool:
        """Return True if module_name is managed by this application."""
        rec = self.get_record(module_name)
        return rec is not None and rec.is_managed

    def check_destination_collision(self, original_path: str, destination_paths: List[str]) -> Tuple[bool, Optional[str]]:
        """
        Check if any destination path already exists and is NOT a managed copy of original_path.
        Returns (ok, error_message).
        If ok is False, copying must NOT proceed to avoid overwriting unmanaged files.
        """
        norm_orig = os.path.realpath(os.path.abspath(original_path)).lower()
        orig_hash = compute_file_hash(original_path)
        with self._lock:
            for dest in destination_paths:
                if not os.path.exists(dest):
                    continue
                # If destination file already has identical content, it's the exact same file and safe to reuse
                if orig_hash and os.path.isfile(dest):
                    dest_hash = compute_file_hash(dest)
                    if dest_hash == orig_hash:
                        continue
                # If it exists, verify if it is already tracked as a managed copy of the SAME original source
                norm_dest = os.path.realpath(os.path.abspath(dest)).lower()
                dest_rec = None
                for rec in self._records.values():
                    for cp in rec.copied_paths:
                        if os.path.realpath(os.path.abspath(cp)).lower() == norm_dest:
                            dest_rec = rec
                            break
                    if dest_rec:
                        break

                if dest_rec is None:
                    # File exists on disk but is NOT tracked by the application at all!
                    return False, (
                        f"Destination file '{os.path.basename(dest)}' already exists in Net-SNMP directory "
                        f"and is not an application-managed copy of this source file. Cannot overwrite existing file."
                    )

                # File is tracked: verify it belongs to the same original file
                rec_orig = os.path.realpath(os.path.abspath(dest_rec.original_path)).lower()
                if rec_orig != norm_orig:
                    return False, (
                        f"Destination file '{os.path.basename(dest)}' is currently managed for a different source file "
                        f"('{dest_rec.original_path}'). Cannot overwrite existing file."
                    )

        return True, None

    def register_copy(
        self,
        module_name: str,
        original_path: str,
        copied_paths: List[str],
        loaded: bool = False,
    ) -> ManagedCopyRecord:
        """Register application-managed copies of an external MIB file."""
        norm_orig = os.path.realpath(os.path.abspath(original_path))
        norm_copies = []
        for p in copied_paths:
            norm_p = os.path.realpath(os.path.abspath(p))
            # CRITICAL SAFETY CHECK: Copied path must NEVER be the original path
            if norm_p.lower() == norm_orig.lower():
                raise ValueError(f"CRITICAL SAFETY VIOLATION: Attempted to register original file as copied path: {p}")
            if norm_p not in norm_copies:
                norm_copies.append(norm_p)

        file_hash = compute_file_hash(norm_orig)
        record = ManagedCopyRecord(
            module_name=module_name,
            original_path=norm_orig,
            copied_paths=norm_copies,
            is_managed=True,
            loaded=loaded,
            file_hash=file_hash,
            created_at=datetime.utcnow().isoformat(),
        )

        with self._lock:
            self._records[module_name] = record
            self._save()

        return record

    def update_loaded_state(self, module_name: str, loaded: bool):
        with self._lock:
            rec = self._records.get(module_name)
            if rec:
                rec.loaded = loaded
                self._save()

    def remove_record(self, module_name: str) -> Optional[ManagedCopyRecord]:
        target = module_name.strip().lower()
        with self._lock:
            key_to_del = None
            for mod in list(self._records.keys()):
                if mod == module_name or mod.strip().lower() == target:
                    key_to_del = mod
                    break
            if key_to_del:
                rec = self._records.pop(key_to_del, None)
                self._save()
                return rec
            return None

    def safe_delete_managed_copies(
        self,
        module_name: str,
        expected_base_dir: Optional[str] = None,
    ) -> List[str]:
        """
        Safely deletes ONLY the files explicitly registered as application-managed copies
        for module_name. Never deletes or modifies the original file.
        Returns list of successfully deleted file paths.
        """
        rec = self.get_record(module_name)
        if not rec or not rec.is_managed:
            return []

        deleted_paths = []
        norm_orig = os.path.realpath(os.path.abspath(rec.original_path)).lower()

        for cpath in rec.copied_paths:
            norm_cpath = os.path.realpath(os.path.abspath(cpath)).lower()
            # Safety check 1: Never delete original user file
            if norm_cpath == norm_orig:
                print(f"SAFETY GUARD TRIGGERED: Refusing to delete original user file {cpath}")
                continue

            # Safety check 2: If expected_base_dir provided, ensure file is inside it
            if expected_base_dir and not is_in_directory(cpath, expected_base_dir):
                print(f"SAFETY GUARD TRIGGERED: File {cpath} is not inside expected directory {expected_base_dir}")
                continue

            # Safety check 3: File must exist
            if os.path.isfile(cpath):
                try:
                    os.remove(cpath)
                    deleted_paths.append(cpath)
                except Exception as e:
                    print(f"Warning: Failed to delete managed copy {cpath}: {e}")

        # Unregister record once deleted
        self.remove_record(module_name)
        return deleted_paths

    def list_all(self) -> List[ManagedCopyRecord]:
        with self._lock:
            return list(self._records.values())


# Aliases for backwards compatibility
ManagedCopyRegistry = UnifiedRegistry
managed_registry = UnifiedRegistry()
registry = managed_registry
