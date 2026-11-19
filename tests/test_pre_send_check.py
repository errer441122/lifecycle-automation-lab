"""Unit tests for multi-ESP Pre-Flight Template QA (Klaviyo Liquid & HubSpot HubL)."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import build_templates as bt  # noqa: E402
import platform_io as pio  # noqa: E402
import pre_send_check as psc  # noqa: E402

KLAVIYO_UNSUB = '<a href="{% unsubscribe %}">Unsubscribe</a>'
HUBSPOT_UNSUB = '<a href="{{ unsubscribe_link }}">Unsubscribe</a>'
CLEAN_LINK = '<a href="https://shop.example.com/sale?utm_source=klaviyo&utm_medium=email&utm_campaign=lifecycle_winback">Shop</a>'


def run_check(body: str = "Hello", subject: str = "Short subject", preheader: str = "Adds context",
              unsub: str = KLAVIYO_UNSUB, link: str = CLEAN_LINK, esp: str = "auto",
              require_utm: bool = True) -> dict:
    html = f"<p>{body}</p>{link}{unsub}"
    return psc.audit_template(
        html,
        text=f"{body} {unsub}",
        subject=subject,
        preheader=preheader,
        esp=esp,
        require_utm=require_utm,
    )


class TestReferenceTemplates(unittest.TestCase):
    def test_every_reference_template_passes_strict_qa(self):
        for e in bt.EMAILS:
            with self.subTest(e["key"]):
                audit = psc.audit_template(
                    bt.render_html(e),
                    text=bt.render_text(e),
                    subject=e["subject"],
                    preheader=e["preheader"],
                    esp="klaviyo",
                    require_utm=True,
                )
                self.assertEqual(audit["issues"], [])


class TestKlaviyoAndHubSpotChecks(unittest.TestCase):
    def test_clean_klaviyo_passes(self):
        self.assertEqual(run_check()["status"], "PASS")

    def test_catches_missing_and_empty_fallbacks_in_klaviyo(self):
        res1 = run_check("Hi {{ first_name }},")
        self.assertEqual(res1["blocker_count"], 1)
        self.assertIn("no fallback", res1["issues"][0]["message"])

        res2 = run_check("Hi {{ first_name|default:'' }},")
        self.assertEqual(res2["blocker_count"], 1)
        self.assertIn("empty fallback", res2["issues"][0]["message"])

    def test_catches_hubspot_hubl_fallbacks_and_auto_detects_esp(self):
        good_hs = run_check(
            "Hi {{ contact.firstname|default('there') }},",
            unsub=HUBSPOT_UNSUB,
            link='<a href="https://app.example.com/?utm_source=hubspot&utm_medium=email&utm_campaign=q2_nurture">Go</a>',
        )
        self.assertEqual(good_hs["esp"], "hubspot")
        self.assertEqual(good_hs["status"], "PASS")

        bad_hs = run_check(
            "Hi {{ contact.firstname }},",
            unsub="",
            link='<a href="https://app.example.com/pricing">Pricing</a>',
        )
        self.assertEqual(bad_hs["esp"], "hubspot")
        cats = {i["category"] for i in bad_hs["issues"]}
        self.assertEqual(cats, {"personalization", "utm", "compliance"})

    def test_commercial_link_without_utm_is_blocked_by_default(self):
        res = run_check(link='<a href="https://shop.example.com/collections/all">Shop</a>')
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any(i["category"] == "utm" for i in res["issues"]))

        # Allowed when ESP auto-UTM mode is explicitly enabled
        ok = run_check(link='<a href="https://shop.example.com/collections/all">Shop</a>', require_utm=False)
        self.assertEqual(ok["status"], "PASS")

    def test_ga4_reference_flags_unknown_utm_source(self):
        ga4_ref = pio.read_ga4_utm_reference(ROOT / "fixtures" / "ga4_traffic_reference_schema.csv")
        html = (
            '<p>Hi</p>'
            '<a href="https://shop.example.com/?utm_source=mailchimp_typo&utm_medium=email&utm_campaign=spring">Go</a>'
            f'{KLAVIYO_UNSUB}'
        )
        res = psc.audit_template(html, ga4_ref=ga4_ref)
        self.assertTrue(any("GA4 reference" in i["message"] for i in res["issues"]))

    def test_detects_gmail_clipping_and_missing_alt_text(self):
        huge = "<p>" + ("x" * 105_000) + '</p><img src="https://cdn.example.com/a.jpg">' + CLEAN_LINK + KLAVIYO_UNSUB
        res = psc.audit_template(huge)
        messages = " ".join(i["message"] for i in res["issues"])
        self.assertIn("Gmail will clip", messages)
        self.assertIn("alt text", messages)

    def test_detects_discount_offer_and_coupon_code(self):
        html = (ROOT / "fixtures" / "broken_klaviyo_email.html").read_text(encoding="utf-8")
        res = psc.audit_template(html, subject="15% off today", preheader="Use SPRING15")
        self.assertTrue(res["discount_offer"]["has_discount"])
        self.assertEqual(res["discount_offer"]["detected_discount_pct"], 15.0)
        self.assertIn("SPRING15", res["discount_offer"]["detected_codes"])

    def test_cli_runs_on_broken_fixture(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = psc.main([str(ROOT / "fixtures" / "broken_hubspot_email.html"), "--subject", "x" * 60])
        self.assertEqual(code, 1)
        self.assertIn("BLOCKER", out.getvalue())
        self.assertIn("PROMO DETECTED", out.getvalue())


if __name__ == "__main__":
    unittest.main()
