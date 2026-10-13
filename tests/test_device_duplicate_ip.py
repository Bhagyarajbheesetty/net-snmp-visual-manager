import sys
import os
import threading
from concurrent.futures import ThreadPoolExecutor

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT_DIR, "snmp_manager"))

from main import app
from fastapi.testclient import TestClient
from database import init_db
from snmp.registry import managed_registry


def setup_module():
    init_db()


def cleanup_ips(*ips):
    devs = managed_registry.list_devices()
    for d in devs:
        if d.get("ip_address") in ips or any(ip.strip() == d.get("ip_address").strip() for ip in ips):
            managed_registry.delete_device(d["id"])


def count_devices_with_ip(ip: str) -> int:
    devs = managed_registry.list_devices()
    return sum(1 for d in devs if d.get("ip_address") == ip)


def test_add_device_new_ipv4_succeeds():
    """Add a device with a new IPv4 address — it should succeed."""
    client = TestClient(app)
    ip = "192.168.100.1"
    # Ensure clean state
    cleanup_ips(ip)

    resp = client.post("/api/devices", json={
        "name": "Test-Unique-1",
        "ip_address": ip,
        "port": 161,
        "version": "v2c",
        "read_community": "public"
    })
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["ip_address"] == ip
    assert "id" in data

    # Cleanup
    client.delete(f"/api/devices/{data['id']}")


def test_add_duplicate_ipv4_rejected():
    """Add the same IPv4 address again — it should be rejected."""
    client = TestClient(app)
    ip = "192.168.100.2"
    cleanup_ips(ip)

    # First add succeeds
    resp1 = client.post("/api/devices", json={
        "name": "Device-A",
        "ip_address": ip,
        "port": 161,
        "version": "v2c"
    })
    assert resp1.status_code == 200
    dev1_id = resp1.json()["id"]

    try:
        # Second add with same IP must be rejected
        resp2 = client.post("/api/devices", json={
            "name": "Device-B",
            "ip_address": ip,
            "port": 161,
            "version": "v2c"
        })
        assert resp2.status_code == 400, f"Expected 400, got {resp2.status_code}: {resp2.text}"
        detail = resp2.json().get("detail", "")
        assert "already exists" in detail.lower(), f"Unexpected error message: {detail}"

        # Verify only one device exists in registry with this IP
        count = count_devices_with_ip(ip)
        assert count == 1, f"Expected exactly 1 device, found {count}"
    finally:
        client.delete(f"/api/devices/{dev1_id}")


def test_add_duplicate_with_whitespace_normalized_and_rejected():
    """Add an existing IP address with leading/trailing whitespace — it should be rejected after normalization."""
    client = TestClient(app)
    ip_base = "192.168.100.3"
    cleanup_ips(ip_base)

    # Add canonical IP
    resp1 = client.post("/api/devices", json={
        "name": "Device-Whitespace-Orig",
        "ip_address": ip_base,
        "port": 161,
        "version": "v2c"
    })
    assert resp1.status_code == 200
    dev1_id = resp1.json()["id"]

    try:
        # Attempt to add with leading/trailing whitespace
        resp2 = client.post("/api/devices", json={
            "name": "Device-Whitespace-Dup",
            "ip_address": f"   {ip_base}  \t",
            "port": 161,
            "version": "v2c"
        })
        assert resp2.status_code == 400
        assert "already exists" in resp2.json().get("detail", "").lower()
    finally:
        client.delete(f"/api/devices/{dev1_id}")


def test_ipv6_equivalent_representations_rejected():
    """Test equivalent IPv6 representations (e.g. expanded vs compressed) — recognized as duplicate."""
    client = TestClient(app)
    ipv6_comp = "2001:db8::1"
    ipv6_exp = "2001:0db8:0000:0000:0000:0000:0000:0001"
    cleanup_ips(ipv6_comp, ipv6_exp)

    # Add compressed form
    resp1 = client.post("/api/devices", json={
        "name": "IPv6-Device-1",
        "ip_address": ipv6_comp,
        "port": 161,
        "version": "v2c"
    })
    assert resp1.status_code == 200
    dev1_id = resp1.json()["id"]

    try:
        # Attempt to add expanded form
        resp2 = client.post("/api/devices", json={
            "name": "IPv6-Device-2",
            "ip_address": ipv6_exp,
            "port": 161,
            "version": "v2c"
        })
        assert resp2.status_code == 400, f"Expected 400 for equivalent IPv6, got {resp2.status_code}: {resp2.text}"
        assert "already exists" in resp2.json().get("detail", "").lower()

        # Attempt to add uppercase form
        resp3 = client.post("/api/devices", json={
            "name": "IPv6-Device-3",
            "ip_address": "2001:DB8::1",
            "port": 161,
            "version": "v2c"
        })
        assert resp3.status_code == 400
        assert "already exists" in resp3.json().get("detail", "").lower()
    finally:
        client.delete(f"/api/devices/{dev1_id}")


