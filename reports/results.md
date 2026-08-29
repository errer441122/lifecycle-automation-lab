# Results

> **First cycle ran on 2026-08-29.** The welcome path is closed end to end:
> consent given, confirmed, flow triggered, email delivered. The cart and
> win-back paths have not run — see *Flow activity* for why, stated rather than
> estimated.

## Setup

| | |
| --- | --- |
| Store | Shopify development store, 8 products (specialty coffee), 3 seeded orders |
| Store currency | USD — the store sits on a United States market. Prices read as `$` in every screenshot; switch the market to Italy/EUR in Settings → Markets and re-create the orders if that matters for the write-up |
| ESP | Klaviyo, free plan, connected to the store since 2026-08-27 |
| Sending domain | `send.negozio-online.org` — **Active**, NS delegation live, DKIM published, DMARC `p=none` |
| List | *Newsletter (double opt-in)* (`WZDGDT`), double opt-in on, unsubscribe global |
| Segment | *At risk (lifecycle_stage)* (`TFJaA4`), 0 members |
| List size | 1 consenting profile, confirmed through double opt-in |
| Period observed | from 2026-08-29 15:46 UTC — one welcome cycle |

### Seeded orders

All three were created as draft orders marked paid, so they all carry today's
date. Shopify cannot backdate an order from the admin, so only `New` and
`Repeat` can be produced this way — `At risk`, `Dormant` and `Churned` need
either real elapsed time or the `--as-of` flag. Addresses are `example.com`
(RFC 2606), so the order-confirmation emails Shopify sent could not reach a
real inbox.

| Order | Customer | Items | Total | Resulting stage |
| --- | --- | --- | --- | --- |
| #1001 | Marco Bianchi | Etiopia Yirgacheffe 250g, Set degustazione 4x100g | 36.50 | `New` (1 order) |
| #1002 | Giulia Rossi | Capsule compostabili x50, Miscela Espresso Bar 1kg | 44.50 | `Repeat` (2 orders) |
| #1003 | Giulia Rossi | Brasile Cerrado 1kg | 32.00 | ↑ same customer |

Neither customer has marketing consent: the admin checkbox was left unticked
on purpose, because consent belongs to the double opt-in form, not to a box
ticked by whoever creates the record. Running the sync against this data
therefore reports **0 eligible, 2 suppressed as `unknown`** — the gate doing
its job, and the cheapest possible proof that it works.

## Read this before the numbers

The list is tiny and self-recruited. At this size:

- **Rates are not benchmarks.** 2 opens out of 6 is not "a 33 % open rate", it
  is two opens. Counts are reported below, rates are not.
- **There is no control group.** Nothing here supports a causal claim about
  what the flows caused.
- **The audience is not representative.** They are people who agreed to receive
  test emails, which is the least representative audience possible.

What this project demonstrates is that the mechanism works end to end: a real
event fires, a real segment updates, a real email arrives, and the consent
gate holds. It does not demonstrate performance, and any reading of it as
performance is a misreading.

## Sync

From `reports/sync_report.json`:

| | Count |
| --- | --- |
| Customers in orders export | 2 |
| Eligible after consent gate | **0** |
| Suppressed — `opted_out` | 0 |
| Suppressed — `unknown` | 2 |
| `New` / `Repeat` / `At risk` / `Dormant` / `Churned` | 0 / 0 / 0 / 0 / 0 |

Zero eligible is the expected result, not a failure. Both customers were
created in the Shopify admin with the marketing checkbox left unticked, so the
gate suppresses them and the script exits without opening a socket. The one
profile that *is* on the list did not come from here — it came from the form,
which is the only path that can grant consent.

## Flow activity

| Flow | Entered | Delivered | Opened | Clicked | Orders | Unsub | Complaints |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Welcome — 1.1 | 1 | 1 | — | — | 0 | 0 | 0 |
| Welcome — 1.2 | pending (Day 3) | | | | | | |
| Abandoned cart — 2.1 | 1 | due 20:45 UTC | | | | | |
| Abandoned cart — 2.2/2.3 | pending (+20h, +2d) | | | | | | |
| Win-back | cannot run before December | | | | | | |

One delivery. That is a mechanism working, not a measurement — see the section
above.

```
15:41:33  Subscribed to List -> Email List                  (Shopify webhook, wrong list)
15:44:4x  subscribe_page_view  x3
15:46:31  Subscribed to List -> Newsletter (double opt-in)   (confirmation clicked)
15:47:18  Received Email -> "Benvenuto in Torrefazione Nord" (flow SQbmHb)
```

**47 seconds** from the confirmation click to delivery, and five minutes
between landing on the consent page and confirming. That gap is the double
opt-in doing its job: the profile existed and had marketing consent from
15:41, and still received nothing until it confirmed for *this* list.

**The abandoned-cart flow was entered by a real cart.**

