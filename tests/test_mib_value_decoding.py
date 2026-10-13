import sys
import os
import tempfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT_DIR, "snmp_manager"))

from pysnmp.proto.rfc1902 import Integer32, OctetString, TimeTicks, Gauge32, Unsigned32
from snmp.client import DeviceConfig, SNMPClient, MIBLoader, VarBind
from snmp.walk import WalkSession
from export.formatter import format_walk_export

SYNTHETIC_TEST_MIB = """
TEST-DECODE-MIB DEFINITIONS ::= BEGIN

IMPORTS
    MODULE-IDENTITY, OBJECT-TYPE, Integer32, Unsigned32, TimeTicks, enterprises
        FROM SNMPv2-SMI
    DisplayString, MacAddress, RowStatus
        FROM SNMPv2-TC;

testEnterprise MODULE-IDENTITY
    LAST-UPDATED "202610120000Z"
    ORGANIZATION "Test Organization"
    CONTACT-INFO "support@example.com"
    DESCRIPTION  "Synthetic MIB for value decoding verification"
    ::= { enterprises 841 }

testObjects         OBJECT IDENTIFIER ::= { testEnterprise 1 }
testSub1            OBJECT IDENTIFIER ::= { testObjects 1 }
testWireless        OBJECT IDENTIFIER ::= { testSub1 1 }
testWirelessSub1    OBJECT IDENTIFIER ::= { testWireless 1 }
testWirelessSub2    OBJECT IDENTIFIER ::= { testWirelessSub1 1 }

-- 1.3.6.1.4.1.841.1.1.1.1.1.1.1
wirelessIfPropertiesEntry OBJECT IDENTIFIER ::= { testWirelessSub2 1 1 }

wirelessIfPropertiesTableIndex OBJECT-TYPE
    SYNTAX      Unsigned32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Table Index"
    ::= { wirelessIfPropertiesEntry 1 }

wirelessIfPropertiesRadioStatus OBJECT-TYPE
    SYNTAX      INTEGER { enable(1), disable(2) }
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "Radio status"
    ::= { wirelessIfPropertiesEntry 2 }

wirelessIfOperationalMode OBJECT-TYPE
    SYNTAX      DisplayString
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "Operational mode"
    ::= { wirelessIfPropertiesEntry 3 }

wirelessIfSupportedOperationalMode OBJECT-TYPE
    SYNTAX      DisplayString
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Supported operational mode"
    ::= { wirelessIfPropertiesEntry 4 }

wirelessIfCurrentChannelBandwidth OBJECT-TYPE
    SYNTAX      Unsigned32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Current channel bandwidth"
    ::= { wirelessIfPropertiesEntry 5 }

wirelessIfSupportedChannelBandwidth OBJECT-TYPE
    SYNTAX      DisplayString
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Supported channel bandwidth"
    ::= { wirelessIfPropertiesEntry 6 }

wirelessIfAutoChannelSelection OBJECT-TYPE
    SYNTAX      INTEGER { enable(1), disable(2) }
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "Auto channel selection"
    ::= { wirelessIfPropertiesEntry 7 }

wirelessIfCellSize OBJECT-TYPE
    SYNTAX      INTEGER { large(1), medium(2), small(3), micro(4) }
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "Cell size"
    ::= { wirelessIfPropertiesEntry 16 }

-- 1.3.6.1.4.1.841.1.1.1.1.1.2.1.8
wirelessIf11nEntry OBJECT IDENTIFIER ::= { testWirelessSub2 2 1 }

wirelessIf11nPropertiesGuardInterval OBJECT-TYPE
    SYNTAX      INTEGER { shortGI-400nSec(1), fullGI-800nSec(2) }
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "Guard interval"
    ::= { wirelessIf11nEntry 8 }

-- 1.3.6.1.4.1.841.1.1.1.1.1.4.1.19
wirelessIfWorpEntry OBJECT IDENTIFIER ::= { testWirelessSub2 4 1 }

wirelessIfWORPIntfMacAddress OBJECT-TYPE
    SYNTAX      MacAddress
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "WORP Interface MAC Address"
    ::= { wirelessIfWorpEntry 19 }

-- 1.3.6.1.4.1.841.1.1.1.1.1.7.1.25
linkProfileEntry OBJECT IDENTIFIER ::= { testWirelessSub2 7 1 }

linkProfileTableEntryStatus OBJECT-TYPE
    SYNTAX      RowStatus
    MAX-ACCESS  read-create
    STATUS      current
    DESCRIPTION "Link profile row status"
    ::= { linkProfileEntry 25 }

-- 1.3.6.1.4.1.841.1.1.1.3.4.1.1.1
qosMappingEntry OBJECT IDENTIFIER ::= { testWireless 3 4 1 1 }

l2l3QoSDot1DToDot1pMappingTableIndex OBJECT-TYPE
    SYNTAX      Unsigned32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "QoS Mapping Table Index"
    ::= { qosMappingEntry 1 }

-- 1.3.6.1.4.1.841.1.1.3.19.1.1.9
sx3IfEntry OBJECT IDENTIFIER ::= { testSub1 3 19 1 1 }

sx3IfLastChange OBJECT-TYPE
    SYNTAX      TimeTicks
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Interface last change"
    ::= { sx3IfEntry 9 }

END
"""

