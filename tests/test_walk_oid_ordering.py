import sys
import os
import asyncio
from datetime import datetime

# Setup paths
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT_DIR, "snmp_manager"))

from snmp.client import VarBind, DeviceConfig
from snmp.walk import WalkSession, WalkEngine
from export.formatter import format_walk_export
from api.walk import WalkResultRow, WalkResultsResponse


def test_walk_all_succeed_preserves_original_order():
    """1. Walk several OIDs where all requests succeed and verify their original order."""
    session = WalkSession(
        id="test-succ-1",
        device_id=1,
        oid_from="1.3.6.1.4.1.841.1",
        oid_to="1.3.6.1.4.1.841.5",
        status="completed",
    )

    raw_items = [
        VarBind(oid="1.3.6.1.4.1.841.1", name="deviceSystem", type="DisplayString", value="Router OS", seq=1),
        VarBind(oid="1.3.6.1.4.1.841.2", name="deviceHardware", type="DisplayString", value="Enterprise AP", seq=2),
        VarBind(oid="1.3.6.1.4.1.841.3", name="deviceWireless", type="Integer32", value="1", seq=3),
        VarBind(oid="1.3.6.1.4.1.841.4", name="deviceEthernet", type="Integer32", value="2", seq=4),
        VarBind(oid="1.3.6.1.4.1.841.5", name="deviceStatus", type="Integer32", value="1", seq=5),
    ]
    session.results = list(raw_items)

    # Verify original order
    assert len(session.results) == 5
    for i, vb in enumerate(session.results):
        assert vb.seq == i + 1
        assert vb.status == "ok"

    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v2c", "read_community": "public"}
    exported = format_walk_export(device, session, session.oid_from, session.oid_to)

    # Verify export output order
    results_section = exported.split("[Query Results]")[1]
    lines = [l.strip() for l in results_section.splitlines() if l.strip() and not l.startswith("Response Time =") and not l.startswith("Response Status =")]
    assert len(lines) == 5
    assert lines[0] == "deviceSystem (DisplayString) = Router OS"
    assert lines[1] == "deviceHardware (DisplayString) = Enterprise AP"
    assert lines[2] == "deviceWireless (Integer32) = 1"
    assert lines[3] == "deviceEthernet (Integer32) = 2"
    assert lines[4] == "deviceStatus (Integer32) = 1"
    print("[PASS] test_walk_all_succeed_preserves_original_order")


def test_timeout_in_middle_retains_position():
    """2. Simulate a timeout on an OID in the middle of the sequence and verify that it remains in that position."""
    session = WalkSession(
        id="test-timeout-mid",
        device_id=1,
        oid_from="1.3.6.1.4.1.841.1",
        oid_to="1.3.6.1.4.1.841.3",
        status="completed",
    )

    # OID 1 succeeds, OID 2 times out, OID 3 succeeds
    session.results = [
        VarBind(oid="1.3.6.1.4.1.841.1", name="deviceSystem", type="DisplayString", value="Router OS", seq=1),
        VarBind(oid="1.3.6.1.4.1.841.2", name="deviceSecurity", type="UNANSWERED", value="Request timed out", status="failed", error_msg="Timeout", seq=2),
        VarBind(oid="1.3.6.1.4.1.841.3", name="deviceWireless", type="Integer32", value="1", seq=3),
    ]

    # Verify positions in results collection
    assert session.results[0].name == "deviceSystem"
    assert session.results[1].name == "deviceSecurity"
    assert session.results[1].status == "failed"
    assert session.results[1].error_msg == "Timeout"
    assert session.results[2].name == "deviceWireless"
    assert session.results[2].status == "ok"

    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v2c"}
    exported = format_walk_export(device, session, session.oid_from, session.oid_to)

    # Failed OID must NOT be grouped at the bottom under separate section
    assert "[Unanswered / Missing MIB Objects]" not in exported

    # Verify lines in query results appear in exact encounter sequence
    results_section = exported.split("[Query Results]")[1]
    lines = [l.strip() for l in results_section.splitlines() if l.strip() and not l.startswith("Response Time =") and not l.startswith("Response Status =")]
    assert len(lines) == 3
    assert lines[0] == "deviceSystem (DisplayString) = Router OS"
    assert lines[1] == "deviceSecurity (FAILED) = Timeout"
    assert lines[2] == "deviceWireless (Integer32) = 1"
    print("[PASS] test_timeout_in_middle_retains_position")