```
16:45:52  Checkout Started   Colombia Huila 250g, $11.00, Source Name: web
          $extra.checkout_url -> .../checkouts/ac/hWNGDmdA.../recover?key=...
```

`Source Name: web` is the part that matters: the event came from Shopify's
checkout webhook on the storefront, not from anything constructed in the
admin. Delivery of 2.1 is due at 20:45 UTC, four hours later, and is recorded
above as due rather than as delivered.

**The exit condition has still not been observed suppressing a send**, and one
cart cannot show both. The condition is re-evaluated before every send, so any
`Placed Order` in those four hours removes the profile and 2.1 never goes out
— which would demonstrate suppression at the cost of demonstrating the send.
This run demonstrates the send. Reviewing the exit condition's design is fair;
reading it as verified behaviour is not.

The win-back cannot produce data until roughly December: it triggers on entry
to `At risk`, which needs 91+ days since the last order, and the seeded orders
are days old. `--as-of` exercises the model against a stated reference date,
which is a disclosure, not a substitute for elapsed time.

## Authentication

| Check | Result |
| --- | --- |
| SPF | served by Klaviyo inside the delegated `send.` zone — dynamic routing, so it never appears in Cloudflare |
| DKIM | `s1._domainkey.send.negozio-online.org` -> `s1.domainkey.u161779.wl030.sendgrid.net`, resolving |
| DMARC (`p=`) | `v=DMARC1; p=none;`, resolving, no `rua=` yet |
| `List-Unsubscribe` one-click | **open** — needs the raw headers of the delivered email, not the dashboard |

Verified with `nslookup` against `8.8.8.8`, not against the ESP's own status
column. The reason for that rule is the first incident below.

## What broke

### A green checkmark that was someone else's wildcard

The sending-domain setup was run against `mionegozio.com` and failed
verification four times in a row. Klaviyo's dashboard was not helpful about
why: it reported five records as *Action required* and one — the `_dmarc` TXT —
as **Verified**, which made it look like a partially-working configuration that
just needed more propagation time.

It was not. Checking the domain directly instead of trusting the dashboard:

```
$ nslookup -type=TXT mionegozio.com
mionegozio.com          text = "v=spf1 -all"

$ nslookup -type=TXT _dmarc.mionegozio.com
_dmarc.mionegozio.com   text = "v=spf1 -all"      # identical
```

Two different names returning the same value is a **wildcard TXT**. And RDAP
explained who was serving it:

```
registration : 2021-09-13
registrar    : GoDaddy.com, LLC
nameservers  : NS1.AFTERNIC.COM, NS2.AFTERNIC.COM
```

The domain had been registered years earlier by someone else and parked on
Afternic, a resale marketplace, whose parking zone answers every TXT query with
`v=spf1 -all`. Klaviyo asked for `_dmarc`, the wildcard answered, and the check
went green. Nothing had been configured.

**What it cost:** four verification attempts and a false belief that the setup
was half-done and needed patience.

**What changed as a result:** authentication is now verified against
`nslookup` and raw message headers, never against the vendor's own status
column — a dashboard can only tell you that *an* answer came back, not that the
answer was yours. The `_dmarc` value is also a tell in hindsight: a real DMARC
record starts `v=DMARC1`, not `v=spf1`, so the value in the "verified" row was
never a valid DMARC policy in the first place.

**Resolved:** the real domain was `negozio-online.org`, already on Cloudflare
with correct records. Klaviyo had been pointed at the wrong one because it
prefills the domain field from account settings.

### Verified is not Active, and nothing says so

With the DNS correct, `send.negozio-online.org` sat in Klaviyo reading
*"created but has not started verification yet"* for a day. Verification had to
be started by hand. Then, once **Verified**, it still had to be **Activated** —
a second, separate action.

**What it cost:** nothing, because it was caught before the first send. Had it
not been, every email would have gone out on Klaviyo's shared sending domain
while the dashboard showed a verified branded domain, and no send report would
have mentioned it.

**What changed as a result:** "domain configured" is not a state worth
recording. The states that matter are Verified *and* Active, and both are now
in [`../docs/deliverability.md`](../docs/deliverability.md).

### Consent arrived on a list that nothing reads

The first attempt to subscribe produced a subscriber, and the welcome flow
still did not fire. The profile was real, consenting, and on the wrong list:

```
consent            SUBSCRIBED
method             SHOPIFY / Customer Webhook
list               Email List          <- Klaviyo integration default
consent_timestamp  15:30:36.655
webhook event      15:30:36.569
```

86 milliseconds between the webhook and the consent record: no confirmation
link was clicked, because none was sent. The subscription had gone through
Shopify's own newsletter field, Shopify created a customer with
`accepts_marketing`, and the Klaviyo integration wrote that straight into its
default list — bypassing the flyout entirely. The destination list is itself
marked double opt-in, and it made no difference.

**What it cost:** a subscriber who looked correct in every summary view and
triggered nothing.