_temp_mib_dir = None


def get_test_client():
    global _temp_mib_dir
    from snmp.mib import mib_manager

    if "TEST-DECODE-MIB" not in mib_manager._active_modules:
        if _temp_mib_dir is None:
            _temp_mib_dir = tempfile.TemporaryDirectory()
        mib_path = os.path.join(_temp_mib_dir.name, "TEST-DECODE-MIB.mib")
        with open(mib_path, "w", encoding="utf-8") as f:
            f.write(SYNTHETIC_TEST_MIB)
        mib_manager.load_file(mib_path)

    loader = mib_manager.get_loader()
    config = DeviceConfig(ip="192.0.2.1")
    client = SNMPClient(config, mib_loader=loader)
    return client


def cleanup_test_mib():
    global _temp_mib_dir
    from snmp.mib import mib_manager
    if "TEST-DECODE-MIB" in mib_manager._active_modules:
        mib_manager.remove_module("TEST-DECODE-MIB")
    if _temp_mib_dir is not None:
        try:
            _temp_mib_dir.cleanup()
        except Exception:
            pass
        _temp_mib_dir = None


def test_enum_decoding_guard_interval():
    """1. Test enumeration decoding on wirelessIf11nPropertiesGuardInterval with value 2 -> fullGI-800nSec (2)."""
    client = get_test_client()
    oid = "1.3.6.1.4.1.841.1.1.1.1.1.2.1.8.1"
    vbs = client._process_varbinds(None, None, None, [(oid, Integer32(2))])
    assert len(vbs) == 1
    vb = vbs[0]

    assert vb.name == "wirelessIf11nPropertiesGuardInterval"
    assert vb.index == "1"
    # Protocol raw value and type preserved
    assert vb.type == "Integer32"
    assert vb.value == "2"
    # Display type and value formatted correctly
    assert vb.display_type == "Enum"
    assert vb.display_value == "fullGI-800nSec (2)"

    session = WalkSession(id="test-enum", device_id=1, oid_from=oid, oid_to=None, status="completed", results=[vb])
    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v3"}
    exported = format_walk_export(device, session, oid)
    assert "wirelessIf11nPropertiesGuardInterval.1 (Enum) = fullGI-800nSec (2)" in exported
    print("[PASS] test_enum_decoding_guard_interval")


def test_enum_decoding_unknown_value():
    """2. Test fallback behavior when an enumeration value is not defined in the MIB."""
    client = get_test_client()
    # wirelessIfCellSize enums: large(1), medium(2), small(3), micro(4)
    oid = "1.3.6.1.4.1.841.1.1.1.1.1.1.1.16.1"
    vbs = client._process_varbinds(None, None, None, [(oid, Integer32(0))])
    assert len(vbs) == 1
    vb = vbs[0]

    assert vb.name == "wirelessIfCellSize"
    assert vb.index == "1"
    assert vb.type == "Integer32"
    assert vb.value == "0"
    assert vb.display_type == "Enum"
    assert vb.display_value == "(0) is not in any MIB!"

    session = WalkSession(id="test-unknown-enum", device_id=1, oid_from=oid, oid_to=None, status="completed", results=[vb])
    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v3"}
    exported = format_walk_export(device, session, oid)
    assert "wirelessIfCellSize.1 (Enum) = (0) is not in any MIB!" in exported
    print("[PASS] test_enum_decoding_unknown_value")


