"""Second-order repeat timing: calibrate post-purchase and win-back delays from real orders.

Reads a native Shopify Orders export (Orders > Export) or a canonical orders CSV
and computes, for customers with a full 365-day observation window, the share who
re-ordered by day 30, 60, 90, 180 and 365 plus the median days to second order.

Also provides `recommended_at_risk_days()` so `sync_klaviyo.py` can dynamically
calibrate the Active -> At risk boundary to the store's actual purchase cadence
instead of relying on hardcoded 90-day thresholds.

Usage:
    python src/repeat_timing.py --orders fixtures/shopify_orders_schema.csv

Pure Python standard library.
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import platform_io as pio

CHECKPOINTS = (30, 60, 90, 180, 365)
MIN_CUSTOMERS = 30
DEFAULT_AT_RISK_DAYS = 90


def order_days(path: Path) -> dict[str, set[date]]:
    """Distinct calendar dates on which each customer placed a valid order."""
    _fmt, events = pio.read_order_events(path)
    days: dict[str, set[date]] = defaultdict(set)
    for ev in events:
        days[ev["email"]].add(ev["order_date"])
    return days


def repeat_timing(days: dict[str, set[date]]) -> dict:
    """Cumulative repeat share at checkpoints and median days to 2nd order."""
    if not days:
        return {
            "customers": 0,
            "share_back_by_day": {k: 0.0 for k in CHECKPOINTS},
            "median_days_if_back": None,
            "recommended_at_risk_days": DEFAULT_AT_RISK_DAYS,
            "calibration_source": "default_90d",
        }
    window = CHECKPOINTS[-1]
    all_days = [d for ds in days.values() for d in ds]
    data_end = max(all_days) + timedelta(days=1)
    first_month = min(all_days).strftime("%Y-%m")
    gaps: list[int | None] = []
    for ds in days.values():
        first, *later = sorted(ds)
        if first.strftime("%Y-%m") == first_month or (data_end - first).days < window:
            continue
        gaps.append((later[0] - first).days if later else None)
    back = [g for g in gaps if g is not None and g <= window]
    median = statistics.median(back) if back else None

    if len(gaps) >= MIN_CUSTOMERS and median is not None:
        # Calibrate At-risk start to ~1.5x the store's median repeat interval (clamped 45..180d).
        rec_days = max(45, min(180, int(round(median * 1.5))))
        source = "calibrated_from_orders"
    else:
        rec_days = DEFAULT_AT_RISK_DAYS
        source = "default_90d"

    return {
        "customers": len(gaps),
        "share_back_by_day": {
            k: (sum(1 for g in back if g <= k) / len(gaps) if gaps else 0.0) for k in CHECKPOINTS
        },
        "median_days_if_back": median,
        "recommended_at_risk_days": rec_days,
        "calibration_source": source,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--orders", type=Path, default=Path("fixtures/shopify_orders_schema.csv"))
    args = p.parse_args(argv)

    days = order_days(args.orders)
    if not days:
        print("No valid orders with an email and a date in this file.")
        return 1
    t = repeat_timing(days)
    n = t["customers"]
    if not n:
        print(
            "No customer has a full 365-day observation window after their first order yet. "
            f"Using default At-risk threshold ({DEFAULT_AT_RISK_DAYS} days)."
        )
        return 0
    if n < MIN_CUSTOMERS:
        print(f"Only {n} customers have a full year of history: treat these figures as indicative.\n")
    print(f"Customers with a full year of data: {n:,}")
    for day, share in t["share_back_by_day"].items():
        print(f"  ordered again by day {day:>3}: {share:5.0%}")
    if t["median_days_if_back"] is None:
        print("\nNo repeat orders observed within 365 days.")
    else:
        m = t["median_days_if_back"]
        print(f"\nMedian days to second order: {m:.0f} days.")
        print(
            f"Recommended post-purchase nudge: before day {m:.0f}. "
            f"Recommended At-risk win-back threshold: day {t['recommended_at_risk_days']} "
            f"({t['calibration_source']})."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
