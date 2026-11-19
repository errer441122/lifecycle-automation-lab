"""Unit tests for GDPR-gated Lifecycle Sync (Klaviyo & HubSpot native exports)."""

from __future__ import annotations

import sys
import tempfile
import unittest
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sync_klaviyo as sk  # noqa: E402

SHOPIFY_FIXTURE = ROOT / "fixtures" / "shopify_orders_schema.csv"
KLAVIYO_FIXTURE = ROOT / "fixtures" / "klaviyo_list_export_schema.csv"
HUBSPOT_FIXTURE = ROOT / "fixtures" / "hubspot_contacts_schema.csv"


class TestLifecycleStage(unittest.TestCase):
    def test_default_boundaries(self):
        self.assertEqual(sk.lifecycle_stage(10, 1), "New")
        self.assertEqual(sk.lifecycle_stage(10, 2), "Repeat")
        self.assertEqual(sk.lifecycle_stage(90, 1), "New")
        self.assertEqual(sk.lifecycle_stage(91, 1), "At risk")
        self.assertEqual(sk.lifecycle_stage(180, 5), "At risk")
        self.assertEqual(sk.lifecycle_stage(181, 5), "Dormant")
        self.assertEqual(sk.lifecycle_stage(365, 5), "Dormant")
        self.assertEqual(sk.lifecycle_stage(366, 5), "Churned")

    def test_custom_calibrated_threshold(self):
        self.assertEqual(sk.lifecycle_stage(55, 1, active_days=60), "New")
        self.assertEqual(sk.lifecycle_stage(65, 1, active_days=60), "At risk")


class TestNativeExportsAndConsentGate(unittest.TestCase):
    def test_shopify_orders_folding_and_voided_exclusion(self):
        orders = sk.read_orders(SHOPIFY_FIXTURE, date(2026, 6, 1))
        # #2001 has 2 line items -> 1 order; total 3 orders for vip.fullprice
        self.assertEqual(orders["vip.fullprice@example.com"]["orders"], 3)
        self.assertAlmostEqual(orders["vip.fullprice@example.com"]["monetary"], 585.00)
        self.assertTrue(orders["vip.fullprice@example.com"]["full_price_only"])
        # #2006 is voided -> skipped
        self.assertEqual(orders["atrisk.buyer@example.com"]["orders"], 1)

    def test_klaviyo_native_export_sync_and_strict_doi_gate(self):
        orders = sk.read_orders(SHOPIFY_FIXTURE, date(2026, 6, 1))
        consent = sk.read_consent(KLAVIYO_FIXTURE)
        profiles, report, held = sk.build_profiles(orders, consent, date(2026, 6, 1), strict_double_optin=True)
        emails = [p["attributes"]["email"] for p in profiles]
        self.assertIn("vip.fullprice@example.com", emails)
        self.assertIn("atrisk.buyer@example.com", emails)
        self.assertNotIn("checkbox.leak@example.com", emails)
        self.assertNotIn("unsub.customer@example.com", emails)
        self.assertNotIn("noproof.optin@example.com", emails)
        held_map = dict(held)
        self.assertEqual(held_map["checkbox.leak@example.com"], "single_optin_unconfirmed_leak")
        self.assertEqual(held_map["unsub.customer@example.com"], "opted_out")
        self.assertEqual(held_map["noproof.optin@example.com"], "opted_in_without_proof")
        self.assertEqual(report["single_optin_leaks_detected"], 1)

    def test_hubspot_export_generates_hubspot_and_klaviyo_csvs(self):
        orders = sk.read_orders(SHOPIFY_FIXTURE, date(2026, 6, 1))
        consent = sk.read_consent(HUBSPOT_FIXTURE)
        profiles, _report, _held = sk.build_profiles(orders, consent, date(2026, 6, 1), strict_double_optin=True)
        hs_csv = sk.to_hubspot_csv(profiles)
        kl_csv = sk.to_klaviyo_csv(profiles)
        self.assertTrue(hs_csv.startswith("Email,Lifecycle Stage Custom,"))
        self.assertTrue(kl_csv.startswith("Email,lifecycle_stage,"))
        self.assertIn("vip.fullprice@example.com", hs_csv)

    def test_orders_after_as_of_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.csv"
            path.write_text(
                "email,order_date,order_value_eur\na@example.com,2026-01-10,10\na@example.com,2026-07-01,99\n",
                encoding="utf-8",
            )
            agg = sk.read_orders(path, date(2026, 6, 1))
            self.assertEqual(agg["a@example.com"]["orders"], 1)


class TestPushSafety(unittest.TestCase):
    def setUp(self):
        self._real_urlopen = urllib.request.urlopen

        def explode(*_args, **_kwargs):
            raise AssertionError("dry run opened a socket")

        urllib.request.urlopen = explode
        self.addCleanup(setattr, urllib.request, "urlopen", self._real_urlopen)

    def test_dry_run_sends_nothing(self):
        profiles = [{"type": "profile", "attributes": {"email": "a@example.com"}}]
        self.assertEqual(sk.push(profiles, "LIST", "key", live=False), [])


if __name__ == "__main__":
    unittest.main()
