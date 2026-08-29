# Lifecycle Automation Lab

Consent-first e-commerce lifecycle automation, running on a live store with
real events. Three flows in Klaviyo (welcome with double opt-in, abandoned
cart, win-back), triggered by lifecycle segments computed with the same rules
as my [CRM analysis repo](https://github.com/errer441122/digital-campaign-performance-dashboard).

This is the companion to that analysis: there I *measure* lifecycle and RFM,
here I *operate* on them. The bridge between the two is
[`src/sync_klaviyo.py`](src/sync_klaviyo.py).

> **Status (2026-08-30).** Two of the three flows have been entered by real
> events. Welcome: consent given on the form, confirmed by clicking the link,
> email delivered 47 seconds later, opened 90 minutes after that. Abandoned
> cart: a real storefront checkout, `Source Name: web` — and the first cart
> email **was skipped by Smart Sending**, because the welcome had gone out five
> hours earlier and that is inside the window. Not a bug; the feature working,
> and costing a conversion. It is the most useful thing in
> [`reports/results.md`](reports/results.md), along with the six other things
> that broke. One subscriber and one cart — a working mechanism, not a
> measurement. The win-back cannot produce data before December and that is
> stated rather than worked around. See [Boundaries](#boundaries) for what is
> real here and what is not.

## What is set up

| | |
| --- | --- |
| Store | Shopify, 8 products, 3 seeded orders, integrated with Klaviyo |
| List | *Newsletter (double opt-in)* — `WZDGDT`, double opt-in on, unsubscribe global |
| Segment | *At risk (lifecycle_stage)* — `TFJaA4`, 0 members until December |
| Sign-up form | Flyout, Italian, consent required to submit |
| Win-back offer | `TORNA15` — 15% off order, one use per customer, active |
| Sender | *Torrefazione Nord* `<caffe@negozio-online.org>` |
| Sending domain | `send.negozio-online.org` — NS delegation, DKIM, DMARC, **Active** |
| Account | `it-IT`, `Europe/Rome` |
| Flow 1 Welcome | **Live** — 1.1 (Day 0) → wait 3 days → 1.2 (Day 3) |
| Flow 2 Abandoned cart | **Live** — exit filter → 4h → 2.1 → 20h → 2.2 → 2 days → 2.3 |
| Flow 3 Win-back | 3.1 (Day 0) → wait 7 days → 3.2 (Day 7) |
| Every email | Content live, UTM tracking on, sender *Torrefazione Nord* |
| Smart Sending | On, left on deliberately — it skipped the first cart email and that is reported rather than switched off |

## Recruiter 5-minute route

1. [`docs/flows.md`](docs/flows.md) — the three flows: trigger, branches,
   timing, exit conditions, and the segment each one reads.
2. The screenshots below — the flows as they actually exist in the ESP.
3. [`docs/consent.md`](docs/consent.md) — double opt-in, lawful basis,
   suppression, and why the sync script cannot grant consent.
4. [`reports/results.md`](reports/results.md) — what happened and what I would
   change next.

## The flows

| # | Flow | Trigger | What it demonstrates |
| --- | --- | --- | --- |
| 1 | Welcome | Added to the double opt-in list, i.e. after confirmation | Consent enforced one layer below the flow, so it cannot be bypassed by editing the flow |
| 2 | Abandoned cart | `Checkout Started` | An exit condition re-evaluated before *every* send, not only at entry — the difference between a working cart flow and one that keeps emailing people who already bought. **Live, entered by a real storefront cart**; the exit condition itself is not yet observed suppressing a send — see [results](reports/results.md) |
| 3 | Win-back | Entry into the `At risk` segment | An analysis model, not a platform event, deciding who gets an email |

Full specification in [`docs/flows.md`](docs/flows.md).

## Screenshots

Every screen below exists now. Capture each one, save it under the given
filename, then replace the row with an image embed.

| Shot | File | Where |
| --- | --- | --- |
| Welcome flow canvas | `assets/flow-welcome.png` | Klaviyo → Flows → *1 - Welcome (double opt-in)* |
| Abandoned cart canvas | `assets/flow-abandoned-cart.png` | Klaviyo → Flows → *2 - Abandoned cart* |
| Win-back canvas | `assets/flow-winback.png` | Klaviyo → Flows → *3 - Win-back (At risk)* |
| Abandoned-cart exit condition | `assets/flow-exit-condition.png` | Flow 2 → Trigger → Profile filters — the single most instructive shot in the set |
| `At risk` segment definition | `assets/segment-at-risk.png` | Klaviyo → Lists & segments → *At risk (lifecycle_stage)* → Edit definition |
| Double opt-in enforced on the list | `assets/klaviyo-double-optin.png` | Klaviyo → Lists → *Newsletter (double opt-in)* → Settings → Consent |
| Shopify integration connected | `assets/klaviyo-shopify-integration.png` | Klaviyo → Integrations → Shopify |
| Catalogue and inventory | `assets/shopify-products.png` | Shopify → Prodotti |
| Seeded orders | `assets/shopify-orders.png` | Shopify → Ordini |
| DNS authentication | `assets/dns-auth.png` | Terminal — `nslookup` output, not the vendor dashboard. See [deliverability](docs/deliverability.md) for why |

The last row is deliberate. After the wildcard incident documented in
[`reports/results.md`](reports/results.md), screenshotting a green tick in a
vendor UI is exactly the wrong evidence; the DNS answers are the evidence.

## The bridge: analysis output to ESP segment

The lifecycle model does not live in the ESP. It is computed from order
history and pushed onto the profile as a property, which a Klaviyo segment
then reads, which in turn triggers the flow:

```
orders export  ─┐
                ├─►  sync_klaviyo.py  ─►  profile property        ─►  Klaviyo segment  ─►  flow
consent export ─┘    (hard consent gate)   lifecycle_stage="At risk"   "At risk"          win-back
```

Same thresholds as the analysis repo, deliberately duplicated rather than
imported, so this repo runs standalone:

| Stage | Rule |
| --- | --- |
| New | last order ≤ 90 days ago, 1 order |
| Repeat | last order ≤ 90 days ago, ≥ 2 orders |
| At risk | last order 91–180 days ago |
| Dormant | last order 181–365 days ago |
| Churned | last order > 365 days ago |

### Run it

No third-party packages — Python standard library only.

```bash
python -m unittest discover -s tests
```

```bash
python src/sync_klaviyo.py --as-of 2026-06-01
```


That is a **dry run**: it prints the suppression report and writes
`reports/sync_report.json` without opening a socket. On the bundled example
data it resolves 7 customers into 5 eligible profiles across all five stages,
suppressing one `opted_out` and one with no consent record at all.

To sync for real, set the key in the environment (never as a CLI flag — a
private key on the command line lands in shell history) and pass `--live`:

```bash
export KLAVIYO_API_KEY=pk_xxx && python src/sync_klaviyo.py --orders data/orders.csv --consent data/consent.csv --list-id ABC123 --live
```

The seven emails are rendered from the same repo and checked against what is
actually live:

```bash
python src/build_templates.py --out build/
```

```bash
export KLAVIYO_API_KEY=pk_xxx && python src/build_templates.py --verify
```

Klaviyo's drag-and-drop editor has no HTML view, so assembling seven emails by
hand is about nine block operations each. Generating them from one render
function instead means the layout is written once, the copy is reviewable in a
diff, and a test can assert the things that only fail after a real send — a
missing `{% unsubscribe %}`, a `{{ first_name }}` with no default, a cart email
whose button does not point at the checkout URL, or a claim the storefront
does not back.

**The content cannot be pushed, and that is the platform's constraint, not a
shortcut.** Klaviyo serves a flow message's template on `GET
/api/templates/{id}` but answers `404` to `PATCH` on the same id, and `PATCH
/api/flow-messages/{id}` is `405`. A template created through the API is
therefore an orphan: nothing can point a flow message at it. The HTML goes in
by hand, once, through the flow's code editor. What *is* automatable is the
check — `--verify` reads each live template back and exits non-zero if it has
drifted from this repo, which is the failure that actually happens: copy
edited here, never re-pasted there. `--verify` needs read scope only; it never
writes. So the loop after any copy change is: edit `EMAILS`, run with `--out`,
paste the changed file into the flow message's code editor, run `--verify`.

## Deliverability

Authenticating the sending domain is part of the build, not an afterthought:
SPF, DKIM and DMARC records, the warm-up schedule and the list-hygiene rules
are documented in [`docs/deliverability.md`](docs/deliverability.md).

## Boundaries

- **The mechanism is real; the volume is not.** This runs on a development
  store with a small list of people who each gave explicit double opt-in
  consent. Open and click rates at this sample size are **not statistically
  meaningful** and are reported as counts, never as rates presented as
  benchmarks.
- **No purchased, scraped, or imported lists.** Every recipient opted in
  through the form documented in `docs/consent.md`.
- **The sync script never grants consent.** A bulk profile import writes
  profile data; it does not subscribe anyone to marketing. Consent comes from
  the double opt-in form only, and the script refuses to touch a profile that
  is not already opted in.
- **No email addresses are invented.** The public dataset behind the analysis
  repo (UCI *Online Retail II*) is anonymous — customer ids, no contacts —
  which is precisely why its customers are not synced here. Only the
  segmentation *rules* cross over.
- The example CSVs in `data/` use `example.com` addresses, which are reserved
  by RFC 2606 and cannot receive mail.

## Licence

MIT — see [LICENSE](LICENSE).
