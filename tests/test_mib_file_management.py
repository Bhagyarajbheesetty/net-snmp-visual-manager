import os
import sys
import shutil
import tempfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT_DIR, "snmp_manager"))

from snmp.mib import mib_manager
from snmp.workspace import BUNDLED_MIBS_DIR, workspace_manager, find_bundled_mibs_dir
from snmp.registry import managed_registry, ManagedCopyRegistry, is_in_directory, compute_file_hash


def _create_sample_mib(module_name: str, imports_from: str = None, extra_oid: str = "") -> str:
    imports_block = ""
    if imports_from:
        imports_block = f"""
IMPORTS
    customItem
        FROM {imports_from}
    OBJECT-TYPE
        FROM SNMPv2-SMI;
"""
    else:
        imports_block = """
IMPORTS
    enterprises
        FROM SNMPv2-SMI
    OBJECT-TYPE
        FROM SNMPv2-SMI;
"""

    return f"""{module_name} DEFINITIONS ::= BEGIN
{imports_block}

testRoot OBJECT IDENTIFIER ::= {{ 1 3 6 1 4 1 99999 }}

testItem OBJECT-TYPE
    SYNTAX      INTEGER
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Test item for verification"
    ::= {{ testRoot 1 }}

{extra_oid}
END
"""


def test_1_external_load_and_copy():
    """Load an external MIB using Browse and verify that a copy appears in Net-SNMP MIB directory."""
    temp_dir = tempfile.mkdtemp(prefix="snmp_test_ext_")
    try:
        mod_name = "TEST-EXT-1-MIB"
        orig_file = os.path.join(temp_dir, f"{mod_name}.txt")
        with open(orig_file, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod_name))

        orig_hash_before = compute_file_hash(orig_file)
        orig_mtime_before = os.path.getmtime(orig_file)

        # 1. Load external file
        res = mib_manager.load_file(orig_file)
        assert res.get("success"), f"load_file failed: {res.get('message')}"

        # 2. Verify original file remains completely unchanged
        assert os.path.isfile(orig_file), "Original file must exist at source location"
        assert compute_file_hash(orig_file) == orig_hash_before, "Original file hash must be identical"
        assert os.path.getmtime(orig_file) == orig_mtime_before, "Original file mtime must be identical"

        # 3. Verify copy appears in Net-SNMP MIB directory
        dest_copy = os.path.join(BUNDLED_MIBS_DIR, f"{mod_name}.txt")
        assert os.path.isfile(dest_copy), f"Managed copy must exist at {dest_copy}"
        assert managed_registry.is_managed_copy(dest_copy), "Copied file must be tracked as managed"
        assert managed_registry.is_managed_module(mod_name), f"Module {mod_name} must be tracked as managed"

        # 4. Verify tree contains loaded MIB
        tree = mib_manager.get_tree()
        assert any("testRoot" in str(n) or "testItem" in str(n) or "99999" in str(n) for n in tree)

        # 5. Cleanup
        unload_res = mib_manager.unload_module(mod_name)
        assert unload_res.get("success"), f"unload failed: {unload_res.get('message')}"
        assert not os.path.exists(dest_copy), "Managed copy must be removed from Net-SNMP directory after unload"
        assert os.path.isfile(orig_file), "Original file must still exist after unload"
        assert compute_file_hash(orig_file) == orig_hash_before, "Original file must remain untouched"

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_2_packaged_mibs_never_deleted_on_unload():
    """Verify that packaged MIB files are never deleted during unloading."""
    # Find any packaged MIB in BUNDLED_MIBS_DIR
    packaged_file = os.path.join(BUNDLED_MIBS_DIR, "RFC1213-MIB.txt")
    if not os.path.isfile(packaged_file):
        # Fall back to any .txt in BUNDLED_MIBS_DIR
        for f in os.listdir(BUNDLED_MIBS_DIR):
            if f.endswith(".txt") and not f.startswith("TEST-"):
                packaged_file = os.path.join(BUNDLED_MIBS_DIR, f)
                break

    assert os.path.isfile(packaged_file), f"Packaged file {packaged_file} must exist"
    info = workspace_manager.parse_mib_header(packaged_file)
    mod_name = info.module_name

    # Load packaged MIB
    res = mib_manager.load_file(packaged_file)
    # Check that packaged MIB is NOT tracked as application-managed copy
    assert not managed_registry.is_managed_module(mod_name), "Packaged MIB must not be registered as a managed copy"

    # Unload packaged MIB
    unload_res = mib_manager.unload_module(mod_name)
    assert unload_res.get("success")

    # CRITICAL: Verify packaged file still exists on disk!
    assert os.path.isfile(packaged_file), f"Packaged file {packaged_file} must NEVER be deleted during unload"