def test_invalid_ip_format_rejected():
    """Invalid IP formats are rejected with clear error."""
    client = TestClient(app)
    invalid_ips = ["999.999.999.999", "not_an_ip", "192.168.1", "192.168.1.1.1", ""]
    for bad in invalid_ips:
        resp = client.post("/api/devices", json={
            "name": "Bad-IP",
            "ip_address": bad,
            "port": 161,
            "version": "v2c"
        })
        assert resp.status_code == 400, f"Expected 400 for '{bad}', got {resp.status_code}"


def test_concurrent_device_creation_only_one_succeeds():
    """
    Submit multiple concurrent requests with the exact same IP address.
    Registry enforcement must ensure exactly ONE succeeds and others are rejected.
    """
    ip = "192.168.100.99"
    cleanup_ips(ip)

    results = []

    def try_create(idx):
        t_client = TestClient(app)
        r = t_client.post("/api/devices", json={
            "name": f"Concurrent-{idx}",
            "ip_address": ip,
            "port": 161,
            "version": "v2c"
        })
        return r.status_code, r.text

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(try_create, i) for i in range(5)]
        results = [f.result() for f in futures]

    successes = [r for r in results if r[0] == 200]
    failures = [r for r in results if r[0] == 400]

    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}: {results}"
    assert len(failures) == 4, f"Expected 4 failures, got {len(failures)}: {results}"

    # Verify registry has exactly 1 device
    count = count_devices_with_ip(ip)
    assert count == 1, f"Registry has {count} devices instead of 1"

    # Cleanup
    cleanup_ips(ip)


def test_edit_device_same_ip_succeeds():
    """Edit an existing device without changing its IP — it should succeed."""
    client = TestClient(app)
    ip = "192.168.100.5"
    cleanup_ips(ip)

    resp = client.post("/api/devices", json={
        "name": "Edit-Test-Orig",
        "ip_address": ip,
        "port": 161,
        "version": "v2c"
    })
    assert resp.status_code == 200
    dev_id = resp.json()["id"]

    try:
        # Update name and port, keeping same IP
        up_resp = client.put(f"/api/devices/{dev_id}", json={
            "name": "Edit-Test-Renamed",
            "ip_address": ip,
            "port": 1161
        })
        assert up_resp.status_code == 200, f"Expected 200, got {up_resp.status_code}: {up_resp.text}"
        data = up_resp.json()
        assert data["name"] == "Edit-Test-Renamed"
        assert data["port"] == 1161
        assert data["ip_address"] == ip
    finally:
        client.delete(f"/api/devices/{dev_id}")


def test_edit_device_duplicate_ip_rejected():
    """Change a device's IP to one already assigned to another device — it should be rejected."""
    client = TestClient(app)
    ip1 = "192.168.100.6"
    ip2 = "192.168.100.7"
    cleanup_ips(ip1, ip2)

    r1 = client.post("/api/devices", json={"name": "Device-1", "ip_address": ip1})
    r2 = client.post("/api/devices", json={"name": "Device-2", "ip_address": ip2})
    assert r1.status_code == 200 and r2.status_code == 200
    id1 = r1.json()["id"]
    id2 = r2.json()["id"]

    try:
        # Try to change Device-2's IP to Device-1's IP
        up_resp = client.put(f"/api/devices/{id2}", json={"ip_address": ip1})
        assert up_resp.status_code == 400, f"Expected 400, got {up_resp.status_code}: {up_resp.text}"
        assert "already exists" in up_resp.json().get("detail", "").lower()

        # Device-2's IP in registry must remain ip2
        dev2 = managed_registry.get_device(id2)
        assert dev2 is not None
        assert dev2["ip_address"] == ip2
    finally:
        client.delete(f"/api/devices/{id1}")
        client.delete(f"/api/devices/{id2}")


def test_device_listing_and_existing_records_remain_unaffected():
    """Verify that device listing, test endpoints, and existing records remain unaffected."""
    client = TestClient(app)
    r = client.post("/api/devices", json={"name": "Sample-Device", "ip_address": "10.0.0.1"})
    try:
        list_resp = client.get("/api/devices")
        assert list_resp.status_code == 200
        devices = list_resp.json()
        assert isinstance(devices, list)
        assert len(devices) > 0
    finally:
        if r.status_code == 200:
            client.delete(f"/api/devices/{r.json()['id']}")


if __name__ == "__main__":
    tests = [
        test_add_device_new_ipv4_succeeds,
        test_add_duplicate_ipv4_rejected,
        test_add_duplicate_with_whitespace_normalized_and_rejected,
        test_ipv6_equivalent_representations_rejected,
        test_invalid_ip_format_rejected,
        test_concurrent_device_creation_only_one_succeeds,
        test_edit_device_same_ip_succeeds,
        test_edit_device_duplicate_ip_rejected,
        test_device_listing_and_existing_records_remain_unaffected,
    ]
    passed = 0
    failed = 0
    print("=" * 60)
    print("RUNNING DEVICE DUPLICATE IP TEST SUITE")
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
