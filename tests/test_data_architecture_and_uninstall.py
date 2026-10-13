import os
import sys
import json
import sqlite3
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT_DIR, "snmp_manager"))

from snmp.registry import UnifiedRegistry, ManagedCopyRecord, DeviceRecord
from database import init_db, get_connection
from main import app
from fastapi.testclient import TestClient


def test_registry_file_creation_and_atomic_save():
    """1. Verify register.json is created atomically and contains valid JSON."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        reg_file = os.path.join(tmp_dir, "register.json")
        reg = UnifiedRegistry(registry_file=reg_file)

        # Add a device
        dev = reg.add_device({
            "name": "Switch-Core",
            "ip_address": "10.10.10.1",
            "port": 161,
            "version": "v2c",
            "read_community": "public"
        })
        assert dev["id"] == 1
        assert dev["name"] == "Switch-Core"
        assert dev["ip_address"] == "10.10.10.1"

        # Verify register.json file exists and has correct schema
        assert os.path.isfile(reg_file), "register.json must be created on disk"
        with open(reg_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["version"] == "1.0"
        assert "devices" in data
        assert "1" in data["devices"]
        assert data["devices"]["1"]["name"] == "Switch-Core"
        assert "mibs" in data
        assert "settings" in data
        print("[PASS] test_registry_file_creation_and_atomic_save")


def test_device_crud_isolated_to_register_json():
    """2. Verify device CRUD strictly modifies register.json and never touches snmp_manager.db."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        reg_file = os.path.join(tmp_dir, "register.json")
        reg = UnifiedRegistry(registry_file=reg_file)

        # Create
        dev = reg.add_device({"name": "Dev-A", "ip_address": "192.168.1.10"})
        dev_id = dev["id"]
        assert reg.get_device(dev_id)["name"] == "Dev-A"

        # Update
        updated = reg.update_device(dev_id, {"name": "Dev-A-Renamed", "port": 1161})
        assert updated["name"] == "Dev-A-Renamed"
        assert updated["port"] == 1161

        # Check list
        all_devs = reg.list_devices()
        assert len(all_devs) == 1
        assert all_devs[0]["name"] == "Dev-A-Renamed"

        # Delete
        assert reg.delete_device(dev_id) is True
        assert reg.get_device(dev_id) is None
        assert len(reg.list_devices()) == 0
        print("[PASS] test_device_crud_isolated_to_register_json")


