"""Lifecycle stage -> Klaviyo profile property, behind a hard consent gate.

The segmentation rules are the ones from the analysis repo
(`digital-campaign-performance-dashboard/src/crm_lifecycle.py`): recency and
order count map every customer to New / Repeat / At risk / Dormant / Churned.
Here they run on the real orders of a live store instead of on the public
dataset, and the resulting stage is written to Klaviyo as a profile property.

What this script does NOT do, on purpose:

* It never grants marketing consent. A Klaviyo bulk import writes profile
  data; it does not subscribe anyone to email marketing. Consent is collected
  only by the double opt-in signup form (`docs/consent.md`). This script just
  refuses to touch anyone who has not already opted in.
* It never invents an email address. Rows without one are reported, not
  guessed. The public dataset used in the analysis repo is anonymous
  (customer ids, no contacts), which is exactly why it cannot be synced.

Segments and flows live in Klaviyo, not here: the property set below is read
by a Klaviyo segment definition, and the flow triggers on segment entry. See
`docs/flows.md`.

Pure standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

API_ROOT = "https://a.klaviyo.com/api/profile-bulk-import-jobs"
# Klaviyo pins behaviour to a dated revision; bumping it is a deliberate act.
API_REVISION = "2026-07-15"
# Klaviyo caps a bulk import at 10k profiles / 5MB. Stay well under both.
BATCH_SIZE = 1000

LIFECYCLE_ORDER = ["New", "Repeat", "At risk", "Dormant", "Churned"]
STAGE_ACTION = {
    "New": "Onboarding / second-purchase nudge",
    "Repeat": "Loyalty / cross-sell flow",
    "At risk": "Win-back sequence",
    "Dormant": "Reactivation offer",
    "Churned": "Low-cost reactivation, then sunset",
}
ELIGIBLE_CONSENT = "opted_in"


def lifecycle_stage(recency_days: int, orders: int) -> str:
    """Same thresholds as crm_lifecycle.real_lifecycle() in the analysis repo."""
    if recency_days <= 90:
        return "Repeat" if orders >= 2 else "New"
    if recency_days <= 180:
        return "At risk"
    if recency_days <= 365:
        return "Dormant"
    return "Churned"


def read_orders(path: Path) -> dict[str, dict]:
    """Aggregate an orders export to one row per email.

    Expected columns: email, order_date (YYYY-MM-DD), order_value_eur.
    A Shopify export needs renaming to these three; see data/README.md.
    """
    agg: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            email = (row.get("email") or "").strip().lower()
            if not email:
                continue
            order_date = datetime.strptime(row["order_date"].strip(), "%Y-%m-%d").date()
            value = float(row.get("order_value_eur") or 0)
            a = agg.setdefault(email, {"orders": 0, "last": order_date, "monetary": 0.0})
            a["orders"] += 1
            a["monetary"] += value
            if order_date > a["last"]:
                a["last"] = order_date
    return agg


def read_consent(path: Path) -> dict[str, str]:
    """Consent status per email, as exported from the signup form / ESP.

    Expected columns: email, consent_status. Anything that is not exactly
    opted_in is treated as not consenting.
    """
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            email = (row.get("email") or "").strip().lower()
            if email:
                out[email] = (row.get("consent_status") or "unknown").strip()
    return out


def build_profiles(
    orders: dict[str, dict], consent: dict[str, str], as_of: date
) -> tuple[list[dict], dict]:
    """Return (profiles to sync, suppression report).

    The consent gate is hard: it is applied before anything else and is never
    a scoring term. A customer with no consent record is suppressed as
    unknown, not optimistically included.
    """
    profiles: list[dict] = []
    suppressed: dict[str, int] = defaultdict(int)
    by_stage: dict[str, int] = defaultdict(int)

    for email, a in sorted(orders.items()):
        status = consent.get(email, "unknown")
        if status != ELIGIBLE_CONSENT:
            suppressed[status] += 1
            continue
        recency = (as_of - a["last"]).days
        stage = lifecycle_stage(recency, a["orders"])
        by_stage[stage] += 1
        profiles.append(
            {
                "type": "profile",
                "attributes": {
                    "email": email,
                    "properties": {
                        "lifecycle_stage": stage,
                        "lifecycle_recency_days": recency,
                        "lifecycle_orders": a["orders"],
                        "lifecycle_monetary_eur": round(a["monetary"], 2),
                        "lifecycle_recommended_action": STAGE_ACTION[stage],
                        # Two dates, because they answer different questions and
                        # collapsing them into one is how a pinned reference date
                        # stops being a disclosure. `computed_at` is when the
                        # script ran; `as_of` is the date the recency was measured
                        # from, and it is written onto the profile so anyone
                        # reading it in the ESP can see it was pinned.
                        "lifecycle_computed_at": date.today().isoformat(),
                        "lifecycle_as_of": as_of.isoformat(),
                    },
                },
            }
        )

    report = {
        "as_of": as_of.isoformat(),
        "customers_in_orders": len(orders),
        "eligible": len(profiles),
        "suppressed": sum(suppressed.values()),
        "suppressed_by_reason": dict(suppressed),
        "eligible_by_stage": {s: by_stage[s] for s in LIFECYCLE_ORDER if by_stage[s]},
    }
    return profiles, report


def _payload(batch: list[dict], list_id: str) -> dict:
    body: dict = {
        "data": {
            "type": "profile-bulk-import-job",
            "attributes": {"profiles": {"data": batch}},
        }
    }
    if list_id:
        body["data"]["relationships"] = {
            "lists": {"data": [{"type": "list", "id": list_id}]}
        }
    return body


def push(profiles: list[dict], list_id: str, api_key: str, live: bool) -> list[str]:
    """POST the profiles in batches. Returns the accepted job ids.

    Dry run is the default everywhere: without live=True this opens no socket.
    """
    job_ids: list[str] = []
    for start in range(0, len(profiles), BATCH_SIZE):
        batch = profiles[start : start + BATCH_SIZE]
        if not live:
            print(f"  [dry-run] batch of {len(batch)} profiles not sent")
            continue
        req = urllib.request.Request(
            API_ROOT,
            data=json.dumps(_payload(batch, list_id)).encode("utf-8"),
            headers={
                "Authorization": f"Klaviyo-API-Key {api_key}",
                "Content-Type": "application/vnd.api+json",
                "Accept": "application/vnd.api+json",
                "revision": API_REVISION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            # Klaviyo puts the useful part in the body, not the status line.
            detail = exc.read().decode("utf-8", "replace")[:500]
            sys.exit(f"Klaviyo rejected the batch ({exc.code}): {detail}")
        job_ids.append(payload.get("data", {}).get("id", "accepted"))
        print(f"  sent batch of {len(batch)} profiles -> job {job_ids[-1]}")
    return job_ids


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--orders", type=Path, default=Path("data/orders_example.csv"))
    p.add_argument("--consent", type=Path, default=Path("data/consent_example.csv"))
    p.add_argument("--list-id", default="", help="Klaviyo list id to attach profiles to")
    p.add_argument(
        "--as-of",
        default="",
        help="reference date YYYY-MM-DD for recency (default: today)",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="actually call Klaviyo; without it nothing leaves the machine",
    )
    p.add_argument("--report", type=Path, default=Path("reports/sync_report.json"))
    args = p.parse_args(argv)

    as_of = (
        datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of else date.today()
    )
    orders = read_orders(args.orders)
    consent = read_consent(args.consent)
    profiles, report = build_profiles(orders, consent, as_of)

    print(json.dumps(report, indent=2))
    if not profiles:
        print("\nNothing eligible to sync - the consent gate suppressed everyone.")
        return 0

    # The key is read from the environment, never from a flag: a private key
    # passed on the command line ends up in shell history and in `ps`.
    api_key = os.environ.get("KLAVIYO_API_KEY", "")
    if args.live and not api_key:
        sys.exit("KLAVIYO_API_KEY is not set - refusing to run --live.")
    if args.live and not args.list_id:
        sys.exit("--list-id is required with --live, or the import lands nowhere.")

    print(f"\n{'LIVE' if args.live else 'DRY RUN'}: {len(profiles)} profiles")
    report["job_ids"] = push(profiles, args.list_id, api_key, args.live)
    report["mode"] = "live" if args.live else "dry-run"

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
