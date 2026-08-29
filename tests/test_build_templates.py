"""Checks on the generated email templates.

Run from the repository root:

    python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import build_templates as bt  # noqa: E402


class TestCopySet(unittest.TestCase):
    def test_one_template_per_flow_email(self):
        keys = [e["key"] for e in bt.EMAILS]
        self.assertEqual(keys, ["1.1", "1.2", "2.1", "2.2", "2.3", "3.1", "3.2"])

    def test_every_email_has_the_parts_a_send_needs(self):
        for e in bt.EMAILS:
            with self.subTest(e["key"]):
                self.assertTrue(e["name"])
                self.assertTrue(e["preheader"], "preheader drives the inbox preview")
                self.assertTrue(e["heading"])
                self.assertTrue(e["body"])
                self.assertEqual(len(e["cta"]), 2)


class TestRenderedHtml(unittest.TestCase):
    """The failures that would only show up after a real send."""

    def test_unsubscribe_tag_present_in_both_parts(self):
        # A custom HTML template does not inherit Klaviyo's footer. Without
        # this tag the send breaches consent design and the one-click
        # unsubscribe rule, and there is no way to notice from the editor.
        for e in bt.EMAILS:
            with self.subTest(e["key"]):
                self.assertIn("{% unsubscribe %}", bt.render_html(e))
                self.assertIn("{% unsubscribe %}", bt.render_text(e))

    def test_first_name_always_has_a_default(self):
        # A bare {{ first_name }} prints the raw tag to anyone with no first
        # name. The default filter degrades to an empty string instead.
        bare = re.compile(r"\{\{\s*first_name\s*\}\}")
        for e in bt.EMAILS:
            with self.subTest(e["key"]):
                self.assertIsNone(bare.search(bt.render_html(e)))

    def test_no_remote_images(self):
        for e in bt.EMAILS:
            with self.subTest(e["key"]):
                self.assertNotIn("<img", bt.render_html(e).lower())

    def test_plain_text_alternative_carries_no_markup(self):
        for e in bt.EMAILS:
            with self.subTest(e["key"]):
                self.assertNotIn("<p", bt.render_text(e))
                self.assertNotIn("<b>", bt.render_text(e))

    def test_cart_emails_link_to_the_checkout_event_variable(self):
        for e in bt.EMAILS:
            if e["key"].startswith("2."):
                with self.subTest(e["key"]):
                    self.assertIn("checkout_url", e["cta"][1])


class TestClaimsMatchTheStore(unittest.TestCase):
    """Copy can only promise what the storefront is configured to deliver.

    This is the class of bug that survives every proofread: the sentence is
    well written, the flow fires correctly, and the promise is simply not
    true. It surfaces as a support ticket, or as a chargeback.
    """

    DURATION = re.compile(r"\b\d+\s*(?:ore|h|giorni|settimane|mesi)\b", re.I)

    def test_no_duration_is_claimed_that_the_store_does_not_back(self):
        allowed = {"%d giorni" % bt.STORE_FACTS["returns_days"]}
        if bt.STORE_FACTS["shipping_sla"]:
            allowed.add(bt.STORE_FACTS["shipping_sla"])
        for e in bt.EMAILS:
            for m in self.DURATION.finditer(bt.render_text(e)):
                with self.subTest(e["key"], phrase=m.group(0)):
                    self.assertIn(
                        m.group(0).lower(),
                        allowed,
                        "copy states a duration the store does not publish",
                    )

    def test_winback_offer_matches_the_live_discount(self):
        text = bt.render_text(next(e for e in bt.EMAILS if e["key"] == "3.2"))
        self.assertIn(bt.STORE_FACTS["winback_code"], text)
        self.assertIn("%d%%" % bt.STORE_FACTS["winback_percent"], text)
        if bt.STORE_FACTS["winback_once_per_customer"]:
            self.assertIn("un solo utilizzo per cliente", text)


class TestFlowTemplateIds(unittest.TestCase):
    def test_every_email_targets_a_flow_template(self):
        # A missing id silently creates an orphan template that no flow points
        # at, and the send goes out with the old copy.
        for e in bt.EMAILS:
            with self.subTest(e["key"]):
                self.assertIn(e["key"], bt.FLOW_TEMPLATES)
        self.assertEqual(len(set(bt.FLOW_TEMPLATES.values())), len(bt.EMAILS))


class TestNetworkSafety(unittest.TestCase):
    """Rendering must never reach the network."""

    def setUp(self):
        real = urllib.request.urlopen

        def explode(*_a, **_k):
            raise AssertionError("rendering opened a socket")

        urllib.request.urlopen = explode
        self.addCleanup(setattr, urllib.request, "urlopen", real)

    def test_default_run_opens_no_socket(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(bt.main([]), 0)
        self.assertIn("Nothing left the machine", out.getvalue())


if __name__ == "__main__":
    unittest.main()
