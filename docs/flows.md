# Flow specification

Three flows. Each one states its trigger, its exit condition, its timing and
the reasoning behind the timing — because "why 4 hours and not 24" is the
question an interviewer actually asks.

Timing choices below are starting points, not received wisdom. Each one names
the test that would replace it with evidence.

## What is actually built (2026-08-29)

All three exist in Klaviyo, all **Draft**. Triggers, filters, delays, the seven
emails, Smart Sending and UTM tracking are configured. Copy is written in
[`email-copy.md`](email-copy.md); the visual templates are not assembled.

| Flow | Trigger as built | Steps built | Gap vs this spec |
| --- | --- | --- | --- |
| 1 Welcome | `Added to list → Newsletter (double opt-in)`, no re-entry | 1.1 (Day 0) → Wait 3 days → 1.2 (Day 3) | none |
| 2 Abandoned cart | `Checkout Started`, re-entry allowed, profile filter `Placed Order zero times since starting this flow` | Wait 4h → 2.1 → Wait 20h → 2.2 → Wait 2 days → 2.3 | the cart-value conditional split is not built |
| 3 Win-back | `Added to segment → At risk (lifecycle_stage)` | 3.1 (Day 0) → Wait 7 days → 3.2 (Day 7) | no `Placed Order` exit filter — flow 2 has one, this does not |

The final abandoned-cart delay is entered as **2 days**, not 48 hours. Same
duration; Klaviyo's unit selector silently reverted to `Days` on save more than
once, so the value that could not be mis-saved was the one used.

### What broke while building this

The 20-hour delay saved as **"Wait 20 days"**. The number persisted and the
unit reverted to the default, and the flow card read plausibly enough that it
would have shipped: a cart email arriving three weeks after the cart. Setting
the unit *before* the number, then re-reading the saved card rather than the
form, is what caught it. Every delay in all three flows was re-read from the
canvas afterwards.

Segment `At risk (lifecycle_stage)` is live with 0 members — correct, because
no customer has yet aged past 90 days without ordering.

**Bootstrap note.** Klaviyo's segment builder only offers profile properties
that already exist on at least one profile, and `lifecycle_stage` is written by
`src/sync_klaviyo.py`, which has never run in live mode. The property was
therefore seeded by hand on one real profile, with the value the model actually
computes for that customer (Giulia Rossi → `Repeat`: 2 orders, recency 0). No
value was invented; the manual write only created the schema so the segment
could be defined. Klaviyo took roughly an hour to index it.

---

## Flow 1 — Welcome (double opt-in)

**Trigger:** added to the list *Newsletter (double opt-in)*.
**Re-entry:** none — a profile is welcomed once, even if re-added.
**Exit condition:** unsubscribe, or a hard bounce.

> **Correction, found while building this.** The first draft of this spec had
> the confirmation request as step 0 of the flow. That is wrong in Klaviyo:
> **double opt-in is a property of the list, not a flow step.** With it enabled,
> Klaviyo sends the confirmation email itself, and a profile is only *added to
> the list* once the link is clicked. So the flow trigger already fires
> post-confirmation, and building a confirmation step inside the flow would
> either duplicate the email or send marketing to unconfirmed people.
>
> The consent gate is therefore enforced one layer lower than this document
> originally claimed — which is better, because it cannot be bypassed by
> editing the flow.

| Step | Wait | Content | Purpose |
| --- | --- | --- | --- |
| — | — | *Confirmation request* | Sent by Klaviyo from the list's double opt-in setting, not by this flow |
| 1 | immediate on confirmation | Welcome + what to expect | Sets frequency expectations, which reduces later unsubscribes |
| 2 | 3 days | Best-sellers / category orientation | First soft commercial contact |

**The gate:** a profile that never clicks the confirmation link is never added
to the list, so this flow never sees it. It is not "pending", it is excluded.
See [`consent.md`](consent.md).

**Why 3 days between step 1 and 2:** long enough that the welcome is not
buried, short enough to land inside the window where the brand is still
recognised. Worth testing at 1 day vs 3 vs 7 once volume allows.