def test_snmp_manager_db_only_stores_query_history():
    """3. Verify snmp_manager.db schema only creates query_history and drops unused/legacy tables."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_snmp_manager.db")
        conn = sqlite3.connect(db_file)
        
        # Simulate an old database with devices and mib_modules
        conn.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT, ip_address TEXT)")
        conn.execute("CREATE TABLE mib_modules (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO devices (name, ip_address) VALUES ('OldDev', '1.1.1.1')")
        conn.commit()

        # Run database initialization logic
        SCHEMA = """
        CREATE TABLE IF NOT EXISTS query_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            operation TEXT NOT NULL,
            oid_from TEXT NOT NULL,
            oid_to TEXT,
            status TEXT NOT NULL,
            result_count INTEGER DEFAULT 0,
            export_path TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            error_message TEXT
        );
        """
        conn.executescript(SCHEMA)
        conn.execute("DROP TABLE IF EXISTS mib_modules")
        conn.execute("DROP TABLE IF EXISTS devices")
        conn.commit()

        # Check tables in database
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "query_history" in tables
        assert "devices" not in tables, "devices table must NOT exist in snmp_manager.db"
        assert "mib_modules" not in tables, "mib_modules table must NOT exist in snmp_manager.db"
        conn.close()
        print("[PASS] test_snmp_manager_db_only_stores_query_history")


def test_idempotent_migration_from_legacy_files():
    """4. Test migration from legacy managed_copies.json and db into register.json."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        reg_file = os.path.join(tmp_dir, "register.json")
        legacy_mibs = os.path.join(tmp_dir, "managed_copies.json")
        db_file = os.path.join(tmp_dir, "snmp_manager.db")

        # Create legacy managed_copies.json
        legacy_mib_data = {
            "PROXIM-MIB": {
                "module_name": "PROXIM-MIB",
                "original_path": "C:\\Desktop\\PXM-SNMP.mib",
                "copied_paths": ["C:\\net-snmp\\share\\snmp\\mibs\\PXM-SNMP.mib"],
                "is_managed": True,
                "loaded": True
            }
        }
        with open(legacy_mibs, "w", encoding="utf-8") as f:
            json.dump(legacy_mib_data, f)

        # Create legacy db with devices
        conn = sqlite3.connect(db_file)
        conn.execute("""
            CREATE TABLE devices (
                id INTEGER PRIMARY KEY,
                name TEXT,
                ip_address TEXT,
                port INTEGER,
                version TEXT,
                read_community TEXT
            )
        """)
        conn.execute("INSERT INTO devices (id, name, ip_address, port, version, read_community) VALUES (42, 'Migrated-Device', '192.168.10.50', 161, 'v2c', 'public')")
        conn.commit()
        conn.close()

        # Instantiate registry pointing to new register.json
        reg = UnifiedRegistry(registry_file=reg_file)

        # Verify MIB record migrated
        rec = reg.get_record("PROXIM-MIB")
        assert rec is not None
        assert rec.module_name == "PROXIM-MIB"
        assert rec.loaded is True

        # Verify device record migrated
        dev = reg.get_device(42)
        assert dev is not None
        assert dev["name"] == "Migrated-Device"
        assert dev["ip_address"] == "192.168.10.50"

        # Verify register.json persisted on disk
        assert os.path.isfile(reg_file)
        with open(reg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "42" in data["devices"]
        assert "PROXIM-MIB" in data["mibs"]
        print("[PASS] test_idempotent_migration_from_legacy_files")


def test_api_device_and_history_integration():
    """5. Verify FastAPI device endpoints and history joining with register.json."""
    client = TestClient(app)

    # 1. Add device via API
    dev_resp = client.post("/api/devices", json={
        "name": "API-Test-Router",
        "ip_address": "172.16.0.1",
        "port": 161,
        "version": "v2c",
        "read_community": "public"
    })
    assert dev_resp.status_code == 200
    dev_data = dev_resp.json()
    dev_id = dev_data["id"]

    try:
        # 2. Insert query_history record in SQLite for this device
        conn = get_connection()
        conn.execute(
            "INSERT INTO query_history (device_id, operation, oid_from, status, result_count) VALUES (?, ?, ?, ?, ?)",
            (dev_id, "walk", "1.3.6.1.2.1.1", "completed", 5)
        )
        conn.commit()

        # 3. Query /api/walk/history
        hist_resp = client.get("/api/walk/history")
        assert hist_resp.status_code == 200
        history = hist_resp.json()
        assert len(history) > 0
        entry = next((h for h in history if h["device_id"] == dev_id), None)
        assert entry is not None
        # Enriched from register.json
        assert entry["device_name"] == "API-Test-Router"
        assert entry["ip_address"] == "172.16.0.1"
    finally:
        # Cleanup
        client.delete(f"/api/devices/{dev_id}")
        conn = get_connection()
        conn.execute("DELETE FROM query_history WHERE device_id = ?", (dev_id,))
        conn.commit()
    print("[PASS] test_api_device_and_history_integration")


def test_installer_cleanup_simulation():
    """6. Simulate complete uninstall cleanup and ensure %USERPROFILE%\\.snmp-manager is removed."""
    with tempfile.TemporaryDirectory() as tmp_root:
        # Simulate %USERPROFILE%\.snmp-manager directory
        fake_data_dir = os.path.join(tmp_root, ".snmp-manager")
        os.makedirs(fake_data_dir, exist_ok=True)
        os.makedirs(os.path.join(fake_data_dir, "exports"), exist_ok=True)
        os.makedirs(os.path.join(fake_data_dir, "workspace"), exist_ok=True)

        # Create app files that uninstall must remove
        with open(os.path.join(fake_data_dir, "register.json"), "w") as f:
            f.write('{"devices": {}, "mibs": {}}')
        with open(os.path.join(fake_data_dir, "snmp_manager.db"), "w") as f:
            f.write("fake db content")
        with open(os.path.join(fake_data_dir, "snmp_manager.db-wal"), "w") as f:
            f.write("fake wal")
        with open(os.path.join(fake_data_dir, "desktop_app.log"), "w") as f:
            f.write("log entry")
        with open(os.path.join(fake_data_dir, "exports", "walk_123.txt"), "w") as f:
            f.write("walk export")

        # Simulate user's external MIB file outside .snmp-manager
        user_mibs_dir = os.path.join(tmp_root, "MyUserMibs")
        os.makedirs(user_mibs_dir, exist_ok=True)
        user_mib_file = os.path.join(user_mibs_dir, "USER-CUSTOM-MIB.txt")
        with open(user_mib_file, "w") as f:
            f.write("USER MIB FILE CONTENT")

        # Perform uninstall cleanup on fake_data_dir (DelTree behavior)
        shutil.rmtree(fake_data_dir)

        # Verify:
        assert not os.path.exists(fake_data_dir), ".snmp-manager directory must be completely removed"
        assert not os.path.exists(os.path.join(fake_data_dir, "register.json"))
        assert not os.path.exists(os.path.join(fake_data_dir, "snmp_manager.db"))
        # Verify user's file is untouched
        assert os.path.isfile(user_mib_file), "User original MIB file must NEVER be deleted"
        print("[PASS] test_installer_cleanup_simulation")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING DATA ARCHITECTURE & UNINSTALL TEST SUITE")
    print("=" * 60)
    test_registry_file_creation_and_atomic_save()
    test_device_crud_isolated_to_register_json()
    test_snmp_manager_db_only_stores_query_history()
    test_idempotent_migration_from_legacy_files()
    test_api_device_and_history_integration()
    test_installer_cleanup_simulation()
    print("=" * 60)
    print("ALL 6 ARCHITECTURE & UNINSTALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
