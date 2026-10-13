import os
import sys
import shutil
import tempfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT_DIR, "snmp_manager"))

from main import app
from fastapi.testclient import TestClient
from snmp.mib import mib_manager
from snmp.workspace import BUNDLED_MIBS_DIR, workspace_manager
from snmp.registry import managed_registry, compute_file_hash


def _create_sample_mib(module_name: str, imports_from: str = None, enterprise_oid: int = 88888) -> str:
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

testRoot OBJECT IDENTIFIER ::= {{ enterprises {enterprise_oid} }}

testItem OBJECT-TYPE
    SYNTAX      INTEGER
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Test object for {module_name}"
    ::= {{ testRoot 1 }}

END
"""


def test_button_reload_handles_filename_mismatch():
    """
    Simulates the exact user issue:
    A MIB file has a filename (MISMATCH-FILE.txt) different from its ASN.1 module name (MY-MISMATCH-MIB).
    - Loading it stages the canonical alias.
    - Reload button (/api/mibs/reload) must succeed without 'status is missing' error.
    - Status in /api/mibs must be loaded: True, status: 'active'.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_btn_reload_")
    client = TestClient(app)
    try:
        mod_name = "MY-MISMATCH-MIB"
        file_path = os.path.join(temp_dir, "MISMATCH-FILE.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod_name, enterprise_oid=77701))

        # 1. Load the file via API
        resp = client.post("/api/mibs/load-file", json={"filepath": file_path})
        assert resp.status_code == 200, f"Load failed: {resp.text}"
        data = resp.json()
        assert data.get("success") is True
        assert data.get("module_name") == mod_name

        # Verify state in /api/mibs
        list_resp = client.get("/api/mibs")
        mibs = list_resp.json()
        target = next((m for m in mibs if m["name"] == mod_name), None)
        assert target is not None, f"Module {mod_name} should appear in /api/mibs"
        assert target["loaded"] is True
        assert target["status"] == "active"

        # 2. Click Reload button (/api/mibs/reload)
        reload_resp = client.post("/api/mibs/reload", json={"module_name": mod_name})
        assert reload_resp.status_code == 200, f"Reload failed: {reload_resp.text}"
        reload_data = reload_resp.json()
        assert reload_data.get("success") is True, f"Reload returned failure: {reload_data}"
        assert f"Module '{mod_name}' reloaded successfully." in reload_data.get("message")

        # Verify state after reload remains active
        list_resp = client.get("/api/mibs")
        mibs = list_resp.json()
        target = next((m for m in mibs if m["name"] == mod_name), None)
        assert target["loaded"] is True
        assert target["status"] == "active"

        # Tree must contain the MIB object
        tree_resp = client.get("/api/mibs/tree")
        assert "77701" in tree_resp.text
    finally:
        # Cleanup
        client.post("/api/mibs/remove", json={"module_name": "MY-MISMATCH-MIB"})
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_button_unload_and_tree_synchronization():
    """
    Tests clicking Unload button:
    - Module transitions from Active to Staged.
    - Tree drops the module's nodes immediately.
    - Objects search no longer returns the module's objects.
    - User's original file is preserved.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_btn_unload_")
    client = TestClient(app)
    try:
        mod_name = "MY-UNLOAD-MIB"
        file_path = os.path.join(temp_dir, f"{mod_name}.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod_name, enterprise_oid=77702))

        orig_hash = compute_file_hash(file_path)

        # Load
        resp = client.post("/api/mibs/load-file", json={"filepath": file_path})
        assert resp.status_code == 200

        # Verify in tree
        tree_resp = client.get("/api/mibs/tree")
        assert "77702" in tree_resp.text

        # Click Unload button (/api/mibs/unload)
        unload_resp = client.post("/api/mibs/unload", json={"module_name": mod_name})
        assert unload_resp.status_code == 200
        assert unload_resp.json().get("success") is True

        # Verify /api/mibs shows unloaded / staged
        list_resp = client.get("/api/mibs")
        mibs = list_resp.json()
        target = next((m for m in mibs if m["name"] == mod_name), None)
        if target:
            assert target["loaded"] is False
            assert target["status"] == "staged"

        # Verify tree no longer contains the node
        tree_resp_after = client.get("/api/mibs/tree")
        assert "77702" not in tree_resp_after.text

        # Original file is intact
        assert os.path.isfile(file_path)
        assert compute_file_hash(file_path) == orig_hash
    finally:
        client.post("/api/mibs/remove", json={"module_name": "MY-UNLOAD-MIB"})
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_button_load_staged_to_active():
    """
    Tests clicking ⚡ Load button on a staged MIB:
    - Module transitions from Staged to Active.
    - Tree is updated with module's nodes.
    - Calling Load again or Unload responds correctly.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_btn_load_staged_")
    client = TestClient(app)
    try:
        mod_name = "MY-STAGED-MIB"
        file_path = os.path.join(temp_dir, f"{mod_name}.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod_name, enterprise_oid=77703))

        # First stage the file in workspace without activating it
        workspace_manager.stage_file_to_workspace(file_path)

        # In scan_mibs, it should appear as staged
        list_resp = client.get("/api/mibs")
        mibs = list_resp.json()
        target = next((m for m in mibs if m["name"] == mod_name), None)
        assert target is not None
        assert target["loaded"] is False
        assert target["status"] == "staged"

        # Tree does NOT contain it yet
        tree_before = client.get("/api/mibs/tree")
        assert "77703" not in tree_before.text

        # Click ⚡ Load button (/api/mibs/load)
        load_resp = client.post("/api/mibs/load", json={"module_name": mod_name})
        assert load_resp.status_code == 200, f"Load failed: {load_resp.text}"
        assert load_resp.json().get("success") is True

        # Now /api/mibs must show loaded: True, status: 'active'
        list_after = client.get("/api/mibs")
        target_after = next((m for m in list_after.json() if m["name"] == mod_name), None)
        assert target_after["loaded"] is True
        assert target_after["status"] == "active"

        # Tree must now contain the node
        tree_after = client.get("/api/mibs/tree")
        assert "77703" in tree_after.text
    finally:
        client.post("/api/mibs/remove", json={"module_name": "MY-STAGED-MIB"})
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_button_remove_cleans_workspace_and_managed_copy():
    """
    Tests clicking 🗑️ Remove button:
    - Can be called whether active or staged.
    - Deactivates from memory.
    - Removes managed copy from Net-SNMP directory.
    - Purges workspace files.
    - User's original file is preserved.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_btn_remove_")
    client = TestClient(app)
    try:
        mod_name = "MY-REMOVE-MIB"
        file_path = os.path.join(temp_dir, f"{mod_name}.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod_name, enterprise_oid=77704))

        orig_hash = compute_file_hash(file_path)

        # Load file
        resp = client.post("/api/mibs/load-file", json={"filepath": file_path})
        assert resp.status_code == 200

        # Click Remove button (/api/mibs/remove)
        rem_resp = client.post("/api/mibs/remove", json={"module_name": mod_name})
        assert rem_resp.status_code == 200
        assert rem_resp.json().get("success") is True

        # Verify not in loaded list
        loaded_list = client.get("/api/mibs/loaded").json()
        assert mod_name not in loaded_list

        # Original file is intact
        assert os.path.isfile(file_path)
        assert compute_file_hash(file_path) == orig_hash

        # Managed copy in BUNDLED_MIBS_DIR does not exist
        dest = os.path.join(BUNDLED_MIBS_DIR, f"{mod_name}.txt")
        assert not os.path.exists(dest)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_dependency_guard_prevents_premature_removal_or_unload():
    """
    Tests that if Child MIB is required by an active Parent MIB:
    - Calling unload or remove on Child MIB fails with 400 and clear message.
    - Child MIB remains active and in tree.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_btn_dep_")
    client = TestClient(app)
    try:
        child_mod = "MY-DEP-CHILD-MIB"
        parent_mod = "MY-DEP-PARENT-MIB"

        child_file = os.path.join(temp_dir, f"{child_mod}.txt")
        with open(child_file, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(child_mod, enterprise_oid=77705))

        parent_file = os.path.join(temp_dir, f"{parent_mod}.txt")
        with open(parent_file, "w", encoding="utf-8") as f:
            f.write(f"""{parent_mod} DEFINITIONS ::= BEGIN
IMPORTS
    enterprises
        FROM SNMPv2-SMI
    OBJECT-TYPE
        FROM SNMPv2-SMI
    testItem
        FROM {child_mod};

parentRoot OBJECT IDENTIFIER ::= {{ enterprises 77706 }}

parentItem OBJECT-TYPE
    SYNTAX      INTEGER
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Parent item"
    ::= {{ parentRoot 1 }}

END
""")

        # Load child first, then parent
        resp1 = client.post("/api/mibs/load-file", json={"filepath": child_file})
        assert resp1.status_code == 200
        resp2 = client.post("/api/mibs/load-file", json={"filepath": parent_file})
        assert resp2.status_code == 200

        # Try to unload child MIB while parent is active
        un_child = client.post("/api/mibs/unload", json={"module_name": child_mod})
        assert un_child.status_code == 400
        assert f"required by active module(s): {parent_mod}" in un_child.text

        # Try to remove child MIB while parent is active
        rem_child = client.post("/api/mibs/remove", json={"module_name": child_mod})
        assert rem_child.status_code == 400
        assert f"required by active module(s): {parent_mod}" in rem_child.text

        # Both remain active
        loaded_list = client.get("/api/mibs/loaded").json()
        assert child_mod in loaded_list
        assert parent_mod in loaded_list

        # Now unload parent first
        un_parent = client.post("/api/mibs/unload", json={"module_name": parent_mod})
        assert un_parent.status_code == 200

        # Now child can be unloaded successfully
        un_child2 = client.post("/api/mibs/unload", json={"module_name": child_mod})
        assert un_child2.status_code == 200
    finally:
        client.post("/api/mibs/remove", json={"module_name": parent_mod})
        client.post("/api/mibs/remove", json={"module_name": child_mod})
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_button_unload_all():
    """
    Tests clicking Unload All button (/api/mibs/unload-all):
    - All active modules are deactivated.
    - /api/mibs/loaded returns an empty list.
    - Tree clears all custom nodes.
    - Original files are preserved.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_btn_unload_all_")
    client = TestClient(app)
    try:
        mod1 = "MY-ALL-1-MIB"
        mod2 = "MY-ALL-2-MIB"
        f1 = os.path.join(temp_dir, f"{mod1}.txt")
        f2 = os.path.join(temp_dir, f"{mod2}.txt")
        with open(f1, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod1, enterprise_oid=77707))
        with open(f2, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod2, enterprise_oid=77708))

        client.post("/api/mibs/load-file", json={"filepath": f1})
        client.post("/api/mibs/load-file", json={"filepath": f2})

        loaded_before = client.get("/api/mibs/loaded").json()
        assert mod1 in loaded_before
        assert mod2 in loaded_before

        # Click Unload All
        un_all = client.post("/api/mibs/unload-all")
        assert un_all.status_code == 200
        assert un_all.json().get("success") is True

        loaded_after = client.get("/api/mibs/loaded").json()
        assert len(loaded_after) == 0

        # Tree does not contain any of them
        tree = client.get("/api/mibs/tree")
        assert "77707" not in tree.text
        assert "77708" not in tree.text

        # Files remain intact
        assert os.path.isfile(f1)
        assert os.path.isfile(f2)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_button_remove_staged_mib_never_reappears():
    """
    Simulates the exact user bug:
    A custom MIB is staged in workspace (or uploaded), showing as Staged.
    Clicking Remove must:
    1. Permanently remove its staging registration and workspace files.
    2. Refreshing /api/mibs must NOT list the MIB as staged anymore.
    3. User original file is preserved.
    4. Repeated removal attempts handle cleanly without error.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_staged_rem_")
    client = TestClient(app)
    try:
        mod_name = "MY-STAGE-REMOVE-MIB"
        file_path = os.path.join(temp_dir, f"{mod_name}.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(_create_sample_mib(mod_name, enterprise_oid=77709))

        orig_hash = compute_file_hash(file_path)

        # Stage file to workspace without activating
        dest_path, info = workspace_manager.stage_file_to_workspace(file_path)
        assert os.path.isfile(dest_path)

        # Verify it appears as staged in /api/mibs
        list_resp = client.get("/api/mibs")
        mibs = list_resp.json()
        target = next((m for m in mibs if m["name"] == mod_name), None)
        assert target is not None, f"Staged MIB {mod_name} should appear in /api/mibs"
        assert target["loaded"] is False
        assert target["status"] == "staged"
        assert target["category"] in ("staged", "custom")

        # Now click Remove on this staged MIB
        rem_resp = client.post("/api/mibs/remove", json={"module_name": mod_name})
        assert rem_resp.status_code == 200, f"Remove failed: {rem_resp.text}"
        rem_data = rem_resp.json()
        assert rem_data.get("success") is True

        # Authoritative scan after remove: MUST NOT appear in /api/mibs as staged!
        list_after = client.get("/api/mibs")
        target_after = next((m for m in list_after.json() if m["name"] == mod_name), None)
        assert target_after is None, f"Removed staged MIB '{mod_name}' MUST NOT appear in /api/mibs after removal!"

        # Files in workspace must be gone
        ws_files = os.listdir(workspace_manager.workspace_dir)
        for wf in ws_files:
            assert mod_name.lower() not in wf.lower(), f"Workspace file {wf} lingering after remove"

        # Original file is 100% intact
        assert os.path.isfile(file_path)
        assert compute_file_hash(file_path) == orig_hash

        # Repeated removal attempt: idempotent and safe
        rep_resp = client.post("/api/mibs/remove", json={"module_name": mod_name})
        assert rep_resp.status_code == 200
        assert rep_resp.json().get("success") is True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_silent_subprocess_execution_flags():
    """
    Verifies that the process runner configures Windows subprocess flags
    (CREATE_NO_WINDOW and SW_HIDE) to prevent console windows from flashing.
    """
    from snmp.process import process_runner
    import subprocess
    silent_kwargs = process_runner._get_silent_kwargs()
    if os.name == "nt" or sys.platform == "win32":
        assert "creationflags" in silent_kwargs
        assert silent_kwargs["creationflags"] == 0x08000000  # CREATE_NO_WINDOW
        assert "startupinfo" in silent_kwargs
        assert silent_kwargs["startupinfo"].wShowWindow == subprocess.SW_HIDE
        assert bool(silent_kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)


if __name__ == "__main__":
    tests = [
        test_button_reload_handles_filename_mismatch,
        test_button_unload_and_tree_synchronization,
        test_button_load_staged_to_active,
        test_button_remove_cleans_workspace_and_managed_copy,
        test_dependency_guard_prevents_premature_removal_or_unload,
        test_button_unload_all,
        test_button_remove_staged_mib_never_reappears,
        test_silent_subprocess_execution_flags,
    ]
    passed = 0
    failed = 0
    print("=" * 60)
    print("RUNNING MIB LIFECYCLE & BUTTONS TEST SUITE")
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
