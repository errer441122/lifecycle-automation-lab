"""Unit tests for the browser Pyodide bridge and real-world Excel CSV quirks."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import platform_io as pio  # noqa: E402
import sync_klaviyo as sk  # noqa: E402
import web_app  # noqa: E402

SHOPIFY_ORDERS = ROOT / "fixtures" / "shopify_orders_schema.csv"
KLAVIYO_EXPORT = ROOT / "fixtures" / "klaviyo_list_export_schema.csv"
BROKEN_HTML = ROOT / "fixtures" / "broken_klaviyo_email.html"


class TestRealWorldCsvQuirks(unittest.TestCase):
    def write(self, text: str, encoding: str = "utf-8") -> Path:
        d = tempfile.mkdtemp()
        path = Path(d) / "file.csv"
        path.write_text(text, encoding=encoding)
        return path

    def test_semicolons_decimal_commas_and_day_first_dates(self):
        path = self.write(
            "email;order_date;order_value_eur\n"
            "a@example.com;20/05/2026;49,90\n"
            "a@example.com;2026-05-25 10:00;1.234,50\n"
        )
        a = sk.read_orders(path)["a@example.com"]
        self.assertEqual(a["orders"], 2)
        self.assertAlmostEqual(a["monetary"], 1284.40)
        self.assertEqual(a["last"], date(2026, 5, 25))

    def test_bom_and_formula_neutralization(self):
        self.assertEqual(pio.safe_cell("=cmd@example.com"), "'=cmd@example.com")
        path = self.write("email\torder_date\torder_value_eur\na@example.com\t2026-05-20\t10\n", "utf-8-sig")
        self.assertEqual(sk.read_orders(path)["a@example.com"]["orders"], 1)


class TestBrowserBridge(unittest.TestCase):
    def test_check_template_returns_structured_audit(self):
        html = BROKEN_HTML.read_text(encoding="utf-8")
        out = json.loads(web_app.check_template(html, "15% off today", "15% off today", "auto", True))
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(out["esp"], "klaviyo")
        self.assertTrue(out["discount_offer"]["has_discount"])
        self.assertGreaterEqual(out["blocker_count"], 3)

    def test_preflight_guard_returns_exclusions_and_suppressions(self):
        out = json.loads(
            web_app.preflight_guard(
                str(KLAVIYO_EXPORT),
                str(SHOPIFY_ORDERS),
                "",
                "",
                "",
                "15",
                "2026-06-01",
                3,
                14,
                True,
                True,
            )
        )
        self.assertEqual(out["summary"]["excluded_vip_margin_guard"], 2)
        self.assertEqual(out["summary"]["blocked_gdpr_deliverability"], 5)
        self.assertTrue(out["vip_exclusions_csv"].startswith("email,exclusion_reason,"))
        self.assertTrue(out["gdpr_suppressions_csv"].startswith("email,suppression_reason,"))

    def test_lifecycle_returns_klaviyo_and_hubspot_downloads(self):
        out = json.loads(web_app.lifecycle(str(SHOPIFY_ORDERS), str(KLAVIYO_EXPORT), "2026-06-01", True, False))
        self.assertEqual(out["report"]["orders_format"], "shopify_orders")
        self.assertEqual(out["report"]["consent_format"], "klaviyo_list_export")
        self.assertTrue(out["klaviyo_csv"].startswith("Email,lifecycle_stage,"))
        self.assertTrue(out["hubspot_csv"].startswith("Email,Lifecycle Stage Custom,"))

    def test_unreadable_file_returns_error_json(self):
        d = tempfile.mkdtemp()
        bad = Path(d) / "bad.csv"
        bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
        out = json.loads(web_app.timing(str(bad)))
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
