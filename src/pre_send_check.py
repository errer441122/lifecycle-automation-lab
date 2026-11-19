"""Multi-ESP Pre-Flight Email QA Checker (Klaviyo Liquid & HubSpot HubL).

Catches production mistakes that ESP editors silently allow to ship:
- Dynamic personalization tags with missing or empty fallbacks (Klaviyo & HubSpot)
- Commercial links missing UTMs or breaking GA4 UTM naming conventions
- Dead, relative, empty, or non-HTTPS links
- Missing mandatory unsubscribe link (Klaviyo {% unsubscribe %} or HubSpot {{ unsubscribe_link }})
- Mobile subject truncation (>50 chars), empty subject, or redundant preview text
- Gmail HTML clipping threshold (>102 KB) and images missing alt text
- Promotional / discount code detection (feeds directly into margin_guard.py so VIPs
  are protected from unnecessary discounts)

Usage:
    python src/pre_send_check.py
    python src/pre_send_check.py email.html --esp auto --subject "..." --preview "..."
    python src/pre_send_check.py email.html --ga4-ref ga4_traffic.csv --json

Pure Python standard library.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from build_templates import EMAILS, render_html, render_text
from platform_io import read_ga4_utm_reference

MAX_SUBJECT = 50
GMAIL_CLIP_BYTES = 102_400  # Gmail clips messages above 102 KB

TAG_RE = re.compile(r"{{\s*(.*?)\s*}}")
GUARD_RE = re.compile(r"{%\s*if\s+([\w.]+)\s*%}(.*?){%\s*endif\s*%}", re.S)
HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']*)["\']', re.I)
IMG_RE = re.compile(r"<img\b([^>]*)>", re.I)
ALT_RE = re.compile(r'\balt\s*=\s*["\']([^"\']*)["\']', re.I)
CLEAN_UTM_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Klaviyo / HubSpot system tags that do not require user-facing fallbacks.
SYSTEM_TAGS = {
    "unsubscribe_link",
    "unsubscribe_link_all",
    "site_settings.company_name",
    "site_settings.company_street_address_1",
    "site_settings.company_city",
    "organization.name",
    "organization.full_address",
    "current_year",
    "today",
}

SERVICE_URL_HINTS = ("unsubscribe", "manage_preferences", "preferences", "privacy", "optout", "opt-out")

DISCOUNT_PATTERNS = [
    re.compile(r"(?:^|\W)(-\s*\d{1,2}\s*%|\d{1,2}\s*%\s*(?:off|di sconto|sconto|discount))", re.I),
    re.compile(r"\b(?:promo\s*code|coupon|discount\s*code|codice\s*sconto|codice\s*promo|codice)\b", re.I),
    re.compile(r"\b(?:save|risparmia)\s*(?:€|\$|£)?\s*\d+", re.I),
]
COUPON_TOKEN_RE = re.compile(
    r"(?:code|codice|coupon)\s*(?::|is|è)?\s*(?:<[^>]+>\s*)*([A-Z0-9]{4,16})\b", re.I
)
PCT_RE = re.compile(r"(?:-\s*(\d{1,2})\s*%|(\d{1,2})\s*%\s*(?:off|di sconto|sconto|discount))", re.I)


def detect_esp(html: str) -> str:
    """Infer whether an email template targets HubSpot (HubL) or Klaviyo (Liquid)."""
    if (
        "{{ contact." in html
        or "{{unsubscribe_link" in html.replace(" ", "")
        or "site_settings." in html
        or "|default(" in html.replace(" ", "")
    ):
        return "hubspot"
    return "klaviyo"


def detect_discount_offer(html: str, subject: str | None = None, preheader: str | None = None) -> dict:
    """Detect whether the email promotes a discount/coupon so Margin Guard can protect VIPs."""
    plain = re.sub(r"<[^>]+>", " ", html)
    corpus = " ".join(filter(None, [subject or "", preheader or "", plain]))
    signals: list[str] = []
    for pat in DISCOUNT_PATTERNS:
        for m in pat.finditer(corpus):
            tok = m.group(0).strip()
            if tok and tok not in signals:
                signals.append(tok)
    codes = sorted({m.group(1).upper() for m in COUPON_TOKEN_RE.finditer(html) if any(ch.isdigit() for ch in m.group(1))})
    pct_match = PCT_RE.search(corpus)
    pct = float(pct_match.group(1) or pct_match.group(2)) if pct_match else None
    return {
        "has_discount": bool(signals or codes or pct is not None),
        "detected_discount_pct": pct,
        "detected_codes": codes,
        "signals": signals[:6],
    }


def _unguarded_tags(source: str) -> list[str]:
    """Return merge tags not protected by an enclosing {% if var %} block."""
    def drop(match: re.Match) -> str:
        return re.sub(r"{{\s*" + re.escape(match.group(1)) + r"\s*}}", "", match.group(2))

    return TAG_RE.findall(GUARD_RE.sub(drop, source))


def _fallback_issue(tag: str) -> dict | None:
    name, *filters = (part.strip() for part in tag.split("|"))
    if name in SYSTEM_TAGS or name.startswith("unsubscribe_link"):
        return None
    for flt in filters:
        # Klaviyo Liquid: |default:'friend'  |  HubSpot HubL: |default('friend')
        if flt.startswith("default:"):
            val = flt[len("default:"):].strip().strip("'\"")
            if val:
                return None
            return {
                "severity": "BLOCKER",
                "category": "personalization",
                "message": f"{{{{ {name} }}}} has an empty fallback — profiles without this field render a broken gap",
            }
        if flt.startswith("default(") and flt.endswith(")"):
            inner = flt[len("default("):-1].split(",", 1)[0].strip().strip("'\"")
            if inner:
                return None
            return {
                "severity": "BLOCKER",
                "category": "personalization",
                "message": f"{{{{ {name} }}}} has an empty HubL default() — profiles without this field render a broken gap",
            }
    return {
        "severity": "BLOCKER",
        "category": "personalization",
        "message": f"{{{{ {name} }}}} has no fallback default value",
    }


def _is_service_link(url: str) -> bool:
    low = url.lower()
    if low.startswith(("mailto:", "tel:")):
        return True
    return any(hint in low for hint in SERVICE_URL_HINTS)


def _link_issues(
    html: str,
    *,
    require_utm: bool = True,
    allowed_sources: set[str] | None = None,
    allowed_mediums: set[str] | None = None,
    ga4_ref: dict[str, set[str]] | None = None,
) -> list[dict]:
    issues: list[dict] = []
    sources = {s.lower() for s in allowed_sources} if allowed_sources else None
    mediums = {m.lower() for m in (allowed_mediums or {"email"})}

    for href in HREF_RE.findall(html):
        url = href.strip()
        if not url or url == "#":
            issues.append({
                "severity": "BLOCKER",
                "category": "links",
                "message": f'Dead link found: href="{href}"',
            })
            continue
        if _is_service_link(url):
            continue
        if url.startswith(("{{", "{%")):
            # Dynamic CTA URL (e.g., checkout recovery): merge tag fallback checked separately.
            continue
        if not url.startswith("https://"):
            issues.append({
                "severity": "BLOCKER",
                "category": "links",
                "message": f"Non-HTTPS or relative link: {url}",
            })
            continue

        qs = parse_qs(urlsplit(url).query)
        utm = {k: v[0] for k, v in qs.items() if k.startswith("utm_")}
        required_keys = ("utm_source", "utm_medium", "utm_campaign")
        if not utm:
            if require_utm:
                issues.append({
                    "severity": "BLOCKER",
                    "category": "utm",
                    "message": f"Commercial link missing UTM parameters (utm_source/utm_medium/utm_campaign): {url}",
                })
            continue

        missing = [k for k in required_keys if not utm.get(k)]
        if missing:
            issues.append({
                "severity": "BLOCKER",
                "category": "utm",
                "message": f"Link missing required UTM key(s) {', '.join(missing)}: {url}",
            })
        for key, val in utm.items():
            if not CLEAN_UTM_TOKEN.match(val):
                issues.append({
                    "severity": "WARNING",
                    "category": "utm",
                    "message": f"{key}={val!r} breaks lowercase snake/kebab GA4 naming rules in {url}",
                })
        if utm.get("utm_medium") and utm["utm_medium"].lower() not in mediums:
            issues.append({
                "severity": "BLOCKER",
                "category": "utm",
                "message": f"utm_medium={utm['utm_medium']!r} must be one of {sorted(mediums)} in {url}",
            })
        if sources and utm.get("utm_source") and utm["utm_source"].lower() not in sources:
            issues.append({
                "severity": "BLOCKER",
                "category": "utm",
                "message": f"utm_source={utm['utm_source']!r} is not in allowed sources {sorted(sources)}: {url}",
            })
        if ga4_ref and ga4_ref.get("sources") and utm.get("utm_source"):
            if utm["utm_source"].lower() not in ga4_ref["sources"]:
                issues.append({
                    "severity": "WARNING",
                    "category": "utm",
                    "message": (
                        f"utm_source={utm['utm_source']!r} does not appear in the GA4 reference export "
                        f"({', '.join(sorted(ga4_ref['sources'])[:6])}) — risk of channel fragmentation"
                    ),
                })

    return issues


def _has_unsubscribe(html: str, esp: str) -> bool:
    compact = html.replace(" ", "").lower()
    if esp == "hubspot":
        return "{{unsubscribe_link" in compact or "{{unsubscribe_link_all" in compact
    return "{%unsubscribe%}" in compact or "{%manage_preferences%}" in compact


def _plain(text: str) -> str:
    return re.sub(r"\W+", "", text).lower()


def audit_template(
    html: str,
    *,
    text: str | None = None,
    subject: str | None = None,
    preheader: str | None = None,
    esp: str = "auto",
    require_utm: bool = True,
    allowed_sources: set[str] | None = None,
    allowed_mediums: set[str] | None = None,
    ga4_ref: dict[str, set[str]] | None = None,
) -> dict:
    """Run full pre-flight template QA and return a structured audit payload."""
    detected_esp = detect_esp(html) if esp == "auto" else esp.lower()
    issues: list[dict] = []

    for tag in _unguarded_tags(html):
        issue = _fallback_issue(tag)
        if issue:
            issues.append(issue)

    issues.extend(
        _link_issues(
            html,
            require_utm=require_utm,
            allowed_sources=allowed_sources,
            allowed_mediums=allowed_mediums,
            ga4_ref=ga4_ref,
        )
    )

    if not _has_unsubscribe(html, detected_esp) or (
        text is not None and not _has_unsubscribe(text, detected_esp)
    ):
        expected = "{{ unsubscribe_link }}" if detected_esp == "hubspot" else "{% unsubscribe %}"
        issues.append({
            "severity": "BLOCKER",
            "category": "compliance",
            "message": f"Missing mandatory unsubscribe token ({expected}) required for GDPR & Google/Yahoo bulk-sender compliance",
        })

    if subject is not None:
        subj = subject.strip()
        if not subj:
            issues.append({"severity": "BLOCKER", "category": "mobile_ux", "message": "Empty subject line"})
        elif len(subj) > MAX_SUBJECT:
            issues.append({
                "severity": "WARNING",
                "category": "mobile_ux",
                "message": f"Subject is {len(subj)} chars — mobile inboxes truncate around {MAX_SUBJECT} chars",
            })

    if preheader is not None:
        pre = preheader.strip()
        if not pre:
            issues.append({
                "severity": "WARNING",
                "category": "mobile_ux",
                "message": "Empty preview text — inbox clients will pull raw body/header markup",
            })
        elif subject and _plain(pre) == _plain(subject):
            issues.append({
                "severity": "WARNING",
                "category": "mobile_ux",
                "message": "Preview text duplicates the subject line instead of adding context",
            })

    size_bytes = len(html.encode("utf-8"))
    if size_bytes > GMAIL_CLIP_BYTES:
        issues.append({
            "severity": "WARNING",
            "category": "deliverability",
            "message": f"HTML size is {size_bytes / 1024:.1f} KB (>100 KB): Gmail will clip the message and hide the unsubscribe footer",
        })

    for img_attrs in IMG_RE.findall(html):
        alt_match = ALT_RE.search(img_attrs)
        if not alt_match or not alt_match.group(1).strip():
            issues.append({
                "severity": "WARNING",
                "category": "deliverability",
                "message": "Image tag missing non-empty alt text (hurts accessibility and image-blocked opens)",
            })

    discount = detect_discount_offer(html, subject, preheader)
    blockers = [i for i in issues if i["severity"] == "BLOCKER"]
    warnings = [i for i in issues if i["severity"] == "WARNING"]

    return {
        "status": "FAIL" if blockers else ("WARN" if warnings else "PASS"),
        "esp": detected_esp,
        "html_bytes": size_bytes,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "issues": issues,
        "discount_offer": discount,
    }


def check(
    html: str,
    text: str | None = None,
    subject: str | None = None,
    preheader: str | None = None,
    *,
    esp: str = "auto",
    require_utm: bool = True,
) -> list[str]:
    """Backwards-compatible flat list of issue messages."""
    report = audit_template(
        html,
        text=text,
        subject=subject,
        preheader=preheader,
        esp=esp,
        require_utm=require_utm,
    )
    return [i["message"] for i in report["issues"]]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Multi-ESP Pre-Flight Email QA Checker (Klaviyo & HubSpot).")
    p.add_argument("files", nargs="*", type=Path, help="HTML templates to audit (default: reference templates)")
    p.add_argument("--esp", choices=("auto", "klaviyo", "hubspot"), default="auto")
    p.add_argument("--subject", help="Subject line to audit")
    p.add_argument("--preview", help="Preview text / preheader to audit")
    p.add_argument("--esp-auto-utm", action="store_true", help="Allow commercial links without hand-typed UTMs")
    p.add_argument("--allowed-sources", default="", help="Comma-separated allowed utm_source values")
    p.add_argument("--ga4-ref", type=Path, help="Optional GA4 Traffic Acquisition CSV to cross-check utm_source")
    p.add_argument("--strict", action="store_true", help="Exit 1 on warnings as well as blockers")
    p.add_argument("--json", action="store_true", dest="as_json", help="Print structured JSON output")
    args = p.parse_args(argv)

    ga4_ref = read_ga4_utm_reference(args.ga4_ref) if args.ga4_ref else None
    allowed_sources = {s.strip() for s in args.allowed_sources.split(",") if s.strip()} or None

    audits: list[dict] = []
    if args.files:
        for path in args.files:
            html = path.read_text(encoding="utf-8", errors="replace")
            res = audit_template(
                html,
                subject=args.subject,
                preheader=args.preview,
                esp=args.esp,
                require_utm=not args.esp_auto_utm,
                allowed_sources=allowed_sources,
                ga4_ref=ga4_ref,
            )
            res["template"] = path.name
            res["subject"] = args.subject or ""
            audits.append(res)
    else:
        for e in EMAILS:
            res = audit_template(
                render_html(e),
                text=render_text(e),
                subject=e["subject"],
                preheader=e["preheader"],
                esp="klaviyo",
                require_utm=not args.esp_auto_utm,
                allowed_sources=allowed_sources or {"klaviyo"},
                ga4_ref=ga4_ref,
            )
            res["template"] = e["key"]
            res["subject"] = e["subject"]
            audits.append(res)

    failed = sum(1 for a in audits if a["blocker_count"] > 0 or (args.strict and a["warning_count"] > 0))
    if args.as_json:
        print(json.dumps({"templates": audits, "failed": failed}, indent=2))
    else:
        for a in audits:
            badge = a["status"]
            disc = " [PROMO DETECTED]" if a["discount_offer"]["has_discount"] else ""
            print(f"  {a['template']:<24} {badge:<4} ({a['esp']}) {a['subject']}{disc}")
            for issue in a["issues"]:
                print(f"      [{issue['severity']}] ({issue['category']}) {issue['message']}")
        print(f"\n{len(audits) - failed} of {len(audits)} passed pre-flight QA.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