def test_3_multiple_loads_and_unloads():
    """Load and unload the same external MIB multiple times safely."""
    temp_dir = tempfile.mkdtemp(prefix="snmp_test_multi_")
    try:
        mod_name = "TEST-REPEAT-MIB"
        orig_file = os.path.join(temp_dir, f"{mod_name}.txt")
        with open(orig_file, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod_name))

        dest_copy = os.path.join(BUNDLED_MIBS_DIR, f"{mod_name}.txt")

        for iteration in range(3):
            # Load
            res = mib_manager.load_file(orig_file)
            assert res.get("success"), f"Load iteration {iteration} failed: {res.get('message')}"
            assert os.path.isfile(dest_copy), f"Copy must exist on iteration {iteration}"
            assert os.path.isfile(orig_file), f"Original must exist on iteration {iteration}"

            # Unload
            unres = mib_manager.unload_module(mod_name)
            assert unres.get("success"), f"Unload iteration {iteration} failed: {unres.get('message')}"
            assert not os.path.exists(dest_copy), f"Copy must be deleted on iteration {iteration}"
            assert os.path.isfile(orig_file), f"Original must remain untouched on iteration {iteration}"

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_4_shared_dependencies():
    """Load multiple MIBs that share supporting dependencies and ensure unloading one does not break the other."""
    temp_dir = tempfile.mkdtemp(prefix="snmp_test_deps_")
    try:
        dep_name = "TEST-DEP-MIB"
        user1_name = "TEST-USER1-MIB"
        user2_name = "TEST-USER2-MIB"

        dep_file = os.path.join(temp_dir, f"{dep_name}.txt")
        user1_file = os.path.join(temp_dir, f"{user1_name}.txt")
        user2_file = os.path.join(temp_dir, f"{user2_name}.txt")

        with open(dep_file, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(dep_name, extra_oid="customItem OBJECT-TYPE SYNTAX INTEGER MAX-ACCESS read-only STATUS current DESCRIPTION 'Item' ::= { testRoot 2 }"))

        with open(user1_file, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(user1_name, imports_from=dep_name))

        with open(user2_file, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(user2_name, imports_from=dep_name))

        # 1. Load USER1 (which resolves and loads DEP)
        res1 = mib_manager.load_file(user1_file)
        assert res1.get("success"), f"Load user1 failed: {res1.get('message')}"

        # 2. Load USER2 (which also relies on DEP)
        res2 = mib_manager.load_file(user2_file)
        assert res2.get("success"), f"Load user2 failed: {res2.get('message')}"

        dep_dest = os.path.join(BUNDLED_MIBS_DIR, f"{dep_name}.txt")
        assert os.path.isfile(dep_dest), "DEP copy must exist in Net-SNMP directory"

        # 3. Unload USER1
        un1 = mib_manager.unload_module(user1_name)
        assert un1.get("success")

        # DEP must STILL exist because USER2 depends on it!
        assert os.path.isfile(dep_dest), "Shared dependency must NOT be deleted while USER2 is still loaded"

        # Trying to unload DEP directly while USER2 is loaded should be blocked by dependency check
        un_dep = mib_manager.unload_module(dep_name)
        assert not un_dep.get("success"), "Unloading DEP should fail because USER2 is active"
        assert "required by active module" in un_dep.get("message")

        # 4. Unload USER2
        un2 = mib_manager.unload_module(user2_name)
        assert un2.get("success")

        # Now DEP can be unloaded
        un_dep_ok = mib_manager.unload_module(dep_name)
        assert un_dep_ok.get("success")
        assert not os.path.exists(dep_dest), "DEP copy should now be removed"

        # Originals must all still exist
        assert os.path.isfile(dep_file)
        assert os.path.isfile(user1_file)
        assert os.path.isfile(user2_file)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_5_destination_filename_collision():
    """Test that existing unmanaged files in destination are NEVER overwritten or deleted."""
    temp_dir = tempfile.mkdtemp(prefix="snmp_test_collision_")
    colliding_dest = os.path.join(BUNDLED_MIBS_DIR, "COLLISION-PROTECTED.txt")
    try:
        # Create an unmanaged file directly in BUNDLED_MIBS_DIR
        with open(colliding_dest, "w", encoding="utf-8") as f:
            f.write("-- Unmanaged pre-existing file\n")

        dest_hash_before = compute_file_hash(colliding_dest)

        # Create external file with same filename
        ext_file = os.path.join(temp_dir, "COLLISION-PROTECTED.txt")
        with open(ext_file, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib("COLLISION-PROTECTED-MIB"))

        # Try to load external file -> should report collision error
        res = mib_manager.load_file(ext_file)
        assert not res.get("success"), "Load must fail on collision with unmanaged file"
        assert "already exists in Net-SNMP directory" in res.get("message")

        # Verify existing file was NOT modified or deleted
        assert os.path.isfile(colliding_dest), "Destination file must still exist"
        assert compute_file_hash(colliding_dest) == dest_hash_before, "Destination file must be unmodified"

    finally:
        if os.path.isfile(colliding_dest):
            os.remove(colliding_dest)
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_6_missing_and_invalid_files():
    """Test error handling for missing and invalid files."""
    # 1. Missing file
    res = mib_manager.load_file("C:\\nonexistent_dir\\missing_mib.txt")
    assert not res.get("success")
    assert "not found" in res.get("message").lower()

    # 2. Invalid ASN.1 file
    temp_dir = tempfile.mkdtemp(prefix="snmp_test_invalid_")
    try:
        inv_file = os.path.join(temp_dir, "invalid.txt")
        with open(inv_file, "w", encoding="utf-8") as f:
            f.write("This is not a MIB file at all.\n")

        res_inv = mib_manager.load_file(inv_file)
        assert not res_inv.get("success")
        assert "not a valid ASN.1 MIB" in res_inv.get("message")

        # Verify no file was copied to BUNDLED_MIBS_DIR
        assert not os.path.exists(os.path.join(BUNDLED_MIBS_DIR, "invalid.txt"))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_7_application_restart_persistence():
    """Verify that file ownership tracking remains consistent across simulated application restart."""
    temp_dir = tempfile.mkdtemp(prefix="snmp_test_restart_")
    try:
        mod_name = "TEST-RESTART-MIB"
        orig_file = os.path.join(temp_dir, f"{mod_name}.txt")
        with open(orig_file, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod_name))

        # Load file
        res = mib_manager.load_file(orig_file)
        assert res.get("success")

        dest_copy = os.path.join(BUNDLED_MIBS_DIR, f"{mod_name}.txt")
        assert os.path.isfile(dest_copy)

        # Simulate restart by creating a new ManagedCopyRegistry instance
        new_registry = ManagedCopyRegistry(managed_registry.registry_file)
        assert new_registry.is_managed_module(mod_name), "New registry instance must track the managed module after restart"
        assert new_registry.is_managed_copy(dest_copy), "New registry instance must recognize the copied file"

        # Verify safe deletion via registry
        deleted = new_registry.safe_delete_managed_copies(mod_name, expected_base_dir=BUNDLED_MIBS_DIR)
        assert len(deleted) > 0, "Must safely delete the managed copy"
        assert not os.path.exists(dest_copy), "Copied file must be removed"
        assert os.path.isfile(orig_file), "Original file must remain untouched"

        # Clean mib_manager state
        mib_manager.unload_module(mod_name)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_8_mib_tree_and_status_synchronization():
    """Verify that MIB status and tree remain synchronized with actual loaded state."""
    temp_dir = tempfile.mkdtemp(prefix="snmp_test_sync_")
    try:
        mod_name = "TEST-SYNC-MIB"
        orig_file = os.path.join(temp_dir, f"{mod_name}.txt")
        with open(orig_file, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod_name))

        # Check before load: module not loaded
        modules_before = mib_manager.scan_mibs()
        assert not any(m.name == mod_name and m.loaded for m in modules_before)

        # Load
        res = mib_manager.load_file(orig_file)
        assert res.get("success")

        # After load: module status active
        modules_after = mib_manager.scan_mibs()
        matched = [m for m in modules_after if m.name == mod_name]
        assert len(matched) > 0, "Module must appear in scan_mibs"
        assert matched[0].loaded is True, "Module must be marked loaded"
        assert matched[0].status == "active", "Module status must be active"

        # Tree must contain the module's node
        tree_loaded = mib_manager.get_tree()
        assert any("testRoot" in str(n) or "99999" in str(n) for n in tree_loaded)

        # Unload
        mib_manager.unload_module(mod_name)

        # After unload: tree must NOT contain the module's node
        tree_unloaded = mib_manager.get_tree()
        assert not any("99999" in str(n) for n in tree_unloaded)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_9_api_endpoints_load_and_unload():
    """Verify FastAPI endpoints /api/mibs/load-file and /api/mibs/unload."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)

    temp_dir = tempfile.mkdtemp(prefix="snmp_test_api_")
    try:
        mod_name = "TEST-API-MIB"
        ext_file = os.path.join(temp_dir, f"{mod_name}.txt")
        with open(ext_file, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod_name))

        orig_hash = compute_file_hash(ext_file)

        # 1. POST /api/mibs/load-file
        resp = client.post("/api/mibs/load-file", json={"filepath": ext_file})
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data.get("success") is True

        dest_file = os.path.join(BUNDLED_MIBS_DIR, f"{mod_name}.txt")
        assert os.path.isfile(dest_file), "Managed copy must exist"
        assert compute_file_hash(ext_file) == orig_hash, "Original file must be untouched"

        # 2. GET /api/mibs/tree
        tree_resp = client.get("/api/mibs/tree")
        assert tree_resp.status_code == 200
        assert "99999" in tree_resp.text, "Tree must contain the test node"

        # 3. POST /api/mibs/unload
        un_resp = client.post("/api/mibs/unload", json={"module_name": mod_name})
        assert un_resp.status_code == 200
        assert un_resp.json().get("success") is True

        assert not os.path.exists(dest_file), "Managed copy must be removed"
        assert os.path.isfile(ext_file), "Original file must still exist"
        assert compute_file_hash(ext_file) == orig_hash, "Original file must be untouched"

        # 4. GET /api/mibs/tree after unload
        tree_after = client.get("/api/mibs/tree")
        assert "99999" not in tree_after.text, "Tree must no longer contain the test node"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_10_single_root_mibs_folder_resolution():
    """Verify that only the single root mibs/ directory is configured in packaging and resolved at runtime."""
    # 1. Verify installer.iss
    iss_path = os.path.join(ROOT_DIR, "installer.iss")
    assert os.path.isfile(iss_path)
    with open(iss_path, "r", encoding="utf-8") as f:
        iss_content = f.read()
    assert 'DestDir: "{app}\\mibs"' in iss_content, "installer.iss must package to {app}\\mibs"
    assert 'DestDir: "{app}\\share\\snmp\\mibs"' not in iss_content, "installer.iss must NOT have duplicate share\\snmp\\mibs"

    # 2. Verify net-snmp-manager.spec
    spec_path = os.path.join(ROOT_DIR, "net-snmp-manager.spec")
    assert os.path.isfile(spec_path)
    with open(spec_path, "r", encoding="utf-8") as f:
        spec_content = f.read()
    assert 'mibs_files.append((fpath, "mibs"))' in spec_content
    assert 'mibs_files.append((fpath, "share/snmp/mibs"))' not in spec_content, "spec file must NOT package duplicate share/snmp/mibs"

    # 3. Verify find_bundled_mibs_dir in simulated frozen environment
    temp_app = tempfile.mkdtemp(prefix="test_frozen_app_")
    try:
        mock_exe = os.path.join(temp_app, "NetSNMPManager.exe")
        with open(mock_exe, "w") as f:
            f.write("")
        mock_mibs = os.path.join(temp_app, "mibs")
        os.makedirs(mock_mibs, exist_ok=True)

        old_frozen = getattr(sys, "frozen", False)
        old_exe = sys.executable
        try:
            sys.frozen = True
            sys.executable = mock_exe
            resolved = find_bundled_mibs_dir()
            assert os.path.normpath(resolved) == os.path.normpath(mock_mibs), f"Expected {mock_mibs}, got {resolved}"
        finally:
            if old_frozen:
                sys.frozen = old_frozen
            else:
                delattr(sys, "frozen")
            sys.executable = old_exe
    finally:
        shutil.rmtree(temp_app, ignore_errors=True)


if __name__ == "__main__":
    tests = [
        test_1_external_load_and_copy,
        test_2_packaged_mibs_never_deleted_on_unload,
        test_3_multiple_loads_and_unloads,
        test_4_shared_dependencies,
        test_5_destination_filename_collision,
        test_6_missing_and_invalid_files,
        test_7_application_restart_persistence,
        test_8_mib_tree_and_status_synchronization,
        test_9_api_endpoints_load_and_unload,
        test_10_single_root_mibs_folder_resolution,
    ]
    passed = 0
    failed = 0
    print("=" * 60)
    print("RUNNING MIB FILE MANAGEMENT TEST SUITE")
    print("=" * 60)
    for t in tests:
        name = t.__name__
        try:
            t()
            print(f"[PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    if failed > 0:
        sys.exit(1)