def test_raw_integer_values_non_enumerated():
    """3. Test raw integer values for non-enumerated objects."""
    client = get_test_client()
    # wirelessIfCurrentChannelBandwidth has syntax Unsigned32 with no enums
    oid = "1.3.6.1.4.1.841.1.1.1.1.1.1.1.5.1"
    vbs = client._process_varbinds(None, None, None, [(oid, Gauge32(80))])
    assert len(vbs) == 1
    vb = vbs[0]

    assert vb.name == "wirelessIfCurrentChannelBandwidth"
    assert vb.index == "1"
    assert vb.value == "80"
    assert vb.display_type == "Unsigned32"
    assert vb.display_value == "80"

    session = WalkSession(id="test-int", device_id=1, oid_from=oid, oid_to=None, status="completed", results=[vb])
    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v3"}
    exported = format_walk_export(device, session, oid)
    assert "wirelessIfCurrentChannelBandwidth.1 (Unsigned32) = 80" in exported
    print("[PASS] test_raw_integer_values_non_enumerated")


def test_row_status_decoding():
    """4. Test RowStatus decoding for known states and unexpected values."""
    client = get_test_client()
    # linkProfileTableEntryStatus has syntax RowStatus
    oid_base = "1.3.6.1.4.1.841.1.1.1.1.1.7.1.25"
    
    # Active (1)
    vb1 = client._process_varbinds(None, None, None, [(f"{oid_base}.1.1", Integer32(1))])[0]
    assert vb1.name == "linkProfileTableEntryStatus"
    assert vb1.index == "1.1"
    assert vb1.type == "Integer32"
    assert vb1.value == "1"
    assert vb1.display_type == "RowStatus"
    assert vb1.display_value == "active (1)"

    # notInService (2)
    vb2 = client._process_varbinds(None, None, None, [(f"{oid_base}.1.2", Integer32(2))])[0]
    assert vb2.display_type == "RowStatus"
    assert vb2.display_value == "notInService (2)"

    # Value 0 (not in MIB)
    vb0 = client._process_varbinds(None, None, None, [(f"{oid_base}.1.3", Integer32(0))])[0]
    assert vb0.display_type == "RowStatus"
    assert vb0.display_value == "(0) is not in any MIB!"

    session = WalkSession(id="test-rowstatus", device_id=1, oid_from=oid_base, oid_to=None, status="completed", results=[vb1, vb2, vb0])
    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v3"}
    exported = format_walk_export(device, session, oid_base)
    assert "linkProfileTableEntryStatus.1.1 (RowStatus) = active (1)" in exported
    assert "linkProfileTableEntryStatus.1.2 (RowStatus) = notInService (2)" in exported
    assert "linkProfileTableEntryStatus.1.3 (RowStatus) = (0) is not in any MIB!" in exported
    print("[PASS] test_row_status_decoding")


def test_mac_address_colon_formatting():
    """5. Test MacAddress colon formatting vs raw hex."""
    client = get_test_client()
    # wirelessIfWORPIntfMacAddress has syntax MacAddress
    oid = "1.3.6.1.4.1.841.1.1.1.1.1.4.1.19.1"
    raw_mac = bytes([0x00, 0x11, 0x22, 0x33, 0x44, 0x55])
    vbs = client._process_varbinds(None, None, None, [(oid, OctetString(raw_mac))])
    assert len(vbs) == 1
    vb = vbs[0]

    assert vb.name == "wirelessIfWORPIntfMacAddress"
    assert vb.index == "1"
    assert vb.type == "OctetString"
    assert vb.value == "0x001122334455"
    assert vb.display_type == "MacAddress"
    assert vb.display_value == "00:11:22:33:44:55"

    # All-zero MAC
    zero_mac = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    vb_zero = client._process_varbinds(None, None, None, [(oid, OctetString(zero_mac))])[0]
    assert vb_zero.display_value == "00:00:00:00:00:00"

    session = WalkSession(id="test-mac", device_id=1, oid_from=oid, oid_to=None, status="completed", results=[vb])
    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v3"}
    exported = format_walk_export(device, session, oid)
    assert "wirelessIfWORPIntfMacAddress.1 (MacAddress) = 00:11:22:33:44:55" in exported
    print("[PASS] test_mac_address_colon_formatting")


