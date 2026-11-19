"""Checks on the second-order timing.

Run from the repository root:

    python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import repeat_timing as rt  # noqa: E402


def d(s: str) -> date:
    return date.fromisoformat(s)


class TestRepeatTiming(unittest.TestCase):
    DAYS = {
        "early@example.com": {d("2024-01-03"), d("2024-01-20")},  # first month of the file: left out
        "a@example.com": {d("2024-02-01"), d("2024-03-02")},       # back after 30 days
        "b@example.com": {d("2024-02-10"), d("2024-08-28")},       # back after 200 days
        "c@example.com": {d("2024-03-05")},                        # never back
        "late@example.com": {d("2025-06-01"), d("2025-06-02")},    # under a year of data: left out
    }

    def test_counts_only_customers_with_a_full_year(self):
        t = rt.repeat_timing(self.DAYS)
        self.assertEqual(t["customers"], 3)
        self.assertAlmostEqual(t["share_back_by_day"][30], 1 / 3)
        self.assertAlmostEqual(t["share_back_by_day"][180], 1 / 3)
        self.assertAlmostEqual(t["share_back_by_day"][365], 2 / 3)
        self.assertEqual(t["median_days_if_back"], 115)

    def test_runs_on_a_shopify_export_and_warns_when_the_file_is_small(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rt.main(["--orders", str(ROOT / "fixtures" / "shopify_orders_schema.csv")])
        self.assertEqual(code, 0)
        self.assertIn("No customer has a full 365-day observation window", out.getvalue())


if __name__ == "__main__":
    unittest.main()