def test_no_response_followed_by_success_subsequent_order_preserved():
    """3. Simulate a no-response failure followed by successful OIDs and verify that subsequent results remain correctly ordered."""
    session = WalkSession(
        id="test-no-resp-seq",
        device_id=1,
        oid_from="1.3.6.1.4.1.841.1",
        oid_to="1.3.6.1.4.1.841.4",
        status="completed",
    )

    session.results = [
        VarBind(oid="1.3.6.1.4.1.841.1", name="devModel", type="DisplayString", value="SX1", seq=1),
        VarBind(oid="1.3.6.1.4.1.841.2", name="devLegacyParam", type="UNANSWERED", value="No response from agent", status="failed", error_msg="No response from agent", seq=2),
        VarBind(oid="1.3.6.1.4.1.841.3", name="devChannel", type="Gauge32", value="36", seq=3),
        VarBind(oid="1.3.6.1.4.1.841.4", name="devTxPower", type="Integer32", value="23", seq=4),
    ]

    # Verify subsequent OIDs are not shifted out of order
    assert [r.seq for r in session.results] == [1, 2, 3, 4]
    assert [r.name for r in session.results] == ["devModel", "devLegacyParam", "devChannel", "devTxPower"]
    assert session.results[1].status == "failed"
    assert session.results[2].status == "ok"
    assert session.results[3].status == "ok"

    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v2c"}
    exported = format_walk_export(device, session, session.oid_from, session.oid_to)

    lines = [l.strip() for l in exported.splitlines() if "dev" in l]
    assert len(lines) == 4
    assert lines[0] == "devModel (DisplayString) = SX1"
    assert lines[1] == "devLegacyParam (FAILED) = No response from agent"
    assert lines[2] == "devChannel (Gauge32) = 36"
    assert lines[3] == "devTxPower (Integer32) = 23"
    print("[PASS] test_no_response_followed_by_success_subsequent_order_preserved")


def test_consecutive_failures_and_intermittent_timeouts():
    """4. Test consecutive failures and intermittent timeouts."""
    session = WalkSession(
        id="test-consec-intermit",
        device_id=1,
        oid_from="1.3.6.1.4.1.841.1",
        oid_to="1.3.6.1.4.1.841.6",
        status="completed",
    )

    session.results = [
        VarBind(oid="1.3.6.1.4.1.841.1", name="node1", type="Integer32", value="100", seq=1),
        VarBind(oid="1.3.6.1.4.1.841.2", name="node2", type="UNANSWERED", value="Request timed out", status="failed", error_msg="Timeout", seq=2),
        VarBind(oid="1.3.6.1.4.1.841.3", name="node3", type="UNANSWERED", value="No response from agent", status="failed", error_msg="No response from agent", seq=3),
        VarBind(oid="1.3.6.1.4.1.841.4", name="node4", type="Integer32", value="400", seq=4),
        VarBind(oid="1.3.6.1.4.1.841.5", name="node5", type="UNANSWERED", value="Request timed out", status="failed", error_msg="Timeout", seq=5),
        VarBind(oid="1.3.6.1.4.1.841.6", name="node6", type="Integer32", value="600", seq=6),
    ]

    expected_statuses = ["ok", "failed", "failed", "ok", "failed", "ok"]
    assert [r.status for r in session.results] == expected_statuses
    assert [r.seq for r in session.results] == [1, 2, 3, 4, 5, 6]

    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v2c"}
    exported = format_walk_export(device, session, session.oid_from, session.oid_to)

    lines = [l.strip() for l in exported.splitlines() if "node" in l]
    assert len(lines) == 6
    assert lines[0] == "node1 (Integer32) = 100"
    assert lines[1] == "node2 (FAILED) = Timeout"
    assert lines[2] == "node3 (FAILED) = No response from agent"
    assert lines[3] == "node4 (Integer32) = 400"
    assert lines[4] == "node5 (FAILED) = Timeout"
    assert lines[5] == "node6 (Integer32) = 600"
    print("[PASS] test_consecutive_failures_and_intermittent_timeouts")


def test_async_out_of_order_responses_preserve_sequence():
    """5. Verify that asynchronous responses arriving out of order do not change the displayed walk sequence."""
    session = WalkSession(
        id="test-async-order",
        device_id=1,
        oid_from="1.3.6.1.4.1.841.1",
        oid_to="1.3.6.1.4.1.841.5",
        status="completed",
    )

    # Simulate items arriving in scrambled order
    scrambled_items = [
        VarBind(oid="1.3.6.1.4.1.841.4", name="item4", type="Integer32", value="40", seq=4),
        VarBind(oid="1.3.6.1.4.1.841.2", name="item2", type="UNANSWERED", value="Timeout", status="failed", error_msg="Timeout", seq=2),
        VarBind(oid="1.3.6.1.4.1.841.5", name="item5", type="Integer32", value="50", seq=5),
        VarBind(oid="1.3.6.1.4.1.841.1", name="item1", type="Integer32", value="10", seq=1),
        VarBind(oid="1.3.6.1.4.1.841.3", name="item3", type="Integer32", value="30", seq=3),
    ]
    session.results = scrambled_items

    # API sorting logic
    sorted_results = sorted(session.results, key=lambda x: getattr(x, "seq", 0))
    assert [r.seq for r in sorted_results] == [1, 2, 3, 4, 5]
    assert [r.name for r in sorted_results] == ["item1", "item2", "item3", "item4", "item5"]
    assert sorted_results[1].status == "failed"

    # Export sorting logic
    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v2c"}
    exported = format_walk_export(device, session, session.oid_from, session.oid_to)
    lines = [l.strip() for l in exported.splitlines() if "item" in l]
    assert lines == [
        "item1 (Integer32) = 10",
        "item2 (FAILED) = Timeout",
        "item3 (Integer32) = 30",
        "item4 (Integer32) = 40",
        "item5 (Integer32) = 50",
    ]
    print("[PASS] test_async_out_of_order_responses_preserve_sequence")


