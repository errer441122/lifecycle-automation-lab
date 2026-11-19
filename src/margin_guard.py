"""VIP Margin Guard & GDPR/Deliverability Pre-Send Audience Gate.

Bridges the gap ESPs do not enforce on their own before a promotional send:
1. GDPR & Deliverability Gate: blocks unsubscribed, hard-bounced, unknown,
   unproven consents (GDPR Art. 7(1)), single opt-in leaks (e.g., Shopify
   checkout checkbox bypassing DOI), and long-unengaged sunset profiles
   (protecting the 0.3% Google/Yahoo spam complaint threshold).
2. VIP & Full-Price Margin Guardrail: when a campaign carries a discount/coupon
   (explicitly declared or auto-detected from the email HTML by pre_send_check),
   identifies VIP/high-CLV customers, recent buyers within a cooldown window,
   and full-price loyalists who would buy without a discount — writing an
   exclusion CSV ready for Klaviyo or HubSpot and quantifying protected margin
   using the store's own historical AOV.

Usage:
    python src/margin_guard.py \\
      --audience fixtures/klaviyo_list_export_schema.csv \\
      --orders fixtures/shopify_orders_schema.csv \\
      --template fixtures/broken_klaviyo_email.html \\
      --subject "15% off for you" --discount-pct 15 \\
      --as-of 2026-06-01 --out build/preflight

Pure Python standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path

import platform_io as pio
import pre_send_check as psc

VIP_EXCL_HEADER = [
    "email",
    "exclusion_reason",
    "historical_orders",
    "historical_spend",
    "avg_order_value",
    "days_since_last_order",
    "discount_pct_avoided",
    "est_margin_protected_per_order",
]
GDPR_SUPP_HEADER = [
    "email",
    "suppression_reason",
    "consent_status",
    "consent_source",
    "consent_timestamp",
    "last_open",
]
SAFE_AUDIENCE_HEADER = [
    "email",
    "platform",
    "consent_verified",
    "discount_eligible",
    "historical_orders",
    "historical_spend",
    "days_since_last_order",
]


def _percentile_threshold(values: list[float], top_share: float) -> float:
    """Value at the top `top_share` cutoff (e.g., 0.20 -> 80th percentile)."""
    positive = sorted(v for v in values if v > 0)
    if not positive:
        return float("inf")
    idx = max(0, min(len(positive) - 1, int(len(positive) * (1.0 - top_share))))
    return positive[idx]


def evaluate_preflight(
    audience_path: Path,
    *,
    orders_path: Path | None = None,
    template_html: str | None = None,
    subject: str | None = None,
    preheader: str | None = None,
    esp: str = "auto",
    as_of: date | None = None,
    discount_pct: float | None = None,
    vip_top_share: float = 0.20,
    vip_min_orders: int = 3,
    recent_buyer_days: int = 14,
    sunset_inactive_days: int = 365,
    strict_double_optin: bool = True,
    require_utm: bool = True,
) -> dict:
    """Run complete pre-send QA across template + audience + order history."""
    ref_day = as_of or date.today()
    audience_fmt, profiles = pio.read_audience_consent(audience_path)

    orders_fmt = None
    orders_by_email: dict[str, dict] = {}
    if orders_path is not None:
        orders_fmt, events = pio.read_order_events(orders_path, as_of=ref_day)
        orders_by_email = pio.aggregate_orders_by_email(events)

    template_audit = None
    if template_html is not None:
        template_audit = psc.audit_template(
            template_html,
            subject=subject,
            preheader=preheader,
            esp=esp,
            require_utm=require_utm,
        )

    effective_discount = discount_pct
    if effective_discount is None and template_audit and template_audit["discount_offer"]["has_discount"]:
        effective_discount = template_audit["discount_offer"]["detected_discount_pct"] or 10.0
    is_promo = (effective_discount or 0.0) > 0

    # Combine spend/order counts from Shopify Orders (preferred) or ESP profile fields.
    enriched: dict[str, dict] = {}
    for email, prof in profiles.items():
        ord_rec = orders_by_email.get(email)
        orders_n = ord_rec["orders"] if ord_rec else prof["historic_orders"]
        spend = ord_rec["monetary"] if ord_rec else prof["historic_clv"]
        aov = ord_rec["aov"] if ord_rec else (round(spend / orders_n, 2) if orders_n else 0.0)
        last_order = ord_rec["last"] if ord_rec else None
        days_since = (ref_day - last_order).days if last_order else None
        full_price_only = ord_rec["full_price_only"] if ord_rec else False
        enriched[email] = {
            **prof,
            "orders": orders_n,
            "spend": round(spend, 2),
            "aov": aov,
            "days_since_last_order": days_since,
            "full_price_only": full_price_only,
        }

    vip_clv_cutoff = _percentile_threshold([c["spend"] for c in enriched.values()], vip_top_share)

    suppressed_rows: list[list[object]] = []
    suppression_counts: dict[str, int] = defaultdict(int)
    vip_exclusion_rows: list[list[object]] = []
    vip_reason_counts: dict[str, int] = defaultdict(int)
    safe_rows: list[list[object]] = []
    total_margin_protected = 0.0

    for email in sorted(enriched):
        c = enriched[email]
        supp_reason = None

        # Step 1: Hard GDPR & deliverability gate
        if c["status"] != "opted_in":
            supp_reason = c["status"]
        else:
            ts_day = pio._try_parse_day(c["timestamp"])
            if not c["source"] or ts_day is None or ts_day > ref_day:
                supp_reason = "missing_consent_proof"
            elif strict_double_optin and c["single_optin_leak"]:
                supp_reason = "single_optin_unconfirmed_leak"
            elif c["last_open"] is not None and (ref_day - c["last_open"]).days > sunset_inactive_days:
                supp_reason = f"sunset_unengaged_{sunset_inactive_days}d"

        if supp_reason:
            suppression_counts[supp_reason] += 1
            suppressed_rows.append([
                email,
                supp_reason,
                c["status"],
                c["source"],
                c["timestamp"],
                c["last_open"].isoformat() if c["last_open"] else "",
            ])
            continue

        # Step 2: VIP / Full-Price Margin Guardrail (only active when sending a discount)
        excl_reasons: list[str] = []
        if is_promo:
            if c["days_since_last_order"] is not None and c["days_since_last_order"] <= recent_buyer_days:
                excl_reasons.append(f"recent_buyer_cooldown_{recent_buyer_days}d")
            if c["orders"] >= vip_min_orders:
                excl_reasons.append("vip_high_frequency")
            elif c["spend"] > 0 and c["spend"] >= vip_clv_cutoff and len(enriched) >= 5:
                excl_reasons.append("vip_top_clv_tier")
            if c["full_price_only"] and c["orders"] >= 2:
                excl_reasons.append("full_price_repeat_buyer")

        if excl_reasons:
            primary_reason = "; ".join(excl_reasons)
            for r in excl_reasons:
                vip_reason_counts[r] += 1
            saved = round(c["aov"] * (effective_discount / 100.0), 2)
            total_margin_protected += saved
            vip_exclusion_rows.append([
                email,
                primary_reason,
                c["orders"],
                c["spend"],
                c["aov"],
                c["days_since_last_order"] if c["days_since_last_order"] is not None else "",
                effective_discount,
                saved,
            ])
            continue

        safe_rows.append([
            email,
            c["platform"],
            "true",
            "true" if is_promo else "not_applicable",
            c["orders"],
            c["spend"],
            c["days_since_last_order"] if c["days_since_last_order"] is not None else "",
        ])

    gate_status = "PASS"
    if template_audit and template_audit["blocker_count"] > 0:
        gate_status = "BLOCKED_TEMPLATE"
    elif len(safe_rows) == 0:
        gate_status = "BLOCKED_EMPTY_AUDIENCE"
    elif suppressed_rows or vip_exclusion_rows or (template_audit and template_audit["warning_count"] > 0):
        gate_status = "ACTION_REQUIRED_EXCLUSIONS"

    summary = {
        "as_of": ref_day.isoformat(),
        "gate_status": gate_status,
        "audience_format": audience_fmt,
        "orders_format": orders_fmt,
        "is_promotional_send": is_promo,
        "discount_pct": effective_discount or 0.0,
        "total_audience_input": len(enriched),
        "safe_to_send": len(safe_rows),
        "blocked_gdpr_deliverability": len(suppressed_rows),
        "excluded_vip_margin_guard": len(vip_exclusion_rows),
        "est_margin_protected_total": round(total_margin_protected, 2),
        "suppression_breakdown": dict(sorted(suppression_counts.items())),
        "vip_exclusion_breakdown": dict(sorted(vip_reason_counts.items())),
        "vip_clv_cutoff": None if vip_clv_cutoff == float("inf") else round(vip_clv_cutoff, 2),
        "template_audit": template_audit,
    }

    return {
        "summary": summary,
        "vip_exclusions_header": VIP_EXCL_HEADER,
        "vip_exclusions": vip_exclusion_rows,
        "vip_exclusions_csv": pio.to_csv_text(VIP_EXCL_HEADER, vip_exclusion_rows),
        "gdpr_suppressions_header": GDPR_SUPP_HEADER,
        "gdpr_suppressions": suppressed_rows,
        "gdpr_suppressions_csv": pio.to_csv_text(GDPR_SUPP_HEADER, suppressed_rows),
        "safe_audience_header": SAFE_AUDIENCE_HEADER,
        "safe_audience": safe_rows,
        "safe_audience_csv": pio.to_csv_text(SAFE_AUDIENCE_HEADER, safe_rows),
    }


def render_preflight_html(result: dict) -> str:
    """Render a self-contained executive pre-flight HTML audit report."""
    s = result["summary"]
    status_color = "#0b6e4f" if s["gate_status"] == "PASS" else (
        "#a3361f" if s["gate_status"].startswith("BLOCKED") else "#9a5b00"
    )
    tpl_html = ""
    if s["template_audit"]:
        ta = s["template_audit"]
        items = "".join(
            f"<li><strong>[{escape(i['severity'])}]</strong> ({escape(i['category'])}) {escape(i['message'])}</li>"
            for i in ta["issues"]
        ) or "<li>No template issues detected.</li>"
        tpl_html = (
            f"<h2>Template QA ({escape(ta['esp'].upper())} — {escape(ta['status'])})</h2>"
            f"<ul>{items}</ul>"
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Pre-Flight Audit Report</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:920px;margin:32px auto;padding:0 20px;color:#111827;line-height:1.5}}
.badge{{display:inline-block;padding:6px 14px;border-radius:999px;color:#fff;font-weight:700;background:{status_color}}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:20px 0}}
.card{{border:1px solid #d1d5db;border-radius:10px;padding:14px}}
.card b{{display:block;font-size:26px}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin-top:12px}}
th,td{{border-bottom:1px solid #e5e7eb;padding:8px;text-align:left}}
</style></head><body>
<h1>ESP Pre-Flight Audit Report</h1>
<p><span class="badge">{escape(s['gate_status'])}</span> &nbsp; As of {escape(s['as_of'])} · Source: {escape(s['audience_format'])}</p>
<div class="grid">
  <div class="card"><span>Input Audience</span><b>{s['total_audience_input']}</b></div>
  <div class="card"><span>Safe to Send</span><b>{s['safe_to_send']}</b></div>
  <div class="card"><span>GDPR / Deliverability Blocked</span><b>{s['blocked_gdpr_deliverability']}</b></div>
  <div class="card"><span>VIP Discount Exclusions</span><b>{s['excluded_vip_margin_guard']}</b></div>
  <div class="card"><span>Est. Margin Protected</span><b>{s['est_margin_protected_total']:,.2f}</b></div>
</div>
{tpl_html}
<p><small>Generated locally by ESP Pre-Flight QA & Margin Guard. Margin estimate = historical AOV x discount % avoided on excluded profiles.</small></p>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pre-flight GDPR, Deliverability & VIP Margin Guard.")
    p.add_argument("--audience", type=Path, required=True, help="Klaviyo, HubSpot, Shopify Customers, or consent CSV")
    p.add_argument("--orders", type=Path, help="Optional Shopify Orders export to enrich LTV/full-price rules")
    p.add_argument("--template", type=Path, help="Optional email HTML template to audit together with the audience")
    p.add_argument("--subject", help="Email subject line")
    p.add_argument("--preview", help="Email preview text")
    p.add_argument("--esp", choices=("auto", "klaviyo", "hubspot"), default="auto")
    p.add_argument("--discount-pct", type=float, default=None, help="Discount % in campaign (auto-detected if template given)")
    p.add_argument("--vip-min-orders", type=int, default=3)
    p.add_argument("--recent-buyer-days", type=int, default=14)
    p.add_argument("--sunset-days", type=int, default=365)
    p.add_argument("--allow-single-optin", action="store_true", help="Do not suppress unconfirmed single opt-in leaks")
    p.add_argument("--esp-auto-utm", action="store_true", help="Allow commercial links without hand-typed UTMs")
    p.add_argument("--as-of", default="", help="Reference date YYYY-MM-DD (default: today)")
    p.add_argument("--out", type=Path, default=Path("build/preflight"))
    args = p.parse_args(argv)

    as_of = pio.parse_day(args.as_of) if args.as_of else date.today()
    tpl_html = args.template.read_text(encoding="utf-8", errors="replace") if args.template else None

    result = evaluate_preflight(
        args.audience,
        orders_path=args.orders,
        template_html=tpl_html,
        subject=args.subject,
        preheader=args.preview,
        esp=args.esp,
        as_of=as_of,
        discount_pct=args.discount_pct,
        vip_min_orders=args.vip_min_orders,
        recent_buyer_days=args.recent_buyer_days,
        sunset_inactive_days=args.sunset_days,
        strict_double_optin=not args.allow_single_optin,
        require_utm=not args.esp_auto_utm,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "vip_discount_exclusions.csv").write_text(result["vip_exclusions_csv"], encoding="utf-8", newline="\n")
    (args.out / "gdpr_suppression_list.csv").write_text(result["gdpr_suppressions_csv"], encoding="utf-8", newline="\n")
    (args.out / "safe_send_audience.csv").write_text(result["safe_audience_csv"], encoding="utf-8", newline="\n")
    (args.out / "preflight_audit.json").write_text(json.dumps(result["summary"], indent=2) + "\n", encoding="utf-8")
    (args.out / "preflight_report.html").write_text(render_preflight_html(result), encoding="utf-8", newline="\n")

    s = result["summary"]
    print(json.dumps(s, indent=2))
    print(f"\nOutputs written to {args.out}/")
    return 1 if s["gate_status"].startswith("BLOCKED") else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
