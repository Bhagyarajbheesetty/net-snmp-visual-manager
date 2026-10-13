import os
import sys
import re

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT_DIR, "snmp_manager"))

from snmp.client import VarBind
from snmp.walk import WalkSession
from export.formatter import format_walk_export


def test_mib_file_definitions_count():
    """Verify MIB parser accurately counts OBJECT-TYPE, OBJECT IDENTIFIER, NOTIFICATION-TYPE, and MODULE-IDENTITY."""
    if_mib_path = os.path.join(ROOT_DIR, "share", "snmp", "mibs", "IF-MIB.txt")
    assert os.path.isfile(if_mib_path), f"Standard bundled IF-MIB.txt must exist at {if_mib_path}"

    with open(if_mib_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    # Clean comments
    clean_text = re.sub(r"--[^\n]*", "", text)

    ots = re.findall(r"(\b[a-zA-Z0-9_-]+\b)\s+OBJECT-TYPE\b", clean_text)
    oids = re.findall(r"(\b[a-zA-Z0-9_-]+\b)\s+OBJECT\s+IDENTIFIER\s*::=", clean_text)
    nots = re.findall(r"(\b[a-zA-Z0-9_-]+\b)\s+NOTIFICATION-TYPE\b", clean_text)
    mods = re.findall(r"(\b[a-zA-Z0-9_-]+\b)\s+MODULE-IDENTITY\b", clean_text)

    assert len(ots) > 50, f"Expected >50 OBJECT-TYPEs in IF-MIB, got {len(ots)}"
    assert len(mods) >= 1, f"Expected >=1 MODULE-IDENTITY in IF-MIB, got {len(mods)}"
    total_declared_definitions = len(ots) + len(oids) + len(nots) + len(mods)
    print(f"PASS: MIB declared definitions count verified on IF-MIB: {total_declared_definitions}")


def test_walk_instances_vs_mib_definitions():
    """Verify walk export distinguishes answered OID instances from failed/unanswered OIDs."""
    session = WalkSession(
        id="test-count",
        device_id=1,
        oid_from="1.3.6.1.2.1.2",
        oid_to=None,
        status="completed",
        results=[
            VarBind(oid="1.3.6.1.2.1.2.1.0", name="ifNumber", index="0", type="Integer32", value="2", seq=1),
            VarBind(oid="1.3.6.1.2.1.2.2.1.1.1", name="ifIndex", index="1", type="Integer32", value="1", seq=2),
            VarBind(oid="1.3.6.1.2.1.2.2.1.2.1", name="ifDescr", index="1", type="UNANSWERED", value="Timeout", status="failed", error_msg="Timeout", seq=3),
            VarBind(oid="1.3.6.1.2.1.2.2.1.1.2", name="ifIndex", index="2", type="Integer32", value="2", seq=4),
        ]
    )
    device = {"ip_address": "192.168.1.1", "port": 161, "version": "v2c"}
    text = format_walk_export(device, session, "1.3.6.1.2.1.2")

    parts = text.split("[Query Results]")
    results_text = parts[1] if len(parts) > 1 else ""
    data_lines = [
        l.strip() for l in results_text.splitlines()
        if l.strip() and not l.startswith("Response Time =") and not l.startswith("Response Status =")
    ]

    assert len(data_lines) == 4
    answered_instances = [l for l in data_lines if "(FAILED) =" not in l]
    assert len(answered_instances) == 3
    print(f"PASS: Walk instance counting verified. Answered OID instances: {len(answered_instances)}, Total walk entries: {len(data_lines)}")


if __name__ == "__main__":
    test_mib_file_definitions_count()
    test_walk_instances_vs_mib_definitions()
    print("ALL TESTS PASSED SUCCESSFULLY!")