def test_failure_indicators_and_error_details():
    """6. Confirm that failure indicators and error details remain accurate."""
    vb_timeout = VarBind(
        oid="1.3.6.1.4.1.841.2",
        name="secKey",
        type="UNANSWERED",
        value="Request timed out",
        status="failed",
        error_msg="Timeout",
        seq=1
    )
    vb_noresp = VarBind(
        oid="1.3.6.1.4.1.841.3",
        name="antGain",
        type="UNANSWERED",
        value="No response from agent",
        status="failed",
        error_msg="No response from agent",
        seq=2
    )

    row_timeout = WalkResultRow(**vb_timeout.__dict__)
    row_noresp = WalkResultRow(**vb_noresp.__dict__)

    assert row_timeout.status == "failed"
    assert row_timeout.error_msg == "Timeout"
    assert row_timeout.value == "Request timed out"

    assert row_noresp.status == "failed"
    assert row_noresp.error_msg == "No response from agent"

    resp = WalkResultsResponse(
        session_id="s1",
        status="completed",
        results=[row_timeout, row_noresp],
        total=2,
        success_count=0,
        failed_count=2
    )
    assert resp.success_count == 0
    assert resp.failed_count == 2
    print("[PASS] test_failure_indicators_and_error_details")


def test_export_no_bottom_grouping_and_no_numeric_oid():
    """7. Confirm export file contains no separate bottom grouping and formats failed rows cleanly."""
    session = WalkSession(
        id="test-clean-export",
        device_id=1,
        oid_from="1.3.6.1.4.1.841",
        oid_to="1.3.6.1.4.1.841.3",
        status="completed",
    )
    session.results = [
        VarBind(oid="1.3.6.1.4.1.841.1", name="prop1", type="Gauge32", value="10", seq=1),
        VarBind(oid="1.3.6.1.4.1.841.2", name="prop2", type="UNANSWERED", value="Object not implemented by device", status="failed", error_msg="Object not implemented by device", seq=2),
        VarBind(oid="1.3.6.1.4.1.841.3", name="prop3", type="Gauge32", value="30", seq=3),
    ]

    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v2c"}
    exported = format_walk_export(device, session, session.oid_from, session.oid_to)

    # 1. No separate bottom group
    assert "[Unanswered / Missing MIB Objects]" not in exported

    # 2. Results lines are in exact encounter order
    lines = [l.strip() for l in exported.splitlines() if "prop" in l]
    assert len(lines) == 3
    assert lines[0] == "prop1 (Gauge32) = 10"
    assert lines[1] == "prop2 (FAILED) = Object not implemented by device"
    assert lines[2] == "prop3 (Gauge32) = 30"

    # 3. No numerical OID prepended to prop2
    assert "1.3.6.1.4.1.841.2 prop2" not in exported
    print("[PASS] test_export_no_bottom_grouping_and_no_numeric_oid")