def test_display_string_decoding():
    """6. Test DisplayString decoding and ASCII representation."""
    client = get_test_client()
    oid = "1.3.6.1.4.1.841.1.1.1.1.1.1.1.3.1"
    vbs = client._process_varbinds(None, None, None, [(oid, OctetString(b"HE"))])
    assert len(vbs) == 1
    vb = vbs[0]

    assert vb.name == "wirelessIfOperationalMode"
    assert vb.index == "1"
    assert vb.type == "OctetString"
    assert vb.value == "HE"
    assert vb.display_type == "DisplayString"
    assert vb.display_value == "HE"

    session = WalkSession(id="test-ds", device_id=1, oid_from=oid, oid_to=None, status="completed", results=[vb])
    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v3"}
    exported = format_walk_export(device, session, oid)
    assert "wirelessIfOperationalMode.1 (DisplayString) = HE" in exported
    print("[PASS] test_display_string_decoding")


def test_timeticks_formatting():
    """7. Test TimeTicks formatting in days-hours:minutes:seconds.hundredths."""
    client = get_test_client()
    oid = "1.3.6.1.4.1.841.1.1.3.19.1.1.9.1"
    
    # 0 ticks
    vb0 = client._process_varbinds(None, None, None, [(oid, TimeTicks(0))])[0]
    assert vb0.name == "sx3IfLastChange"
    assert vb0.index == "1"
    assert vb0.type == "TimeTicks"
    assert vb0.value == "0"
    assert vb0.display_type == "TimeTicks"
    assert vb0.display_value == "0-0:0:0.00"

    # Non-zero ticks (e.g. 100 centiseconds = 1 second)
    vb100 = client._process_varbinds(None, None, None, [(oid, TimeTicks(100))])[0]
    assert vb100.display_value == "0-0:0:1.00"

    # Complex ticks: 9006123 centiseconds = 1 day, 1 hour, 1 min, 1 sec, 23 cs
    vb_comp = client._process_varbinds(None, None, None, [(oid, TimeTicks(9006123))])[0]
    assert vb_comp.display_value == "1-1:1:1.23"

    session = WalkSession(id="test-tt", device_id=1, oid_from=oid, oid_to=None, status="completed", results=[vb0])
    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v3"}
    exported = format_walk_export(device, session, oid)
    assert "sx3IfLastChange.1 (TimeTicks) = 0-0:0:0.00" in exported
    print("[PASS] test_timeticks_formatting")


def test_multi_index_table_resolution():
    """8. Test multi-index table resolution (such as QoS tables with composite indices)."""
    client = get_test_client()
    # l2l3QoSDot1DToDot1pMappingTableIndex indexed by (tableIndex, priority)
    oid = "1.3.6.1.4.1.841.1.1.1.3.4.1.1.1.1.0"
    vbs = client._process_varbinds(None, None, None, [(oid, Gauge32(0))])
    assert len(vbs) == 1
    vb = vbs[0]

    assert vb.name == "l2l3QoSDot1DToDot1pMappingTableIndex"
    assert vb.index == "1.0", f"Expected composite index '1.0', got '{vb.index}'"
    assert vb.display_type == "Unsigned32"
    assert vb.display_value == "0"

    session = WalkSession(id="test-multi-idx", device_id=1, oid_from=oid, oid_to=None, status="completed", results=[vb])
    device = {"ip_address": "192.0.2.1", "port": 161, "version": "v3"}
    exported = format_walk_export(device, session, oid)
    assert "l2l3QoSDot1DToDot1pMappingTableIndex.1.0 (Unsigned32) = 0" in exported
    print("[PASS] test_multi_index_table_resolution")


