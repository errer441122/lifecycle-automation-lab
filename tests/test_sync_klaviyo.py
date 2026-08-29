"""Behavioural checks for the lifecycle -> Klaviyo bridge.

Run from the repository root:

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sync_klaviyo as sk  # noqa: E402


class TestLifecycleStage(unittest.TestCase):
    """The thresholds must stay identical to the analysis repo."""

    def test_new_vs_repeat_within_90_days(self):
        self.assertEqual(sk.lifecycle_stage(10, 1), "New")
        self.assertEqual(sk.lifecycle_stage(10, 2), "Repeat")

    def test_boundaries_are_inclusive(self):
        self.assertEqual(sk.lifecycle_stage(90, 1), "New")
        self.assertEqual(sk.lifecycle_stage(91, 1), "At risk")
        self.assertEqual(sk.lifecycle_stage(180, 5), "At risk")
        self.assertEqual(sk.lifecycle_stage(181, 5), "Dormant")
        self.assertEqual(sk.lifecycle_stage(365, 5), "Dormant")
        self.assertEqual(sk.lifecycle_stage(366, 5), "Churned")

    def test_order_count_stops_mattering_after_90_days(self):
        # A high-frequency buyer who went quiet is still At risk.
        self.assertEqual(sk.lifecycle_stage(120, 40), "At risk")

    def test_every_stage_has_an_action(self):
        for stage in sk.LIFECYCLE_ORDER:
            self.assertIn(stage, sk.STAGE_ACTION)


class TestConsentGate(unittest.TestCase):
    """Consent is a hard gate applied before anything else."""

    AS_OF = date(2026, 6, 1)
    ORDERS = {
        "yes@example.com": {"orders": 3, "last": date(2026, 5, 20), "monetary": 300.0},
        "no@example.com": {"orders": 9, "last": date(2026, 5, 20), "monetary": 900.0},
        "missing@example.com": {"orders": 5, "last": date(2026, 5, 20), "monetary": 500.0},
    }
    CONSENT = {"yes@example.com": "opted_in", "no@example.com": "opted_out"}

    def setUp(self):
        self.profiles, self.report = sk.build_profiles(
            self.ORDERS, self.CONSENT, self.AS_OF
        )

    def test_only_opted_in_profiles_are_built(self):
        emails = [p["attributes"]["email"] for p in self.profiles]
        self.assertEqual(emails, ["yes@example.com"])

    def test_absent_consent_record_is_suppressed_not_assumed(self):
        self.assertEqual(self.report["suppressed_by_reason"]["unknown"], 1)
        self.assertEqual(self.report["suppressed_by_reason"]["opted_out"], 1)
        self.assertEqual(self.report["suppressed"], 2)

    def test_high_value_does_not_buy_its_way_past_the_gate(self):
        # no@example.com is the best customer in the file and still excluded.
        self.assertNotIn(
            "no@example.com", [p["attributes"]["email"] for p in self.profiles]
        )

    def test_stage_property_is_written(self):
        props = self.profiles[0]["attributes"]["properties"]
        self.assertEqual(props["lifecycle_stage"], "Repeat")
        self.assertEqual(props["lifecycle_recency_days"], 12)
        self.assertEqual(props["lifecycle_recommended_action"], sk.STAGE_ACTION["Repeat"])


class TestPushSafety(unittest.TestCase):
    """A dry run must never reach the network."""

    def setUp(self):
        self._real_urlopen = urllib.request.urlopen

        def explode(*_args, **_kwargs):
            raise AssertionError("dry run opened a socket")

        urllib.request.urlopen = explode
        self.addCleanup(setattr, urllib.request, "urlopen", self._real_urlopen)

    def test_dry_run_sends_nothing(self):
        profiles = [{"type": "profile", "attributes": {"email": "a@example.com"}}]
        self.assertEqual(sk.push(profiles, "LIST", "key", live=False), [])

    def test_payload_omits_list_relationship_when_no_list_given(self):
        body = sk._payload([], "")
        self.assertNotIn("relationships", body["data"])
        body = sk._payload([], "ABC123")
        self.assertEqual(
            body["data"]["relationships"]["lists"]["data"][0]["id"], "ABC123"
        )


if __name__ == "__main__":
    unittest.main()
