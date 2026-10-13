import os
import sys
import tempfile
from unittest.mock import patch
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "snmp_manager")))

from fastapi.testclient import TestClient
from main import app
from snmp.walk import walk_engine, WalkSession
from snmp.client import VarBind
from snmp.registry import managed_registry
from export.file_dialog import (
    sanitize_export_filename,
    save_export_content_to_path,
    get_default_initial_dir,
)


def test_filename_sanitization_and_extension():
    """1. Verify filenames are sanitized for Windows and always normalized to .txt."""
    assert sanitize_export_filename("my_walk") == "my_walk.txt"
    assert sanitize_export_filename("my_walk.txt") == "my_walk.txt"
    assert sanitize_export_filename("walk:192.168.1.1/test?.txt") == "test-.txt"
    assert sanitize_export_filename('walk<>:"|?*.txt') == "walk-------.txt"
    assert sanitize_export_filename("") == "walk_export.txt"
    assert sanitize_export_filename("   ") == "walk_export.txt"
    print("[PASS] test_filename_sanitization_and_extension")


def test_save_export_content_writes_exact_text_to_selected_location():
    """2. Verify save_export_content_to_path writes UTF-8 content to user-selected path and verifies existence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, "subfolder", "custom_walk_output.txt")
        sample_content = (
            "Walk: proxim to 1.3.6.1.4.1.841, 7 - 192.168.1.100:161- SNMPv2c\n\n"
            "[Query Results]\n"
            "sysDescr.0 (DisplayString) = Proxim Tsunami MP-10100\n"
            "sysUpTime.0 (TimeTicks) = 1-02:03:04.00\n"
        )
        saved_path = save_export_content_to_path(target, sample_content)
        assert os.path.isfile(saved_path)
        assert saved_path == os.path.abspath(target)
        with open(saved_path, "r", encoding="utf-8") as f:
            read_back = f.read()
        assert read_back == sample_content
    print("[PASS] test_save_export_content_writes_exact_text_to_selected_location")


def test_save_as_endpoint_saves_to_selected_dialog_path():
    """3. Verify POST /api/walk/save-as opens Save As dialog and writes content to the chosen path."""
    client = TestClient(app)

    # Create a device and walk session
    dev = managed_registry.add_device({
        "name": "TestExportDevice",
        "ip_address": "10.99.88.77",
        "port": 161,
        "version": "v2c",
        "read_community": "public",
        "write_community": "private",
        "retries": 2,
        "timeout": 2,
    })

    sid = "exp12345"
    session = WalkSession(
        id=sid,
        device_id=dev["id"],
        oid_from="1.3.6.1.2.1.1",
        oid_to=None,
        status="completed",
        started_at=datetime.now(),
        completed_at=datetime.now(),
    )
    session.results = [
        VarBind(oid="1.3.6.1.2.1.1.1.0", name="sysDescr", type="DisplayString", value="Windows 10 SNMP Test", index="0", status="ok", seq=1),
        VarBind(oid="1.3.6.1.2.1.1.5.0", name="sysName", type="DisplayString", value=" Lab-Switch-01", index="0", status="ok", seq=2),
    ]
    walk_engine.sessions[sid] = session

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            user_chosen_path = os.path.join(tmpdir, "user_selected_walk.txt")

            with patch("api.walk.prompt_save_as_dialog", return_value=user_chosen_path) as mock_dialog:
                res = client.post(
                    "/api/walk/save-as",
                    json={
                        "filename": "suggested_walk_name.txt",
                        "session_id": sid,
                    },
                )
                assert res.status_code == 200
                data = res.json()
                assert data["success"] is True
                assert data["status"] == "saved"
                assert data["path"] == os.path.abspath(user_chosen_path)
                assert data["filename"] == "user_selected_walk.txt"
                mock_dialog.assert_called_once_with("suggested_walk_name.txt")

                # Verify file exists on disk and contains the formatted walk results
                assert os.path.isfile(user_chosen_path)
                with open(user_chosen_path, "r", encoding="utf-8") as f:
                    saved_text = f.read()
                assert "sysDescr.0 (DisplayString) = Windows 10 SNMP Test" in saved_text
                assert "sysName.0 (DisplayString) =  Lab-Switch-01" in saved_text
    finally:
        walk_engine.sessions.pop(sid, None)
        managed_registry.delete_device(dev["id"])

    print("[PASS] test_save_as_endpoint_saves_to_selected_dialog_path")


def test_save_as_endpoint_handles_user_cancel_without_saving():
    """4. Verify cancelling the Save As dialog returns status='cancelled' and does not create a file."""
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent_file = os.path.join(tmpdir, "should_not_exist.txt")

        with patch("api.walk.prompt_save_as_dialog", return_value=None) as mock_dialog:
            res = client.post(
                "/api/walk/save-as",
                json={
                    "filename": "walk_cancel_test.txt",
                    "content": "sysDescr.0 (DisplayString) = Test\n",
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is False
            assert data["status"] == "cancelled"
            assert data["path"] is None
            assert not os.path.exists(non_existent_file)
            mock_dialog.assert_called_once()

    print("[PASS] test_save_as_endpoint_handles_user_cancel_without_saving")


def test_save_as_endpoint_handles_write_errors_gracefully():
    """5. Verify write errors return a clear error message and HTTP 500."""
    client = TestClient(app)

    with patch("api.walk.prompt_save_as_dialog", return_value="C:\\chosen\\walk.txt"):
        with patch("api.walk.save_export_content_to_path", side_effect=PermissionError("Access is denied")):
            res = client.post(
                "/api/walk/save-as",
                json={
                    "filename": "walk_error_test.txt",
                    "content": "sysDescr.0 (DisplayString) = Test\n",
                },
            )
            assert res.status_code == 500
            data = res.json()
            assert "Failed to save file" in data["detail"]
            assert "Access is denied" in data["detail"]

    print("[PASS] test_save_as_endpoint_handles_write_errors_gracefully")


def test_download_stream_fallback_endpoint():
    """6. Verify /api/walk/download-stream returns proper Content-Disposition attachment and UTF-8 content."""
    client = TestClient(app)
    sample_text = "sysDescr.0 (DisplayString) = Fallback Browser Download\n"

    res = client.post(
        "/api/walk/download-stream",
        json={
            "filename": "custom_walk_name",
            "content": sample_text,
        },
    )
    assert res.status_code == 200
    assert "text/plain" in res.headers.get("content-type", "")
    assert 'attachment; filename="custom_walk_name.txt"' in res.headers.get("content-disposition", "")
    assert res.text == sample_text
    print("[PASS] test_download_stream_fallback_endpoint")


def test_frontend_download_export_implementation():
    """7. Verify index.html uses Save As dialog (showSaveFilePicker + /api/walk/save-as) and handles cancel."""
    index_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "snmp_manager", "static", "index.html")
    )
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert "window.showSaveFilePicker" in html
    assert "AbortError" in html
    assert "/api/walk/save-as" in html
    assert "res.status === 'cancelled'" in html
    assert "this.showToast('Downloaded ' + this.exportFilename)" not in html
    print("[PASS] test_frontend_download_export_implementation")


def test_real_windows_native_save_as_dialog_opens_and_cancels():
    """8. Verify the real Windows 10/11 native Save As dialog opens via GetSaveFileNameW and handles Cancel."""
    if sys.platform != "win32":
        return

    import ctypes
    import threading
    import time
    from export.file_dialog import prompt_save_as_dialog

    dialog_title = "Save Walk Export As - Win32 Verification"
    opened_hwnds = []

    def _watch_and_cancel_dialog():
        user32 = ctypes.windll.user32
        for _ in range(80):
            hwnd = user32.FindWindowW("#32770", dialog_title)
            if hwnd:
                opened_hwnds.append(hwnd)
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE (Cancel)
                return
            time.sleep(0.05)

    watcher = threading.Thread(target=_watch_and_cancel_dialog, daemon=True)
    watcher.start()

    result = prompt_save_as_dialog("verify_win10_dialog.txt", title=dialog_title)
    watcher.join(timeout=3.0)

    assert len(opened_hwnds) == 1, "Expected native Windows Save As dialog (#32770) to open"
    assert result is None, "Expected None when Save As dialog is cancelled"
    print(f"[PASS] test_real_windows_native_save_as_dialog_opens_and_cancels (HWND={opened_hwnds[0]})")


def test_end_to_end_save_and_locate_file_on_windows():
    """9. Verify end-to-end saving and locating an exported .txt file on Windows filesystem."""
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as user_chosen_folder:
        chosen_filepath = os.path.join(user_chosen_folder, "My_BulkWalk_Export")  # Without .txt extension
        expected_filepath = os.path.join(user_chosen_folder, "My_BulkWalk_Export.txt")
        walk_text = (
            "Walk: proxim to 1.3.6.1.4.1.841, 7 - 192.168.1.1:161- SNMPv2c\n\n"
            "[SNMP Agent]\n"
            "IP Address = 192.168.1.1\n\n"
            "[Query Results]\n"
            "sysDescr.0 (DisplayString) = Proxim Wireless Unit\n"
            "ifNumber.0 (Integer32) = 4\n"
        )

        res = client.post(
            "/api/walk/save-as",
            json={
                "filename": "My_BulkWalk_Export",
                "content": walk_text,
                "target_path": chosen_filepath,
            },
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["success"] is True
        assert payload["status"] == "saved"
        assert payload["path"] == os.path.abspath(expected_filepath)
        assert payload["filename"] == "My_BulkWalk_Export.txt"

        # Locate the file on disk and verify its content
        assert os.path.isfile(expected_filepath), f"Saved file not found at {expected_filepath}"
        with open(expected_filepath, "r", encoding="utf-8") as f:
            disk_content = f.read()
        assert disk_content == walk_text

    print("[PASS] test_end_to_end_save_and_locate_file_on_windows")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING EXPORT & DOWNLOAD TEST SUITE")
    print("=" * 60)
    test_filename_sanitization_and_extension()
    test_save_export_content_writes_exact_text_to_selected_location()
    test_save_as_endpoint_saves_to_selected_dialog_path()
    test_save_as_endpoint_handles_user_cancel_without_saving()
    test_save_as_endpoint_handles_write_errors_gracefully()
    test_download_stream_fallback_endpoint()
    test_frontend_download_export_implementation()
    test_real_windows_native_save_as_dialog_opens_and_cancels()
    test_end_to_end_save_and_locate_file_on_windows()
    print("=" * 60)
    print("ALL 9 EXPORT & DOWNLOAD TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
