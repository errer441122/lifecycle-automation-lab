# Pre-Flight QA: Fixed Rules + AI Store Policy Check

The pre-send gate in [`workflows/ai-email-preflight-qa.n8n.json`](../workflows/ai-email-preflight-qa.n8n.json) splits the work in two:

- **Fixed rules (Code node `Rules: Fixed Checks (No AI)`):** everything with one right answer. Code is exact, free and never changes its mind, so no AI is used for these.
- **AI (node `AI: Policy Check & VIP Margin Audit (JSON)`):** only the judgment calls, where the copy has to be read: does it promise something the store cannot keep, and does a discount go out without the exclusions? This is the real failure mode found during hands-on Klaviyo QA: **well-written copy that promises things the store cannot deliver** (*"48-hour shipping"* when checkout publishes no SLA, *"valid for 14 days"* on a static Shopify code).

The node `Merge Rule & AI Results (Safe Defaults)` puts both lists together: any blocker means FAIL, and an unreadable AI answer is itself a blocker.

---

## 1. What the Fixed Rules Check

| Check | Level | Rule |
| --- | --- | --- |
| Personalization fallbacks | Blocker | A first-name tag outside `{% if first_name %}...{% endif %}` needs a non-empty fallback (`{{ first_name|default:'' }}` fails) |
| Links | Blocker | Every link is a full `https://` URL (unsubscribe links and links built from template tags are skipped) |
| GA4 UTMs | Blocker | Every link carries lowercase `utm_source`, `utm_medium=email` and `utm_campaign` |
| Unsubscribe | Blocker | `{% unsubscribe %}` (Klaviyo) or `{{ unsubscribe_link }}` (HubSpot) is present |
| Subject length | Warning | Over 50 characters gets cut on phones |
| Preview text | Warning | Empty, or the same as the subject |
| Image alt text | Warning | An `<img>` without a non-empty `alt` |

## 2. AI System Prompt (Temperature = `0.0`, Strict JSON)

```text
You are a CRM pre-send QA auditor. Fixed checks (merge-tag fallbacks, links, UTMs,
unsubscribe tag, subject length, preview text, alt text) are already done by code:
do not repeat them. Check only two things against the store policy:
(1) copy claims the store cannot keep (e.g. a shipping time when published_shipping_sla
    is none, an expiry window on a static code), category policy_mismatch;
(2) a discount or coupon offered while excluded_segments lacks the required VIP,
    recent-buyer and CX-hold exclusions, category vip_margin_guard.
Return strictly JSON: has_discount_offer (bool), blockers (array of {category, issue, fix}),
warnings (array of {category, issue, fix}).
```

---

## 3. Concrete Example Caught Before Launch

**Draft input:**
- Subject: *"Torna a trovarci oggi: un regalo speciale per te con spedizione 48h!"* (68 chars), no preview text
- Body: `Ciao {{ first_name|default:'' }}, ... spedizione garantita in 48 ore ... TORNA15 (valido solo 14 giorni)`, CTA link without UTMs
- Excluded segments: none

**Verdict (`status: FAIL`), in the order the merge node lists it:**
1. `[BLOCKER · personalization · rule]` `{{ first_name|default:'' }}` renders `"Ciao ,"` for profiles without a first name → `Ciao{% if first_name %} {{ first_name }}{% endif %},`.
2. `[BLOCKER · utm · rule]` The CTA link has no UTM parameters → `?utm_source=klaviyo&utm_medium=email&utm_campaign=lifecycle_winback`.
3. `[BLOCKER · policy_mismatch · AI]` Promises 48-hour shipping, but `published_shipping_sla` is `null` → remove the delivery-time claim.
4. `[BLOCKER · policy_mismatch · AI]` Promises a 14-day expiry on the static code `TORNA15` (`supports_per_recipient_expiry: false`) → use dynamic per-recipient coupons or drop the expiry.
5. `[BLOCKER · vip_margin_guard · AI]` 15% discount to All Subscribers with no VIP, recent-buyer or CX-hold exclusion → exclude `Exclusion — Protect Full-Price Margin` and `CX hold active`.
6. `[WARNING · mobile_ux · rule]` Subject is 68 characters → trim to 50 or fewer.
7. `[WARNING · preview_text · rule]` Preview text is empty → add one line the subject does not already say.
