# 1-Page Pre-Send QA, GDPR & Deliverability SOP

Run this checklist before switching any **Klaviyo** or **HubSpot** campaign or automated flow to **Live**.

---

## 1. Domain Authentication & Deliverability (Setup & Monthly Audit)

- [ ] **Dedicated sending subdomain** (`send.yourdomain.com`) separated from corporate transactional mail.
- [ ] **SPF, DKIM, and DMARC** verified directly via public DNS lookup (`nslookup` / raw email headers) — **never trust a green vendor badge alone** (see real Afternic wildcard trap in [`field-notes/klaviyo-shopify-field-notes.md`](field-notes/klaviyo-shopify-field-notes.md)).
- [ ] **DMARC progression followed:** `p=none` (monitor reports) → `p=quarantine` → `p=reject`.
- [ ] **Domain state is both Verified AND Active** (a Verified-but-inactive domain silently falls back to shared ESP IPs).
- [ ] **Google & Yahoo bulk-sender rules:** one-click `List-Unsubscribe` header active, spam complaint rate kept strictly **<0.3%**, unengaged >365d profiles sunsetted.

## 2. GDPR Consent Governance (Art. 7(1))

- [ ] **Double Opt-In enabled** on signup forms, with explicit `consent_source` and `consent_timestamp` stored on every marketable profile.
- [ ] **Audit for single opt-in leaks:** verify Shopify checkout checkboxes or third-party integrations are **not** silently bypassing Double Opt-In into flow-triggered lists (real bug documented in field notes).
- [ ] **Suppress, never delete:** unsubscribed and hard-bounced emails stay suppressed so future imports can never accidentally re-subscribe them.

## 3. Flow & Campaign Pre-Flight QA (Before Every Launch)

- [ ] **Smart Sending decision explicit:** **OFF** on high-intent abandoned-cart / transactional-adjacent touches (leaving it ON silently drops cart recovery if a welcome email went out hours earlier — real finding in field notes); **ON** for promotional newsletters.
- [ ] **Exit conditions re-evaluated before every step** (e.g., `Placed Order = 0 since starting flow` on Abandoned Cart & Win-back).
- [ ] **Re-read every delay card after saving** (ESP UIs can revert hours ↔ days on save).
- [ ] **Run the Pre-Flight QA workflow** (fixed rules + AI policy check) ([`workflows/ai-email-preflight-qa.n8n.json`](../workflows/ai-email-preflight-qa.n8n.json)): zero empty merge-tag fallbacks, valid lowercase GA4 UTMs on all commercial links, mobile subject ≤50 chars, copy verified against `store-facts-and-promo-policy.json`, and **VIP + Recent Buyer + Active CX Hold exclusions** attached to all discount sends.
- [ ] **Live seed-inbox test:** click every CTA, verify UTMs in the landing URL, inspect raw headers for SPF/DKIM/DMARC `PASS`, and verify plain-text fallback.