**What changed as a result:** double opt-in on a list protects the path that
goes through the form. It does not protect the list. Any integration with
write access can put a `SUBSCRIBED` profile on it without a confirmation, so
the list a flow reads has to be one that only the form writes to. Worth saying
plainly in an interview: the setting was on, correctly, and it still did not do
what its name suggests.

### A form that was live, correct, and never rendered

The flyout was Live, published, submitting to the right list, with no URL,
location, device or UTM restrictions and a permissive display rule (exit
intent **or** 5 seconds **or** 30% scroll, `all conditions` off). The Klaviyo
app embed was on in the theme, onsite tracking was enabled, and
`klaviyo.js?company_id=VgsrdN` served the `signup_forms` bundles.

**Submits: 0. Viewed form: 0.** Not "shown and ignored" — never rendered.

The unblock was Klaviyo's hosted consent page, which needs no storefront, no
theme embed and no store password, and honours the same double opt-in. That is
what produced the subscriber above.

**Still open:** why the flyout does not render. The two candidates are the
theme-editor preview, where onsite scripts do not run, and Shopify's password
page, which app embeds are not executed on.

### Copy that promised what the store could not deliver

Two claims survived every read-through because they are well written:

- *"Spedizione in 48 ore in tutta Italia"* — the store publishes no shipping
  rate carrying a delivery estimate. The promise existed only in the email.
- *"Valido 14 giorni"* on the win-back code — a win-back flow runs
  continuously and each profile enters on a different day, so one static code
  cannot carry a per-recipient 14-day window.

The second is the more interesting error: it is not a typo, it is a claim that
is incoherent with the mechanism sending it.

**What changed as a result:** `STORE_FACTS` in
[`../src/build_templates.py`](../src/build_templates.py) records what the
storefront actually backs, and a test fails if any duration in the copy is not
in it. `TORNA15` was created in Shopify so the offer is real, and the copy now
states the terms the discount has.

### An abandoned cart cannot be manufactured from the Shopify admin

The obvious way to trigger the cart flow without touching a storefront is a
draft order in the admin, and it looked supported: earlier `Checkout Started`
events in this account carried `Source Name: shopify_draft_order`.

A draft order was created and left unpaid. **No event, five minutes later.**
Going back to those earlier events explains why — `Checkout Started` at
13:56:18 and `Placed Order` at 13:56:37, nineteen seconds apart. The draft
order emits `Checkout Started` when it is *completed*, and completing it also
emits `Placed Order`. So the admin can produce a purchase, and it can produce
a checkout, but it cannot produce a checkout that was abandoned: the two
events are welded together.

**What changed as a result:** the cart flow was entered from the storefront
instead, which is the only path that produces the event this flow is designed
around. Worth knowing before building a QA routine on draft orders.

### The cart CTA was checked before the send, not after

`{{ event.extra.checkout_url }}` is the button in all three cart emails, and a
Klaviyo event stores that payload under `$extra`, not `extra`. Reading the
live event back confirmed the key exists and holds a real Shopify recovery URL
before the four-hour delay elapsed. A dead CTA in the one cart email this
project actually sends would have been discovered by clicking it — which is
the expensive way.

### Smaller ones, without the write-up

- Setting the account sender does not propagate to flow messages that already
  exist. Three of seven still read **"Azienda"** as the from-name.
- A flow's status and its messages' statuses are separate. A Live flow whose
  messages are Draft sends nothing and looks fine.
- Klaviyo serves a flow message's template on `GET /api/templates/{id}` and
  answers `404` to `PATCH` on the same id; `PATCH /api/flow-messages/{id}` is
  `405`. Content goes in by hand. `--verify` exists because of this.
- A flow is not retroactive. Subscribing before activating produces a
  subscriber and no email, which reads exactly like a broken flow.

## What I would do next

**First, close the consent leak.** The Shopify integration can write
`SUBSCRIBED` profiles into a list without a confirmation. Either point the
integration at a list no flow reads, or stop syncing marketing consent from
Shopify entirely and let the form be the only writer. This is a correctness
fix, not an optimisation, and it comes before any test.

**Then, the 4h first-touch delay.** It is the one decision in
[`../docs/flows.md`](../docs/flows.md) with the weakest justification: 4 hours
was chosen to catch the same browsing session, and 1 hour is just as defensible.
It is also the cheapest to test, since it changes one number and needs no new
content.

The honest part is the arithmetic. Detecting a 2-point difference in recovery
rate at a plausible baseline needs on the order of a few thousand carts per
arm. This store will never produce that. So the correct thing to do here is
**not** to run the test and report a winner — it is to state the delay as a
documented choice with its reasoning, and note the sample size at which it
would become answerable. A portfolio project that reports a significant result
from twelve sends is telling you something about the author, not the delay.

## Cost

| | |
| --- | --- |
| Shopify development store | €0 |
| ESP free plan | €0 |
| Domain | `negozio-online.org`, Cloudflare — ~€10/year |
| **Total** | **~€10/year** |
