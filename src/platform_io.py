"""Native CSV readers for standard Martech platform exports.

Auto-detects unmodified CSV exports from:
- Shopify Orders (Orders > Export)
- Shopify Customers (Customers > Export)
- Klaviyo Lists & Segments (Export List/Segment to CSV)
- HubSpot Contacts (CRM > Contacts > Export)
- GA4 Traffic Acquisition (Reports > Acquisition > Traffic acquisition > Export CSV)
- Simple canonical CSV fallback (orders / consent)

Handles Excel-re-saved files (UTF-8 BOM, UTF-16, Windows-1252, semicolons, tabs,
decimal commas, ISO and DD/MM/YYYY dates) and neutralizes CSV formula injection.

Pure Python standard library (runs identically in CLI and browser via Pyodide).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d")
NOT_A_SALE = {"refunded", "voided"}

SHOPIFY_ORDER_COLS = {"Name", "Email", "Created at", "Total"}
SHOPIFY_CUSTOMER_COLS = {"Email", "Accepts Email Marketing"}
KLAVIYO_EXPORT_SIGNALS = {
    "Email Marketing Consent",
    "Email Marketing Consent Timestamp",
    "Email Marketing Consent Method",
    "Klaviyo ID",
}
HUBSPOT_EXPORT_SIGNALS = {
    "Marketing contact status",
    "Unsubscribed from all email",
    "Legal basis for processing contact's data",
    "Original Traffic Source",
}
VALUE_COLS = ("order_value_eur", "order_value", "value", "total", "amount", "order_value_gbp")

# Consent methods known to skip Double Opt-In confirmation in real setups.
SINGLE_OPTIN_LEAK_SOURCES = {
    "shopify",
    "shopify_checkout",
    "shopify_checkout_checkbox",
    "shopify_footer",
    "shopify_webhook",
    "manual_import",
    "list_upload",
    "csv_import",
    "back_in_stock_single",
}


def safe_cell(value: object) -> str:
    """Prefix spreadsheet formula triggers so Excel never executes user input."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def read_text_tolerant(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a CSV/TSV skipping leading comment lines (e.g., GA4 export headers)."""
    text = read_text_tolerant(path)
    lines = text.splitlines()
    # GA4 CSV exports begin with '#' metadata rows before the real header.
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].lstrip().startswith("#")):
        start += 1
    body = "\n".join(lines[start:])
    if not body.strip():
        return [], []
    header_line = lines[start]
    delimiter = max(",;\t", key=header_line.count)
    reader = csv.DictReader(io.StringIO(body, newline=""), delimiter=delimiter)
    fieldnames = [f.strip() for f in (reader.fieldnames or [])]
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        cleaned = {(k.strip() if k else ""): (v or "").strip() for k, v in raw_row.items()}
        if any(cleaned.values()):
            rows.append(cleaned)
    return fieldnames, rows


def to_csv_text(header: list[str], rows: list[list[object]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe_cell(c) if isinstance(c, str) else c for c in row])
    return buf.getvalue()


def parse_day(text: str | None) -> date | None:
    """Parse YYYY-MM-DD[ time], DD/MM/YYYY[ time], or ISO timestamps; None if empty."""
    raw = (text or "").strip()
    if not raw:
        return None
    head = raw.split()[0].split("T")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"date {raw!r} is not a recognised format (YYYY-MM-DD or DD/MM/YYYY)")


def parse_amount(text: str | None) -> float:
    """Parse monetary amounts like '49.90', '49,90', '€ 1.234,56', '$1,234.56'."""
    cleaned = "".join(ch for ch in (text or "") if ch.isdigit() or ch in ",.-")
    if not cleaned or cleaned in ("-", ".", ","):
        return 0.0
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    return float(cleaned)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"true", "yes", "1", "y", "si", "sì"}


def _col(columns: list[str], *candidates: str) -> str | None:
    by_lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand in columns:
            return cand
        if cand.lower() in by_lower:
            return by_lower[cand.lower()]
    return None


def detect_orders_format(columns: list[str]) -> str:
    col_set = set(columns)
    if SHOPIFY_ORDER_COLS <= col_set:
        return "shopify_orders"
    if _col(columns, "email", "customer_id", "customer") and _col(columns, "order_date", "created_at", "date"):
        return "canonical_orders"
    return "unknown"


