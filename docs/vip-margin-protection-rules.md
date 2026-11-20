# VIP Margin Protection & Discount Eligibility Matrix

Sending the same blanket discount to the entire database is one of the highest-cost mistakes in CRM: **best customers would have purchased at full price anyway**, so every coupon they redeem destroys gross margin while training them to wait for sales.

---

## 1. Who Gets a Discount vs. Who Stays Full-Price

| Customer Segment | Definition | Eligible for Automatic Discount? | Recommended Treatment |
| --- | --- | --- | --- |
| **VIP / Champions** | ≥3 lifetime orders OR top 20% historical spend | **NO — Exclude** | Early access to launches, private previews, loyalty perks, editorial content |
| **Full-Price Repeat Buyers** | ≥2 orders, zero historical coupons used | **NO — Exclude** | Product recommendations & replenishment reminders (protect margin) |
| **Recent Buyers (Cooldown)** | Placed an order within the last **14 days** | **NO — Exclude** | Post-purchase care / onboarding — sending a coupon right after purchase creates buyer remorse & support refund tickets |
| **New Buyers (15–90 days)** | 1 order, inside natural repeat window | **NO (nudge first)** | Content & cross-sell reminder first; reserve offers only if still inactive past day 90 |
| **At Risk (91–180 days)** | Last order 91–180 days ago | **YES — Controlled** | Single win-back offer (`TORNA15`, once per customer), then stop |
| **Dormant (181–365 days)** | Last order 181–365 days ago | **YES — Final Offer** | One last reactivation offer; if unengaged, move to sunset |
| **Churned / Unengaged (>365 days)** | No open/click/order in 365 days | **NO — Sunset** | Suppress to protect sender reputation (<0.3% spam complaint threshold) |
| **Active CX Hold** | Stuck parcel, 1–2★ review, or open ticket | **NO — Global Hold** | Pause all marketing & review emails until resolved |

---

## 2. How to Enforce in Klaviyo & HubSpot (Zero Coding)

- **Klaviyo:** Build a reusable segment named **`Exclusion — Protect Full-Price Margin`** (`Placed Order >= 3 over all time` OR `Placed Order at least once in last 14 days` OR `cx_promo_hold equals true`). Select it under **Don't send to** on every promotional campaign and as a Flow Filter on discount branches.
- **HubSpot:** Build an Active Suppression List with the same criteria and attach it to every promotional email send.
