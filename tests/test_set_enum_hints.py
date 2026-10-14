import os
import sys
import unittest
from fastapi.testclient import TestClient

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT_DIR, "snmp_manager"))

from snmp.process import process_runner
from snmp.mib import mib_manager
from snmp.registry import managed_registry
from main import app

client = TestClient(app)


class TestSetEnumHints(unittest.TestCase):

    def test_translate_proxim_https_access_control_numeric(self):
        """1. Verify httpsAccessControl numeric OID resolves enums: enable(1), disable(2)."""
        res = process_runner.translate_oid_details("1.3.6.1.4.1.841.1.1.2.7.3")
        self.assertIsNotNone(res)
        self.assertTrue(res.get("has_enums"))
        self.assertEqual(res.get("enums"), {"enable": 1, "disable": 2})
        self.assertEqual(res.get("type_char"), "i")
        self.assertIn("enable(1)", res.get("syntax", ""))
        self.assertIn("disable(2)", res.get("syntax", ""))

    def test_translate_proxim_https_access_control_instance(self):
        """2. Verify httpsAccessControl.0 instance OID resolves enums."""
        res = process_runner.translate_oid_details("1.3.6.1.4.1.841.1.1.2.7.3.0")
        self.assertIsNotNone(res)
        self.assertTrue(res.get("has_enums"))
        self.assertEqual(res.get("enums"), {"enable": 1, "disable": 2})
        self.assertEqual(res.get("type_char"), "i")

    def test_translate_proxim_symbolic_name(self):
        """3. Verify bare and instance symbolic names resolve enums via -IR."""
        res_bare = process_runner.translate_oid_details("httpsAccessControl")
        self.assertIsNotNone(res_bare)
        self.assertEqual(res_bare.get("enums"), {"enable": 1, "disable": 2})

        res_inst = process_runner.translate_oid_details("httpsAccessControl.0")
        self.assertIsNotNone(res_inst)
        self.assertEqual(res_inst.get("enums"), {"enable": 1, "disable": 2})

    def test_translate_standard_if_admin_status(self):
        """4. Verify standard IF-MIB ifAdminStatus enums: up(1), down(2), testing(3)."""
        res = process_runner.translate_oid_details("1.3.6.1.2.1.2.2.1.7.1")
        self.assertIsNotNone(res)
        self.assertTrue(res.get("has_enums"))
        self.assertEqual(res.get("enums"), {"up": 1, "down": 2, "testing": 3})
        self.assertEqual(res.get("type_char"), "i")

    def test_translate_non_enum_sys_descr(self):
        """5. Verify non-enum string object sysDescr resolves has_enums=False, type_char='s'."""
        res = process_runner.translate_oid_details("1.3.6.1.2.1.1.1.0")
        self.assertIsNotNone(res)
        self.assertFalse(res.get("has_enums"))
        self.assertEqual(res.get("enums"), {})
        self.assertEqual(res.get("type_char"), "s")

    def test_api_oid_details_proxim_endpoint(self):
        """6. Verify GET /api/operations/oid-details returns full schema and enums."""
        resp = client.get("/api/operations/oid-details?oid=1.3.6.1.4.1.841.1.1.2.7.3.0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["oid"], "1.3.6.1.4.1.841.1.1.2.7.3.0")
        self.assertTrue(data["has_enums"])
        self.assertEqual(data["enums"], {"enable": 1, "disable": 2})
        self.assertEqual(data["type_char"], "i")
        self.assertEqual(data["defval"], "enable")
        self.assertIn("HTTPS", data["description"])

    def test_api_oid_details_symbolic_endpoint(self):
        """7. Verify GET /api/operations/oid-details with symbolic name."""
        resp = client.get("/api/operations/oid-details?oid=httpsAccessControl.0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["has_enums"])
        self.assertEqual(data["enums"], {"enable": 1, "disable": 2})

    def test_api_oid_details_empty_oid(self):
        """8. Verify GET /api/operations/oid-details rejects empty OID."""
        resp = client.get("/api/operations/oid-details?oid=")
        self.assertEqual(resp.status_code, 400)

    def test_translate_proxim_sysmgmt_cfg_commit_free_text_hints(self):
        """10. Verify sysMgmtCfgCommit (Unsigned32) extracts text SET options, GET codes, notes, and preserves 'u' type_char."""
        res = process_runner.translate_oid_details("sysMgmtCfgCommit")
        self.assertIsNotNone(res)
        self.assertTrue(res.get("has_enums"))
        self.assertEqual(res.get("type_char"), "u")
        self.assertEqual(res.get("enums"), {"Commit": 1, "Temporary Commit": 2})
        desc_det = res.get("description_details", {})
        self.assertIn("Commit", desc_det.get("set_options", {}))
        self.assertEqual(desc_det.get("set_options", {})["Commit"], 1)
        self.assertEqual(desc_det.get("set_options", {})["Temporary Commit"], 2)
        self.assertIn("Commit Successful", desc_det.get("get_options", {}))
        self.assertEqual(desc_det.get("get_options", {})["Commit Successful"], 200)
        self.assertIn("sysMgmtCfgErrorMsg", desc_det.get("related", ""))
        self.assertIn("seconds", desc_det.get("note", ""))

    def test_api_oid_details_description_details(self):
        """11. Verify GET /api/operations/oid-details returns description_details object for sysMgmtCfgCommit."""
        resp = client.get("/api/operations/oid-details?oid=sysMgmtCfgCommit")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type_char"], "u")
        self.assertTrue(data["has_enums"])
        self.assertIsNotNone(data["description_details"])
        self.assertEqual(data["description_details"]["set_options"], {"Commit": 1, "Temporary Commit": 2})
        self.assertEqual(data["description_details"]["get_options"]["Commit Successful"], 200)


if __name__ == "__main__":
    unittest.main()