def read_order_events(path: Path, as_of: date | None = None) -> tuple[str, list[dict]]:
    """Return (detected_format, list of normalized order dicts).

    Normalized order fields:
      email, order_id, order_date (date), order_value (float),
      discount_amount (float), discount_code (str), country (str)
    """
    columns, rows = read_csv_rows(path)
    fmt = detect_orders_format(columns)
    if fmt == "unknown":
        raise ValueError(
            "Unrecognised orders CSV: expected a Shopify Orders export "
            "(Name, Email, Created at, Total) or a CSV with email/customer_id and order_date."
        )

    events: list[dict] = []
    if fmt == "shopify_orders":
        folded: dict[str, dict[str, str]] = {}
        for row in rows:
            name = row.get("Name", "")
            if not name:
                continue
            target = folded.setdefault(name, {})
            for k, v in row.items():
                if v and not target.get(k):
                    target[k] = v
        for name, o in folded.items():
            if o.get("Cancelled at") or o.get("Financial Status", "").lower() in NOT_A_SALE:
                continue
            email = (o.get("Email") or "").strip().lower()
            when = parse_day(o.get("Created at"))
            if not email or when is None:
                continue
            if as_of and when > as_of:
                continue
            events.append({
                "email": email,
                "order_id": name,
                "order_date": when,
                "order_value": parse_amount(o.get("Total")),
                "discount_amount": parse_amount(o.get("Discount Amount")),
                "discount_code": (o.get("Discount Code") or "").strip(),
                "country": (o.get("Billing Country") or o.get("Shipping Country") or "").strip(),
            })
        return fmt, events

    who_col = _col(columns, "email", "customer_id", "customer")
    date_col = _col(columns, "order_date", "created_at", "date")
    val_col = _col(columns, *VALUE_COLS)
    disc_col = _col(columns, "discount_amount", "discount")
    code_col = _col(columns, "discount_code", "coupon")
    id_col = _col(columns, "order_id", "id", "name")
    country_col = _col(columns, "country", "billing_country")

    for idx, row in enumerate(rows, start=1):
        email = (row.get(who_col or "") or "").strip().lower()
        when = parse_day(row.get(date_col or ""))
        if not email or when is None:
            continue
        if as_of and when > as_of:
            continue
        events.append({
            "email": email,
            "order_id": row.get(id_col or "") or f"#{idx}",
            "order_date": when,
            "order_value": parse_amount(row.get(val_col or "")) if val_col else 0.0,
            "discount_amount": parse_amount(row.get(disc_col or "")) if disc_col else 0.0,
            "discount_code": row.get(code_col or "") if code_col else "",
            "country": row.get(country_col or "") if country_col else "",
        })
    return fmt, events


def aggregate_orders_by_email(events: list[dict]) -> dict[str, dict]:
    """Aggregate normalized order events to one customer record per email."""
    agg: dict[str, dict] = {}
    for ev in events:
        email = ev["email"]
        c = agg.setdefault(
            email,
            {
                "orders": 0,
                "first": ev["order_date"],
                "last": ev["order_date"],
                "monetary": 0.0,
                "discounted_orders": 0,
                "total_discount": 0.0,
                "country": ev["country"],
            },
        )
        c["orders"] += 1
        c["monetary"] += ev["order_value"]
        if ev["discount_amount"] > 0 or ev["discount_code"]:
            c["discounted_orders"] += 1
            c["total_discount"] += ev["discount_amount"]
        if ev["order_date"] < c["first"]:
            c["first"] = ev["order_date"]
        if ev["order_date"] > c["last"]:
            c["last"] = ev["order_date"]
        if not c["country"] and ev["country"]:
            c["country"] = ev["country"]
    for c in agg.values():
        c["monetary"] = round(c["monetary"], 2)
        c["aov"] = round(c["monetary"] / c["orders"], 2) if c["orders"] else 0.0
        c["full_price_only"] = c["orders"] > 0 and c["discounted_orders"] == 0
    return agg


def detect_audience_format(columns: list[str]) -> str:
    col_set = set(columns)
    if col_set & KLAVIYO_EXPORT_SIGNALS:
        return "klaviyo_list_export"
    if col_set & HUBSPOT_EXPORT_SIGNALS:
        return "hubspot_contacts_export"
    if SHOPIFY_CUSTOMER_COLS <= col_set:
        return "shopify_customers_export"
    if _col(columns, "email") and _col(columns, "consent_status"):
        return "canonical_consent"
    if _col(columns, "email"):
        return "email_list_only"
    return "unknown"


