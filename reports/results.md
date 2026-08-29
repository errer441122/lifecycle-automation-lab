# Results

> **Template — fill in after the first full cycle.** Every `TODO` below is a
> placeholder. Publishing this file with the placeholders still in it is worse
> than not publishing it at all.

## Setup

| | |
| --- | --- |
| Store | Shopify development store, 8 products (specialty coffee), 3 seeded orders |
| Store currency | USD — the store sits on a United States market. Prices read as `$` in every screenshot; switch the market to Italy/EUR in Settings → Markets and re-create the orders if that matters for the write-up |
| ESP | Klaviyo, free plan, connected to the store since 2026-08-27 |
| Sending domain | `send.negozio-online.org` — NS delegation live, DKIM published, DMARC `p=none` |
| List | *Newsletter (double opt-in)* (`WZDGDT`), double opt-in on, unsubscribe global |
| Segment | *At risk (lifecycle_stage)* (`TFJaA4`), 0 members |
| List size | 0 consenting profiles — the form has not been published yet |
| Period observed | not started — every flow is Draft |

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
| Customers in orders export | TODO |
| Eligible after consent gate | TODO |
| Suppressed — `opted_out` | TODO |
| Suppressed — `unknown` | TODO |
| `New` / `Repeat` / `At risk` / `Dormant` / `Churned` | TODO |

## Flow activity

| Flow | Entered | Delivered | Opened | Clicked | Orders | Unsub | Complaints |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Welcome | TODO | | | | | | |
| Abandoned cart | TODO | | | | | | |
| Win-back | TODO | | | | | | |

## Authentication

| Check | Result |
| --- | --- |
| SPF | TODO |
| DKIM | TODO |
| DMARC (`p=`) | TODO |
| `List-Unsubscribe` one-click | TODO |

Raw headers from a seed send, not the ESP dashboard's own verdict.

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

**Still open:** a branded sending domain needs a registered domain. Flows run on
Klaviyo's shared sending domain until then — see
[`../docs/deliverability.md`](../docs/deliverability.md).

## What I would do next

TODO — the specific next change and the test that would settle it, not a list
of features. For example: which of the 4h / 20h / 48h abandoned-cart delays to
test first and why, and how many sends it would take to detect a difference
worth acting on.

## Cost

| | |
| --- | --- |
| Shopify development store | €0 |
| ESP free plan | €0 |
| Domain | TODO — ~€10/year |
| **Total** | **TODO** |
