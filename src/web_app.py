"""Browser bridge called by docs/index.html via Pyodide.

Runs the exact same Python functions and tests as the CLI locally inside the
user's browser: no file is ever uploaded and no network request is made.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import margin_guard as mg
import platform_io as pio
import pre_send_check as psc
import repeat_timing as rt
import sync_klaviyo as sk


def _guarded(fn):
    def run(*args):
        try:
            return json.dumps(fn(*args), default=str)
        except (SystemExit, ValueError, KeyError) as exc:
            return json.dumps({"error": str(exc) or exc.__class__.__name__})
    return run


@_guarded
def check_template(
    html: str,
    subject: str = "",
    preview: str = "",
    esp: str = "auto",
    require_utm: bool = True,
    ga4_path: str = "",
) -> dict:
    ga4_ref = pio.read_ga4_utm_reference(Path(ga4_path)) if ga4_path else None
    audit = psc.audit_template(
        html,
        subject=subject if subject else None,
        preheader=preview if preview else None,
        esp=esp or "auto",
        require_utm=bool(require_utm),
        ga4_ref=ga4_ref,
    )
    audit["problems"] = [i["message"] for i in audit["issues"]]
    return audit


@_guarded
def preflight_guard(
    audience_path: str,
    orders_path: str = "",
    template_html: str = "",
    subject: str = "",
    preview: str = "",
    discount_pct: str = "",
    as_of: str = "",
    vip_min_orders: int = 3,
    recent_buyer_days: int = 14,
    strict_doi: bool = True,
    require_utm: bool = True,
) -> dict:
    ref_day = pio.parse_day(as_of) if as_of else date.today()
    disc = float(discount_pct) if str(discount_pct).strip() else None
    res = mg.evaluate_preflight(
        Path(audience_path),
        orders_path=Path(orders_path) if orders_path else None,
        template_html=template_html if template_html.strip() else None,
        subject=subject if subject else None,
        preheader=preview if preview else None,
        as_of=ref_day,
        discount_pct=disc,
        vip_min_orders=int(vip_min_orders),
        recent_buyer_days=int(recent_buyer_days),
        strict_double_optin=bool(strict_doi),
        require_utm=bool(require_utm),
    )
    res["report_html"] = mg.render_preflight_html(res)
    return res


@_guarded
def lifecycle(
    orders_path: str,
    consent_path: str,
    as_of: str = "",
    strict_doi: bool = False,
    auto_thresholds: bool = False,
) -> dict:
    ref_day = pio.parse_day(as_of) if as_of else date.today()
    orders_fmt, events = pio.read_order_events(Path(orders_path), as_of=ref_day)
    orders = pio.aggregate_orders_by_email(events)
    consent_fmt, consent = pio.read_audience_consent(Path(consent_path))

    active_days = 90
    if auto_thresholds:
        days_map = defaultdict(set)
        for ev in events:
            days_map[ev["email"]].add(ev["order_date"])
        active_days = rt.repeat_timing(days_map)["recommended_at_risk_days"]
    at_risk_days = max(active_days * 2, 180)

    profiles, report, held = sk.build_profiles(
        orders,
        consent,
        ref_day,
        active_days=active_days,
        at_risk_days=at_risk_days,
        strict_double_optin=bool(strict_doi),
    )
    report["orders_format"] = orders_fmt
    report["consent_format"] = consent_fmt

    header = [
        "email",
        "lifecycle_stage",
        "days_since_last_order",
        "orders",
        "spend",
        "discount_eligible",
        "consent_source",
        "consent_timestamp",
    ]
    rows = []
    for p in profiles:
        a = p["attributes"]["properties"]
        rows.append([
            sk.safe_cell(p["attributes"]["email"]),
            a["lifecycle_stage"],
            a["lifecycle_recency_days"],
            a["lifecycle_orders"],
            a["lifecycle_monetary_eur"],
            str(a["discount_eligible"]).lower(),
            sk.safe_cell(a["consent_source"]),
            sk.safe_cell(a["consent_timestamp"]),
        ])
    held_rows = [[sk.safe_cell(email), reason] for email, reason in held]
    return {
        "report": report,
        "header": header,
        "profiles": rows,
        "suppressed": held_rows,
        "klaviyo_csv": sk.to_klaviyo_csv(profiles),
        "hubspot_csv": sk.to_hubspot_csv(profiles),
        "profiles_csv": sk.to_klaviyo_csv(profiles),
        "suppressed_csv": pio.to_csv_text(["email", "reason"], held_rows),
    }


@_guarded
def timing(orders_path: str) -> dict:
    days = rt.order_days(Path(orders_path))
    if not days:
        raise ValueError("No valid orders with a customer and a date in this file.")
    t = rt.repeat_timing(days)
    return {
        "customers": t["customers"],
        "min_customers": rt.MIN_CUSTOMERS,
        "share_back_by_day": {str(k): v for k, v in t["share_back_by_day"].items()},
        "median_days_if_back": t["median_days_if_back"],
        "recommended_at_risk_days": t["recommended_at_risk_days"],
        "calibration_source": t["calibration_source"],
    }