def _normalise_klaviyo_status(raw_status: str, suppression_reason: str) -> str:
    if suppression_reason:
        low_sup = suppression_reason.lower()
        if "bounce" in low_sup:
            return "hard_bounce"
        if "spam" in low_sup or "complaint" in low_sup:
            return "spam_complaint"
        return "opted_out"
    low = raw_status.strip().lower()
    if low in {"subscribed", "opted_in", "opt_in", "true", "yes"}:
        return "opted_in"
    if low in {"unsubscribed", "opted_out", "suppressed", "false", "no"}:
        return "opted_out"
    if low in {"never_subscribed", "never subscribed", "pending"}:
        return "never_subscribed"
    return "unknown"


def _is_single_optin_leak(source: str, doi_flag: str | None = None) -> bool:
    if doi_flag is not None and doi_flag.strip():
        low_flag = doi_flag.strip().lower()
        if low_flag in {"false", "no", "0", "single", "single_opt_in", "pending", "confirmation pending"}:
            return True
        if low_flag in {"true", "yes", "1", "double", "double_opt_in", "user clicked confirmation", "confirmed"}:
            return False
    norm = source.strip().lower().replace(" ", "_").replace("-", "_")
    if "double_opt" in norm or "doi" in norm or "confirmed" in norm:
        return False
    return norm in SINGLE_OPTIN_LEAK_SOURCES or "checkbox" in norm or "manual" in norm