def test_client_walk_simulation_timeout_in_middle():
    """8. Simulate SNMPClient walk encountering a timeout on an OID in the middle and continuing."""
    from unittest.mock import patch
    from snmp.client import SNMPClient

    cfg = DeviceConfig(ip="127.0.0.1", port=161, version="v2c")
    client = SNMPClient(cfg)

    expected_oids = [
        "1.3.6.1.4.1.841.1",
        "1.3.6.1.4.1.841.2",
    ]

    async def mock_next_cmd(*args, **kwargs):
        ot = args[4]
        oid = str(ot._ObjectType__args[0]._ObjectIdentity__args[0])
        if oid == "1.3.6.1.4.1.841.1":
            from pysnmp.proto.rfc1902 import Integer
            return None, None, 0, [("1.3.6.1.4.1.841.1.1", Integer(100))]
        elif oid == "1.3.6.1.4.1.841.1.1":
            # Mid-sequence query times out
            return "requestTimedOut", None, 0, None
        elif oid == "1.3.6.1.4.1.841.2":
            from pysnmp.proto.rfc1902 import Integer
            return None, None, 0, [("1.3.6.1.4.1.841.2.1", Integer(200))]
        return None, None, 0, None

    with patch("snmp.client.next_cmd", side_effect=mock_next_cmd):
        results = asyncio.run(client.walk(
            oid_from="1.3.6.1.4.1.841.1",
            oid_to="1.3.6.1.4.1.841.2.1",
            expected_oids=expected_oids,
        ))

    assert len(results) == 3
    # Check that item 1 succeeded
    assert results[0].oid == "1.3.6.1.4.1.841.1.1"
    assert results[0].status == "ok"
    assert results[0].seq == 1

    # Check that item 2 timed out in the middle at position 2
    assert results[1].oid == "1.3.6.1.4.1.841.1.1"
    assert results[1].status == "failed"
    assert results[1].error_msg == "Timeout"
    assert results[1].seq == 2

    # Check that item 3 succeeded after the timeout at position 3
    assert results[2].oid == "1.3.6.1.4.1.841.2.1"
    assert results[2].status == "ok"
    assert results[2].seq == 3
    print("[PASS] test_client_walk_simulation_timeout_in_middle")


def test_fastapi_walk_endpoints_and_export_response():
    """9. Verify FastAPI walk results endpoint preserves seq order and export returns formatted content."""
    from fastapi.testclient import TestClient
    from main import app
    from snmp.walk import walk_engine, WalkSession
    from snmp.client import VarBind
    from database import get_connection

    client = TestClient(app)

    # Use an existing device or register one if not present
    from snmp.registry import managed_registry
    devs = managed_registry.list_devices()
    if devs:
        dev_id = devs[0]["id"]
    else:
        new_dev = managed_registry.add_device({
            "name": "TestDev",
            "ip_address": "192.0.2.1",
            "port": 161,
            "version": "v2c",
            "read_community": "public",
            "write_community": "private"
        })
        dev_id = new_dev["id"]

    # Create a mock session in walk_engine
    test_sid = "test-session-api-order"
    session = WalkSession(
        id=test_sid,
        device_id=dev_id,
        oid_from="1.3.6.1.4.1.841.1",
        oid_to="1.3.6.1.4.1.841.3",
        status="completed",
    )
    # Scrambled order
    session.results = [
        VarBind(oid="1.3.6.1.4.1.841.3", name="devC", type="Integer32", value="30", seq=3),
        VarBind(oid="1.3.6.1.4.1.841.1", name="devA", type="Integer32", value="10", seq=1),
        VarBind(oid="1.3.6.1.4.1.841.2", name="devB", type="UNANSWERED", value="Request timed out", status="failed", error_msg="Timeout", seq=2),
    ]
    walk_engine.sessions[test_sid] = session

    # Query GET /api/walk/results/{session_id}
    res = client.get(f"/api/walk/results/{test_sid}")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert data["success_count"] == 2
    assert data["failed_count"] == 1
    # Check that results are strictly ordered by seq
    res_list = data["results"]
    assert len(res_list) == 3
    assert res_list[0]["seq"] == 1
    assert res_list[0]["name"] == "devA"
    assert res_list[1]["seq"] == 2
    assert res_list[1]["name"] == "devB"
    assert res_list[1]["status"] == "failed"
    assert res_list[2]["seq"] == 3
    assert res_list[2]["name"] == "devC"

    # Query POST /api/walk/export/{session_id}
    exp_res = client.post(f"/api/walk/export/{test_sid}", json={"filename": "test_export_order.txt"})
    assert exp_res.status_code == 200
    exp_data = exp_res.json()
    assert exp_data["success"] is True
    content = exp_data["content"]
    assert "[Unanswered / Missing MIB Objects]" not in content
    assert "devA (Integer32) = 10" in content
    assert "devB (FAILED) = Timeout" in content
    assert "devC (Integer32) = 30" in content
    # Order verification in content
    posA = content.index("devA")
    posB = content.index("devB")
    posC = content.index("devC")
    assert posA < posB < posC
    print("[PASS] test_fastapi_walk_endpoints_and_export_response")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING WALK OID ORDERING TEST SUITE")
    print("=" * 60)
    test_walk_all_succeed_preserves_original_order()
    test_timeout_in_middle_retains_position()
    test_no_response_followed_by_success_subsequent_order_preserved()
    test_consecutive_failures_and_intermittent_timeouts()
    test_async_out_of_order_responses_preserve_sequence()
    test_failure_indicators_and_error_details()
    test_export_no_bottom_grouping_and_no_numeric_oid()
    test_client_walk_simulation_timeout_in_middle()
    test_fastapi_walk_endpoints_and_export_response()
    print("=" * 60)
    print("ALL 9 WALK OID ORDERING TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
