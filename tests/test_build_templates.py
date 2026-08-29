"""Checks on the generated email templates.

Run from the repository root:

    python -m unittest discover -s tests
"""

from __future__ import annotations

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


class TestPushSafety(unittest.TestCase):
    """A dry run must never reach the network."""

    def setUp(self):
        real = urllib.request.urlopen

        def explode(*_a, **_k):
            raise AssertionError("dry run opened a socket")

        urllib.request.urlopen = explode
        self.addCleanup(setattr, urllib.request, "urlopen", real)

    def test_dry_run_sends_nothing(self):
        self.assertIsNone(bt.create_template(bt.EMAILS[0], "key", live=False))


if __name__ == "__main__":
    unittest.main()