def read_audience_consent(path: Path) -> tuple[str, dict[str, dict]]:
    """Read native Klaviyo, HubSpot, Shopify Customers, or canonical consent CSV.

    Returns (detected_format, {email: normalized_profile_record}).
    """
    columns, rows = read_csv_rows(path)
    fmt = detect_audience_format(columns)
    if fmt == "unknown":
        raise ValueError(
            "Unrecognised audience/consent CSV: expected a Klaviyo List/Segment export, "
            "HubSpot Contacts export, Shopify Customers export, or a CSV with an Email column."
        )

    email_col = _col(columns, "Email", "email")
    profiles: dict[str, dict] = {}

    for row in rows:
        email = (row.get(email_col or "") or "").strip().lower()
        if not email:
            continue

        if fmt == "klaviyo_list_export":
            raw_status = row.get(_col(columns, "Email Marketing Consent") or "", "")
            supp_reason = row.get(_col(columns, "Email Suppression Reason", "Suppression Reason") or "", "")
            status = _normalise_klaviyo_status(raw_status, supp_reason)
            source = row.get(
                _col(columns, "Email Marketing Consent Method", "Consent Method", "Initial Source") or "",
                "",
            )
            timestamp = row.get(_col(columns, "Email Marketing Consent Timestamp", "Consent Timestamp") or "", "")
            doi_flag = row.get(_col(columns, "Email Marketing Double Opt-In", "Double Opt-In") or "", "")
            last_open_raw = row.get(_col(columns, "Last Open", "Last Email Open") or "", "")
            hist_orders = int(parse_amount(row.get(_col(columns, "Historic Number Of Orders", "Orders") or "", "0")))
            hist_clv = parse_amount(row.get(_col(columns, "Historic CLV", "Total Spent") or "", "0"))
            profiles[email] = {
                "email": email,
                "status": status,
                "source": source,
                "timestamp": timestamp,
                "single_optin_leak": status == "opted_in" and _is_single_optin_leak(source, doi_flag),
                "last_open": _try_parse_day(last_open_raw),
                "historic_orders": hist_orders,
                "historic_clv": round(hist_clv, 2),
                "platform": "klaviyo",
            }
            continue

        if fmt == "hubspot_contacts_export":
            unsub = _truthy(row.get(_col(columns, "Unsubscribed from all email", "Opted out of email") or "", ""))
            bounce = row.get(_col(columns, "Email hard bounce reason") or "", "")
            mkt_status = (row.get(_col(columns, "Marketing contact status") or "", "")).lower()
            legal_basis = row.get(_col(columns, "Legal basis for processing contact's data") or "", "")
            doi_status = row.get(
                _col(columns, "Double opt-in status", "Marketing email confirmation status") or "",
                "",
            )
            source = row.get(_col(columns, "Original Traffic Source", "Original Source") or "", "")
            timestamp = row.get(
                _col(columns, "Marketing email confirmation date", "Opt-in date", "Create Date") or "",
                "",
            )
            last_open_raw = row.get(_col(columns, "Recent Sales Email Opened Date", "Last marketing email open date") or "", "")
            hist_orders = int(parse_amount(row.get(_col(columns, "Number of Associated Deals", "Total Orders") or "", "0")))
            hist_clv = parse_amount(row.get(_col(columns, "Total Revenue", "Amount") or "", "0"))

            if bounce:
                status = "hard_bounce"
            elif unsub:
                status = "opted_out"
            elif mkt_status and "non-marketing" in mkt_status:
                status = "non_marketing_contact"
            elif doi_status.lower() in {"confirmation pending", "pending", "unconfirmed"}:
                status = "unconfirmed_doi"
            elif "freely given consent" in legal_basis.lower() or "marketing contact" in mkt_status:
                status = "opted_in"
            else:
                status = "unknown"

            single_leak = status == "opted_in" and _is_single_optin_leak(source or legal_basis, doi_status)
            profiles[email] = {
                "email": email,
                "status": status,
                "source": source or legal_basis,
                "timestamp": timestamp,
                "single_optin_leak": single_leak,
                "last_open": _try_parse_day(last_open_raw),
                "historic_orders": hist_orders,
                "historic_clv": round(hist_clv, 2),
                "platform": "hubspot",
            }
            continue

        if fmt == "shopify_customers_export":
            accepts = _truthy(row.get(_col(columns, "Accepts Email Marketing") or "", ""))
            hist_orders = int(parse_amount(row.get(_col(columns, "Total Orders") or "", "0")))
            hist_clv = parse_amount(row.get(_col(columns, "Total Spent") or "", "0"))
            profiles[email] = {
                "email": email,
                "status": "opted_in" if accepts else "opted_out",
                "source": "shopify_customer_export" if accepts else "shopify_unsubscribed",
                # Shopify Customers export does not include a GDPR consent proof timestamp.
                "timestamp": "",
                "single_optin_leak": accepts,
                "last_open": None,
                "historic_orders": hist_orders,
                "historic_clv": round(hist_clv, 2),
                "platform": "shopify",
            }
            continue

        if fmt == "canonical_consent":
            status = (row.get(_col(columns, "consent_status") or "") or "unknown").strip().lower()
            source = row.get(_col(columns, "consent_source") or "", "")
            timestamp = row.get(_col(columns, "consent_timestamp") or "", "")
            last_open_raw = row.get(_col(columns, "last_open") or "", "")
            profiles[email] = {
                "email": email,
                "status": status,
                "source": source,
                "timestamp": timestamp,
                "single_optin_leak": status == "opted_in" and _is_single_optin_leak(source),
                "last_open": _try_parse_day(last_open_raw),
                "historic_orders": int(parse_amount(row.get(_col(columns, "orders") or "", "0"))),
                "historic_clv": round(parse_amount(row.get(_col(columns, "spend", "clv") or "", "0")), 2),
                "platform": "canonical",
            }
            continue

        # email_list_only: audience list with no consent metadata attached.
        profiles[email] = {
            "email": email,
            "status": "unknown",
            "source": "",
            "timestamp": "",
            "single_optin_leak": False,
            "last_open": None,
            "historic_orders": 0,
            "historic_clv": 0.0,
            "platform": "unknown",
        }

    return fmt, profiles


def read_ga4_utm_reference(path: Path) -> dict[str, set[str]]:
    """Read a GA4 Traffic Acquisition CSV export to extract active sources/mediums/campaigns."""
    columns, rows = read_csv_rows(path)
    sm_col = _col(columns, "Session source / medium", "First user source / medium", "source / medium")
    camp_col = _col(columns, "Session campaign", "First user campaign", "campaign")
    sources: set[str] = set()
    mediums: set[str] = set()
    campaigns: set[str] = set()
    for row in rows:
        if sm_col and "/" in row.get(sm_col, ""):
            src, med = (p.strip().lower() for p in row[sm_col].split("/", 1))
            if src and src != "(direct)":
                sources.add(src)
            if med and med != "(none)":
                mediums.add(med)
        if camp_col:
            c = row.get(camp_col, "").strip()
            if c and not c.startswith("("):
                campaigns.add(c)
    return {"sources": sources, "mediums": mediums, "campaigns": campaigns}


def _try_parse_day(text: str | None) -> date | None:
    try:
        return parse_day(text)
    except ValueError:
        return None