def test_raw_values_remain_separated_from_display_values():
    """9. Ensure raw protocol values remain untouched while display_value holds presentation."""
    client = get_test_client()
    oid = "1.3.6.1.4.1.841.1.1.1.1.1.2.1.8.1"
    vb = client._process_varbinds(None, None, None, [(oid, Integer32(2))])[0]

    # vb.value must be numeric "2", NOT "fullGI-800nSec (2)"
    assert vb.value == "2"
    assert int(vb.value) == 2
    assert vb.display_value == "fullGI-800nSec (2)"

    # vb.type must be raw SNMP protocol type "Integer32", NOT "Enum"
    assert vb.type == "Integer32"
    assert vb.display_type == "Enum"
    print("[PASS] test_raw_values_remain_separated_from_display_values")


def test_bulk_matching_against_nudesign_export_samples():
    """10. Verify known samples directly matching NuDesign Visual MIBrowser Pro 16.0 export."""
    client = get_test_client()
    test_cases = [
        ("1.3.6.1.4.1.841.1.1.1.1.1.1.1.1.1", Gauge32(1), "wirelessIfPropertiesTableIndex", "1", "Unsigned32", "1"),
        ("1.3.6.1.4.1.841.1.1.1.1.1.1.1.2.1", Integer32(1), "wirelessIfPropertiesRadioStatus", "1", "Enum", "enable (1)"),
        ("1.3.6.1.4.1.841.1.1.1.1.1.1.1.3.1", OctetString(b"HE"), "wirelessIfOperationalMode", "1", "DisplayString", "HE"),
        ("1.3.6.1.4.1.841.1.1.1.1.1.1.1.4.1", OctetString(b"VHT,HE"), "wirelessIfSupportedOperationalMode", "1", "DisplayString", "VHT,HE"),
        ("1.3.6.1.4.1.841.1.1.1.1.1.1.1.5.1", Gauge32(80), "wirelessIfCurrentChannelBandwidth", "1", "Unsigned32", "80"),
        ("1.3.6.1.4.1.841.1.1.1.1.1.1.1.6.1", OctetString(b"20,40,80"), "wirelessIfSupportedChannelBandwidth", "1", "DisplayString", "20,40,80"),
        ("1.3.6.1.4.1.841.1.1.1.1.1.1.1.7.1", Integer32(2), "wirelessIfAutoChannelSelection", "1", "Enum", "disable (2)"),
    ]

    for oid, val, exp_name, exp_idx, exp_disp_type, exp_disp_val in test_cases:
        vb = client._process_varbinds(None, None, None, [(oid, val)])[0]
        assert vb.name == exp_name, f"Expected {exp_name}, got {vb.name}"
        assert vb.index == exp_idx, f"Expected {exp_idx}, got {vb.index}"
        assert vb.display_type == exp_disp_type, f"Expected {exp_disp_type}, got {vb.display_type}"
        assert vb.display_value == exp_disp_val, f"Expected {exp_disp_val}, got {vb.display_value}"

    print("[PASS] test_bulk_matching_against_nudesign_export_samples")


def test_null_padded_octet_string_decoding():
    """11. Test OctetString containing trailing null bytes decodes cleanly into ASCII string instead of hex zeros."""
    client = get_test_client()
    raw_payload = b"75,75,75,75,72,72,70,70" + (b"\x00" * 150)
    oid = "1.3.6.1.4.1.841.1.1.1.1.1.1.1.6.1"
    vb = client._process_varbinds(None, None, None, [(oid, OctetString(raw_payload))])[0]
    assert vb.value == "75,75,75,75,72,72,70,70"
    assert vb.display_value == "75,75,75,75,72,72,70,70"
    print("[PASS] test_null_padded_octet_string_decoding")


if __name__ == "__main__":
    print("============================================================")
    print("RUNNING MIB VALUE DECODING TEST SUITE")
    print("============================================================")
    try:
        test_enum_decoding_guard_interval()
        test_enum_decoding_unknown_value()
        test_raw_integer_values_non_enumerated()
        test_row_status_decoding()
        test_mac_address_colon_formatting()
        test_display_string_decoding()
        test_timeticks_formatting()
        test_multi_index_table_resolution()
        test_raw_values_remain_separated_from_display_values()
        test_bulk_matching_against_nudesign_export_samples()
        test_null_padded_octet_string_decoding()
        print("============================================================")
        print("ALL 11 MIB VALUE DECODING TESTS PASSED SUCCESSFULLY!")
        print("============================================================")
    finally:
        cleanup_test_mib()
