# ESP Pre-Flight QA, VIP Margin Guard & GDPR Consent Gate

An operational pre-send governance toolkit for **Klaviyo**, **HubSpot**, **Shopify**, and **GA4** teams.

ESPs send whatever is marked Live — they do not stop human deployment errors, single opt-in GDPR leaks, or promotional discounts accidentally shipped to VIPs who would buy at full price. This tool sits directly in front of campaign and flow launches, running on unmodified platform CSV exports in the browser or CLI.

**[Launch the browser workbench (zero upload — runs locally via Pyodide)](https://errer441122.github.io/lifecycle-automation-lab/)**

---

## Operational Gap Covered

| Failure mode ESPs do not block | What this tool enforces before send |
| --- | --- |
| Personalization tags with missing or empty fallbacks (`Ciao {{ first_name\|default:'' }},` or `{{ contact.firstname }}`) | Blocks deploy across both **Klaviyo Liquid** and **HubSpot HubL** syntax |
| Commercial links missing UTMs or breaking GA4 naming rules | Blocks un-tagged links and optionally cross-checks `utm_source` against an active **GA4 Traffic Acquisition** CSV |
| Mobile subject truncation (>50 chars), duplicate preview text, Gmail clipping (>102 KB), missing `alt`, missing unsubscribe token | Structured `BLOCKER` / `WARNING` audit with non-zero CI exit code |
| **Promotional discounts sent to VIPs & recent full-price buyers** | Auto-detects coupon/discount offers in the template, joins the audience export with **Shopify Orders**, extracts a **VIP Exclusion CSV**, and quantifies protected margin from historical AOV |
| **GDPR Art. 7(1) & deliverability leaks** | Suppresses unsubscribed, hard-bounced, unconfirmed Double Opt-In, single opt-in leaks (e.g., Shopify checkout checkbox bypassing DOI), missing consent proof, and 365-day sunset profiles (<0.3% Google/Yahoo complaint threshold) |

---

## Day-1 Native Platform Exports Supported

Every parser auto-detects native column headers, UTF-8/UTF-16/Windows-1252 encodings, Excel semicolons, decimal commas (`49,90`), ISO and `DD/MM/YYYY` dates, and neutralizes CSV formula injection on all exports.

| Platform | Native Export Accepted | Auto-Detected Fields Used |
| --- | --- | --- |
| **Klaviyo** | *Lists & Segments > Export CSV* + HTML templates | `Email`, `Email Marketing Consent`, `Email Marketing Consent Timestamp`, `Email Marketing Consent Method`, `Email Marketing Double Opt-In`, `Email Suppression Reason`, `Historic Number Of Orders`, `Historic CLV`, `Last Open` |
| **HubSpot** | *CRM > Contacts > Export CSV* + HubL HTML | `Email`, `Marketing contact status`, `Unsubscribed from all email`, `Email hard bounce reason`, `Legal basis for processing contact's data`, `Double opt-in status`, `Original Traffic Source`, `Number of Associated Deals`, `Total Revenue` |
| **Shopify** | *Orders > Export* & *Customers > Export* | Multi-line-item folding on `Name`, exclusion of `Cancelled at` / `refunded` / `voided`, `Total`, `Discount Amount`, `Discount Code`, `Accepts Email Marketing` |
| **GA4** | *Reports > Acquisition > Traffic acquisition > Export CSV* | Comment-row stripping + `Session source / medium`, `Session campaign` |

---

## Immediate Operational Outputs

1. **`vip_discount_exclusions.csv`** — Upload directly as an exclusion segment in Klaviyo or HubSpot for promotional sends; includes per-customer exclusion reason (`vip_high_frequency`, `vip_top_clv_tier`, `full_price_repeat_buyer`, `recent_buyer_cooldown_14d`) and estimated margin protected (`historical AOV × discount %`).
2. **`gdpr_suppression_list.csv`** — Contacts blocked with explicit compliance/deliverability reason (`opted_out`, `hard_bounce`, `unconfirmed_doi`, `single_optin_unconfirmed_leak`, `missing_consent_proof`, `sunset_unengaged_365d`).
3. **`safe_send_audience.csv`** + **`preflight_report.html`** + **`preflight_audit.json`** — Clean send-ready audience and PASS/FAIL pre-flight report.
4. **`klaviyo_profile_sync.csv`** & **`hubspot_contact_sync.csv`** — Lifecycle stage (`New`, `Repeat`, `At risk`, `Dormant`, `Churned`) and `discount_eligible` properties ready for bulk import or live Klaviyo API push (`--live`, dry-run by default).

---

## CLI Usage (Pure Python 3.11 Standard Library — Zero Install)

```bash
# 1. Run full pre-flight audit on a Klaviyo/HubSpot template + audience + Shopify orders
python src/margin_guard.py \
  --audience fixtures/klaviyo_list_export_schema.csv \
  --orders fixtures/shopify_orders_schema.csv \
  --template fixtures/broken_klaviyo_email.html \
  --subject "15% off spring collection" \
  --as-of 2026-06-01 \
  --out build/preflight

# 2. Standalone multi-ESP template QA (with optional GA4 UTM reference)
python src/pre_send_check.py fixtures/broken_hubspot_email.html \
  --subject "Upgrade now and save 20%" \
  --ga4-ref fixtures/ga4_traffic_reference_schema.csv

# 3. GDPR-gated lifecycle sync (dry-run by default; outputs Klaviyo + HubSpot CSVs)
python src/sync_klaviyo.py \
  --orders fixtures/shopify_orders_schema.csv \
  --consent fixtures/klaviyo_list_export_schema.csv \
  --as-of 2026-06-01 --strict-doi --auto-thresholds \
  --klaviyo-out build/klaviyo_sync.csv \
  --hubspot-out build/hubspot_sync.csv \
  --suppressed build/gdpr_suppression_list.csv

# 4. Run unit test suite
python -m unittest discover -s tests -v
```

---

## Repository Structure

| Path | Purpose |
| --- | --- |
| `src/platform_io.py` | Auto-detecting native CSV readers for Shopify, Klaviyo, HubSpot, and GA4 |
| `src/pre_send_check.py` | Multi-ESP template QA (Liquid & HubL), required UTM checks, and promo detection |
| `src/margin_guard.py` | VIP / full-price discount protection & GDPR/deliverability pre-send audience gate |
| `src/sync_klaviyo.py` | GDPR-gated lifecycle stage sync (Klaviyo API/CSV + HubSpot CSV) |
| `src/repeat_timing.py` | Second-order timing curve used to calibrate At-risk thresholds from order history |
| `src/web_app.py` & `docs/index.html` | Client-side Pyodide browser workbench (zero server upload) |
| `fixtures/` | Minimal schema test fixtures (`example.com` only) for automated parser & QA tests |
| `tests/` | Unit tests covering Klaviyo, HubSpot, Shopify, GA4, Excel quirks, and API dry-run safety |
| `docs/field-notes/` | Hands-on Klaviyo, Shopify & DNS (DKIM/DMARC) QA field notes from a real sandbox deployment (Smart Sending collision, Shopify checkbox DOI bypass, DNS wildcard trap) |

---

## Notes on Scope & Testing

- All files in `fixtures/` are minimal **schema test fixtures** used solely to verify platform export parsing and QA rules in CI — they are not client lists or performance benchmarks.
- Real exports are gitignored (`data/*.csv`, `build/`) and never leave the local machine when run through the CLI or browser app.
- Live Klaviyo API writes require both `KLAVIYO_API_KEY` in the environment and the explicit `--live` flag; the sync script never grants marketing consent.

## License

MIT. See [LICENSE](LICENSE).