---

## Flow 2 — Abandoned cart

**Trigger:** `Checkout Started` metric.
**Entry condition:** has not placed an order since the trigger.
**Exit condition:** `Placed Order` — checked before *every* send, not only at
entry. This is the single most common misconfiguration in an abandoned-cart
flow: a customer who buys after email 1 keeps receiving emails 2 and 3, which
reads as incompetence and generates unsubscribes.

| Step | Wait | Content | Purpose |
| --- | --- | --- | --- |
| 1 | 4 hours | "Still interested?" + cart contents | Fast enough to catch the same session's intent. |
| 2 | 20 hours | Reassurance: shipping, returns, payment | Handles the objection rather than repeating the ask. |
| 3 | 48 hours | Last reminder, cart expiring | Final touch. No discount — see below. |

**Conditional split at step 2:** cart value above the average order value gets
the reassurance variant; below it gets a lighter single-reminder variant. High
consideration needs objection handling, low consideration needs a nudge.

**Why no discount in step 3:** a predictable abandonment discount teaches
customers to abandon carts deliberately. If margin allows a discount, it
belongs in a test with a holdout, not as a default.

**Why 4h / 20h / 48h:** the first touch targets the same browsing session; the
second lands the next morning regardless of when the cart was abandoned; the
third clears the window before the intent is stale. Test 1h vs 4h for step 1
first — it has the largest expected effect.

---

## Flow 3 — Win-back

**Trigger:** entry into the `At risk` segment.
**Entry condition:** `lifecycle_stage` equals `At risk` — the property written
by [`../src/sync_klaviyo.py`](../src/sync_klaviyo.py).
**Exit condition:** `Placed Order`, or leaving the segment.

| Step | Wait | Content | Purpose |
| --- | --- | --- | --- |
| 1 | immediate on entry | "It has been a while" + category they bought from | Relevance from purchase history, not a generic blast. |
| 2 | 7 days | Single re-engagement offer | One offer, then stop. |

**Why `At risk` and not `Dormant` or `Churned`:** at 91–180 days the
relationship is recoverable and the address is likely still active. `Dormant`
and `Churned` are handled by a lower-frequency reactivation track, and
`Churned` should be sunset rather than mailed indefinitely — continuing to
send to people who never open is the fastest way to damage the sending
reputation built in [`deliverability.md`](deliverability.md).

**Why this flow is the interesting one:** its trigger is not a platform event
like a click or a checkout. It is the output of an analysis model, pushed into
the ESP as a property. That is the analysis → action bridge that most
lifecycle setups never close.

---

## Segment definitions

| Segment | Definition | Used by |
| --- | --- | --- |
| `At risk` | `lifecycle_stage` = `At risk` | Flow 3 |
| `Dormant` | `lifecycle_stage` = `Dormant` | Reactivation track |
| `Suppressed` | consent ≠ `opted_in` | Excluded from every send |

The stage property is refreshed by re-running the sync. **Recency changes
every day, so a stale property silently mis-targets people** — the intended
cadence is a weekly re-sync, which also means the property carries
`lifecycle_computed_at` so a stale segment is visible rather than invisible.

## Measurement

Every link carries the UTM taxonomy from the analysis repo
([`tracking/UTM_TAXONOMY.md`](https://github.com/errer441122/digital-campaign-performance-dashboard/blob/main/tracking/UTM_TAXONOMY.md)),
so flow traffic is separable from campaign traffic in GA4:

| Parameter | Value |
| --- | --- |
| `utm_source` | `klaviyo` |
| `utm_medium` | `email` |
| `utm_campaign` | `lifecycle_<flow>` e.g. `lifecycle_winback` |
| `utm_content` | `step<n>_<variant>` e.g. `step2_reassurance` |

`utm_campaign` deliberately separates lifecycle flows from one-off campaigns:
mixing them makes flow revenue look like campaign revenue and quietly inflates
whatever channel the last campaign ran on.
