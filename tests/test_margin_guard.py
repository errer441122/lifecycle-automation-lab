"""Unit tests for VIP Margin Guard & GDPR/Deliverability Pre-Send Gate."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import margin_guard as mg  # noqa: E402

SHOPIFY_ORDERS = ROOT / "fixtures" / "shopify_orders_schema.csv"
KLAVIYO_EXPORT = ROOT / "fixtures" / "klaviyo_list_export_schema.csv"
HUBSPOT_EXPORT = ROOT / "fixtures" / "hubspot_contacts_schema.csv"
BROKEN_TPL = ROOT / "fixtures" / "broken_klaviyo_email.html"
CLEAN_TPL = ROOT / "fixtures" / "clean_klaviyo_email.html"


class TestMarginGuardKlaviyoAndShopify(unittest.TestCase):
    def test_blocks_gdpr_leaks_and_protects_vip_and_recent_buyers(self):
        res = mg.evaluate_preflight(
            KLAVIYO_EXPORT,
            orders_path=SHOPIFY_ORDERS,
            discount_pct=15.0,
            as_of=date(2026, 6, 1),
            strict_double_optin=True,
        )
        s = res["summary"]
        self.assertEqual(s["audience_format"], "klaviyo_list_export")
        self.assertEqual(s["orders_format"], "shopify_orders")

        # Suppressed: checkbox.leak (single opt-in), unsub, sunset.inactive (>365d), noproof, bounced
        supp_map = {row[0]: row[1] for row in res["gdpr_suppressions"]}
        self.assertEqual(supp_map["checkbox.leak@example.com"], "single_optin_unconfirmed_leak")
        self.assertEqual(supp_map["unsub.customer@example.com"], "opted_out")
        self.assertEqual(supp_map["sunset.inactive@example.com"], "sunset_unengaged_365d")
        self.assertEqual(supp_map["noproof.optin@example.com"], "missing_consent_proof")
        self.assertEqual(supp_map["bounced.lead@example.com"], "hard_bounce")

        # VIP / recent excluded from discount: vip.fullprice (3 full-price orders), recent.buyer (bought 6 days ago)
        vip_map = {row[0]: row for row in res["vip_exclusions"]}
        self.assertIn("vip.fullprice@example.com", vip_map)
        self.assertIn("vip_high_frequency", vip_map["vip.fullprice@example.com"][1])
        self.assertIn("full_price_repeat_buyer", vip_map["vip.fullprice@example.com"][1])
        self.assertIn("recent.buyer@example.com", vip_map)
        self.assertIn("recent_buyer_cooldown_14d", vip_map["recent.buyer@example.com"][1])

        # Safe to receive the 15% promo: only atrisk & dormant buyers
        safe_emails = [row[0] for row in res["safe_audience"]]
        self.assertEqual(safe_emails, ["atrisk.buyer@example.com", "dormant.buyer@example.com"])

        # Estimated margin protected = 15% of VIP AOV (195) + 15% of recent buyer AOV (81) = 29.25 + 12.15 = 41.40
        self.assertAlmostEqual(s["est_margin_protected_total"], 41.40, places=2)

    def test_auto_detects_discount_from_template_and_blocks_broken_template(self):
        tpl = BROKEN_TPL.read_text(encoding="utf-8")
        res = mg.evaluate_preflight(
            KLAVIYO_EXPORT,
            orders_path=SHOPIFY_ORDERS,
            template_html=tpl,
            subject="15% off today",
            as_of=date(2026, 6, 1),
        )
        self.assertEqual(res["summary"]["gate_status"], "BLOCKED_TEMPLATE")
        self.assertTrue(res["summary"]["is_promotional_send"])
        self.assertEqual(res["summary"]["discount_pct"], 15.0)
        self.assertEqual(res["summary"]["excluded_vip_margin_guard"], 2)

    def test_non_promo_send_does_not_exclude_vips(self):
        tpl = CLEAN_TPL.read_text(encoding="utf-8")
        res = mg.evaluate_preflight(
            KLAVIYO_EXPORT,
            orders_path=SHOPIFY_ORDERS,
            template_html=tpl,
            subject="New harvest in stock",
            preheader="Fresh seasonal single-origin lot",
            as_of=date(2026, 6, 1),
        )
        self.assertFalse(res["summary"]["is_promotional_send"])
        self.assertEqual(res["summary"]["excluded_vip_margin_guard"], 0)
        safe_emails = [row[0] for row in res["safe_audience"]]
        self.assertIn("vip.fullprice@example.com", safe_emails)
        self.assertIn("recent.buyer@example.com", safe_emails)


class TestMarginGuardHubSpot(unittest.TestCase):
    def test_reads_native_hubspot_contacts_export(self):
        res = mg.evaluate_preflight(
            HUBSPOT_EXPORT,
            discount_pct=20.0,
            as_of=date(2026, 6, 1),
        )
        self.assertEqual(res["summary"]["audience_format"], "hubspot_contacts_export")
        supp_map = {row[0]: row[1] for row in res["gdpr_suppressions"]}
        self.assertEqual(supp_map["pending.doi@example.com"], "unconfirmed_doi")
        self.assertEqual(supp_map["unsub.customer@example.com"], "opted_out")
        self.assertEqual(supp_map["nonmarketing@example.com"], "non_marketing_contact")
        self.assertEqual(supp_map["bounced@example.com"], "hard_bounce")
        # vip.fullprice has 3 deals -> protected; atrisk.buyer -> safe
        self.assertEqual([r[0] for r in res["vip_exclusions"]], ["vip.fullprice@example.com"])
        self.assertEqual([r[0] for r in res["safe_audience"]], ["atrisk.buyer@example.com"])

    def test_cli_writes_all_operational_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            code = mg.main([
                "--audience", str(KLAVIYO_EXPORT),
                "--orders", str(SHOPIFY_ORDERS),
                "--discount-pct", "15",
                "--as-of", "2026-06-01",
                "--out", str(out_dir),
            ])
            self.assertEqual(code, 0)
            for fname in (
                "vip_discount_exclusions.csv",
                "gdpr_suppression_list.csv",
                "safe_send_audience.csv",
                "preflight_audit.json",
                "preflight_report.html",
            ):
                self.assertTrue((out_dir / fname).exists(), fname)
            audit = json.loads((out_dir / "preflight_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["excluded_vip_margin_guard"], 2)


if __name__ == "__main__":
    unittest.main()
