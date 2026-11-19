"""GDPR-gated Lifecycle Sync for Klaviyo & HubSpot (from native platform CSV exports).

Reads unmodified exports from:
- Orders: Shopify Orders (Orders > Export) or canonical orders CSV
- Consent/Audience: Klaviyo Lists & Segments Export, HubSpot Contacts Export,
  Shopify Customers Export, or canonical consent CSV

Assigns lifecycle stages (New, Repeat, At risk, Dormant, Churned) using either
standard 90/180/365-day rules or dynamically calibrated thresholds derived from
the store's real second-order interval (`--auto-thresholds`), applies a hard
GDPR Art. 7(1) consent & Double Opt-In leak gate, and outputs:
- Klaviyo profile import CSV (or live bulk-import API push with `--live`)
- HubSpot contact import CSV (`--hubspot-out`)
- GDPR suppression list CSV with exact suppression reasons (`--suppressed`)

What this script never does:
- It never grants marketing consent or subscribes anyone.
- Dry-run is the default everywhere: without `--live` it opens no socket.

Pure Python standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

import platform_io as pio
import repeat_timing as rt

API_ROOT = "https://a.klaviyo.com/api/profile-bulk-import-jobs"
API_REVISION = "2026-07-15"
BATCH_SIZE = 1000

LIFECYCLE_ORDER = ["New", "Repeat", "At risk", "Dormant", "Churned"]
STAGE_ACTION = {
    "New": "Onboarding / second-purchase nudge (no discount)",
    "Repeat": "Loyalty / cross-sell flow (protect full-price margin)",
    "At risk": "Win-back sequence (eligible for controlled offer)",
    "Dormant": "Reactivation offer",
    "Churned": "Final re-permission touch, then sunset",
}
ELIGIBLE_CONSENT = "opted_in"

KLAVIYO_CSV_HEADER = [
    "Email",
    "lifecycle_stage",
    "lifecycle_recency_days",
    "lifecycle_orders",
    "lifecycle_monetary",
    "discount_eligible",
    "lifecycle_recommended_action",
    "lifecycle_as_of",
    "consent_source",
    "consent_timestamp",
]
HUBSPOT_CSV_HEADER = [
    "Email",
    "Lifecycle Stage Custom",
    "Days Since Last Order",
    "Orders Count",
    "Total Historical Spend",
    "Discount Eligible",
    "Recommended CRM Action",
    "Consent Verified",
    "Consent Source",
    "Consent Timestamp",
]

# Re-export helpers for clean imports in tests and callers.
safe_cell = pio.safe_cell
parse_day = pio.parse_day
parse_amount = pio.parse_amount


def lifecycle_stage(
    recency_days: int,
    orders: int,
    *,
    active_days: int = 90,
    at_risk_days: int = 180,
    dormant_days: int = 365,
) -> str:
    if recency_days <= active_days:
        return "Repeat" if orders >= 2 else "New"
    if recency_days <= at_risk_days:
        return "At risk"
    if recency_days <= dormant_days:
        return "Dormant"
    return "Churned"


def read_orders(path: Path, as_of: date | None = None) -> dict[str, dict]:
    """Read Shopify or canonical orders CSV and aggregate per customer email."""
    _fmt, events = pio.read_order_events(path, as_of=as_of)
    return pio.aggregate_orders_by_email(events)


def read_consent(path: Path) -> dict[str, dict]:
    """Read Klaviyo, HubSpot, Shopify Customers, or canonical consent CSV."""
    _fmt, profiles = pio.read_audience_consent(path)
    return profiles


def build_profiles(
    orders: dict[str, dict],
    consent: dict[str, dict],
    as_of: date,
    *,
    active_days: int = 90,
    at_risk_days: int = 180,
    dormant_days: int = 365,
    strict_double_optin: bool = False,
) -> tuple[list[dict], dict, list[tuple[str, str]]]:
    """Return (profiles to sync, report dict, suppression list of (email, reason))."""
    profiles: list[dict] = []
    held: list[tuple[str, str]] = []
    suppressed: dict[str, int] = defaultdict(int)
    by_stage: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    single_optin_leaks: list[str] = []

    for email, a in sorted(orders.items()):
        record = consent.get(email, {})
        status = record.get("status", "unknown")
        if status != ELIGIBLE_CONSENT:
            suppressed[status] += 1
            held.append((email, status))
            continue
        given = pio._try_parse_day(record.get("timestamp", ""))
        if not record.get("source") or given is None or given > as_of:
            suppressed["opted_in_without_proof"] += 1
            held.append((email, "opted_in_without_proof"))
            continue
        if record.get("single_optin_leak"):
            single_optin_leaks.append(email)
            if strict_double_optin:
                suppressed["single_optin_unconfirmed_leak"] += 1
                held.append((email, "single_optin_unconfirmed_leak"))
                continue

        by_source[record["source"]] += 1
        recency = (as_of - a["last"]).days
        stage = lifecycle_stage(
            recency,
            a["orders"],
            active_days=active_days,
            at_risk_days=at_risk_days,
            dormant_days=dormant_days,
        )
        by_stage[stage] += 1
        # Only At risk / Dormant customers qualify for promotional discounts by default.
        discount_eligible = stage in {"At risk", "Dormant"} and not (
            a.get("full_price_only") and a["orders"] >= 3
        )
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
                        "discount_eligible": discount_eligible,
                        "lifecycle_recommended_action": STAGE_ACTION[stage],
                        "lifecycle_computed_at": date.today().isoformat(),
                        "lifecycle_as_of": as_of.isoformat(),
                        "consent_source": record["source"],
                        "consent_timestamp": record["timestamp"],
                        "single_optin_leak_flag": bool(record.get("single_optin_leak")),
                    },
                },
            }
        )

    report = {
        "as_of": as_of.isoformat(),
        "thresholds": {
            "active_days": active_days,
            "at_risk_days": at_risk_days,
            "dormant_days": dormant_days,
        },
        "strict_double_optin": strict_double_optin,
        "customers_in_orders": len(orders),
        "eligible": len(profiles),
        "suppressed": sum(suppressed.values()),
        "suppressed_by_reason": dict(sorted(suppressed.items())),
        "eligible_by_stage": {s: by_stage[s] for s in LIFECYCLE_ORDER if by_stage[s]},
        "eligible_by_consent_source": dict(sorted(by_source.items())),
        "single_optin_leaks_detected": len(single_optin_leaks),
    }
    return profiles, report, held


def to_klaviyo_csv(profiles: list[dict]) -> str:
    rows = []
    for p in profiles:
        a = p["attributes"]["properties"]
        rows.append([
            p["attributes"]["email"],
            a["lifecycle_stage"],
            a["lifecycle_recency_days"],
            a["lifecycle_orders"],
            a["lifecycle_monetary_eur"],
            str(a["discount_eligible"]).lower(),
            a["lifecycle_recommended_action"],
            a["lifecycle_as_of"],
            a["consent_source"],
            a["consent_timestamp"],
        ])
    return pio.to_csv_text(KLAVIYO_CSV_HEADER, rows)


def to_hubspot_csv(profiles: list[dict]) -> str:
    rows = []
    for p in profiles:
        a = p["attributes"]["properties"]
        rows.append([
            p["attributes"]["email"],
            a["lifecycle_stage"],
            a["lifecycle_recency_days"],
            a["lifecycle_orders"],
            a["lifecycle_monetary_eur"],
            "Yes" if a["discount_eligible"] else "No",
            a["lifecycle_recommended_action"],
            "Verified",
            a["consent_source"],
            a["consent_timestamp"],
        ])
    return pio.to_csv_text(HUBSPOT_CSV_HEADER, rows)


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
    """POST profiles in batches to Klaviyo API. Dry-run opens no socket."""
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
            detail = exc.read().decode("utf-8", "replace")[:500]
            sent = ", ".join(job_ids) or "none"
            sys.exit(
                f"Klaviyo rejected the batch starting at profile {start} "
                f"({exc.code}): {detail}\nAlready accepted jobs: {sent}"
            )
        job_ids.append(payload.get("data", {}).get("id", "accepted"))
        print(f"  sent batch of {len(batch)} profiles -> job {job_ids[-1]}")
    return job_ids


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="GDPR-gated Lifecycle Sync for Klaviyo & HubSpot.")
    p.add_argument("--orders", type=Path, default=Path("fixtures/shopify_orders_schema.csv"))
    p.add_argument("--consent", type=Path, default=Path("fixtures/klaviyo_list_export_schema.csv"))
    p.add_argument("--list-id", default="", help="Klaviyo list ID (required with --live)")
    p.add_argument("--as-of", default="", help="Reference date YYYY-MM-DD (default: today)")
    p.add_argument("--auto-thresholds", action="store_true", help="Calibrate active_days from second-order repeat timing")
    p.add_argument("--strict-doi", action="store_true", help="Suppress single opt-in leaks (e.g., Shopify checkbox)")
    p.add_argument("--live", action="store_true", help="Push to Klaviyo API (dry-run by default)")
    p.add_argument("--report", type=Path, default=Path("build/sync_report.json"))
    p.add_argument("--suppressed", type=Path, help="Write GDPR suppression list CSV")
    p.add_argument("--klaviyo-out", type=Path, help="Write Klaviyo bulk-import CSV")
    p.add_argument("--hubspot-out", type=Path, help="Write HubSpot contact import CSV")
    args = p.parse_args(argv)

    as_of = pio.parse_day(args.as_of) if args.as_of else date.today()
    orders_fmt, events = pio.read_order_events(args.orders, as_of=as_of)
    orders = pio.aggregate_orders_by_email(events)
    consent_fmt, consent = pio.read_audience_consent(args.consent)

    active_days = 90
    if args.auto_thresholds:
        days_map = defaultdict(set)
        for ev in events:
            days_map[ev["email"]].add(ev["order_date"])
        timing = rt.repeat_timing(days_map)
        active_days = timing["recommended_at_risk_days"]
    at_risk_days = max(active_days * 2, 180)

    profiles, report, held = build_profiles(
        orders,
        consent,
        as_of,
        active_days=active_days,
        at_risk_days=at_risk_days,
        strict_double_optin=args.strict_doi,
    )
    report["orders_format"] = orders_fmt
    report["consent_format"] = consent_fmt

    print(json.dumps(report, indent=2))
    if args.suppressed:
        args.suppressed.parent.mkdir(parents=True, exist_ok=True)
        args.suppressed.write_text(
            pio.to_csv_text(["email", "reason"], [[e, r] for e, r in held]),
            encoding="utf-8",
            newline="\n",
        )
    if args.klaviyo_out:
        args.klaviyo_out.parent.mkdir(parents=True, exist_ok=True)
        args.klaviyo_out.write_text(to_klaviyo_csv(profiles), encoding="utf-8", newline="\n")
    if args.hubspot_out:
        args.hubspot_out.parent.mkdir(parents=True, exist_ok=True)
        args.hubspot_out.write_text(to_hubspot_csv(profiles), encoding="utf-8", newline="\n")

    if not profiles:
        print("\nNothing eligible to sync - consent gate suppressed all contacts.")
        return 0

    api_key = os.environ.get("KLAVIYO_API_KEY", "")
    if args.live and not api_key:
        sys.exit("KLAVIYO_API_KEY is not set - refusing to run --live.")
    if args.live and not args.list_id:
        sys.exit("--list-id is required with --live.")

    print(f"\n{'LIVE' if args.live else 'DRY RUN'}: {len(profiles)} profiles")
    report["job_ids"] = push(profiles, args.list_id, api_key, args.live)
    report["mode"] = "live" if args.live else "dry-run"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
