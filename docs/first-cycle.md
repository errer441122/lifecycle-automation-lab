# Running the first cycle

Everything is configured and nothing has run. Three facts explain that, and two
of them are closed by working through this page in order.

| Why nothing has happened | Fixed by |
| --- | --- |
| All three flows are in Draft, so they never send | Steps 1–3 |
| Flow emails have no template assigned | Step 1 |
| The list has no subscribers, because the storefront is password-locked | Step 2 |

Do these in order. Activating a flow before its emails have content sends
*"It's time to design"* to a real inbox, and that is not recoverable.

---

## 0. Check the sending domain first

Klaviyo's dashboard showed `send.negozio-online.org` as *Incomplete* even after
DNS was correct, because its verification job runs on its own schedule. If the
domain is still not verified at send time, Klaviyo silently falls back to its
shared sending domain and the whole DKIM/DMARC setup contributes nothing to
that send.

Settings → Domains. If it does not read verified, the DNS is still right —
confirm it independently rather than waiting on the dashboard:

```bash
nslookup -type=NS send.negozio-online.org
nslookup -type=CNAME s1._domainkey.send.negozio-online.org
nslookup -type=TXT _dmarc.negozio-online.org
```

## 1. Generate and assign the templates

```bash
python src/build_templates.py --out build/
```

Open the files in `build/` and read them. This is the last point where a typo
costs nothing.

```bash
export KLAVIYO_API_KEY=pk_xxx && python src/build_templates.py --live
```

Then in Klaviyo, for each of the seven emails: Flows → the flow → the email →
**Change template** → pick the matching one. The names line up (`1.1`, `1.2`,
`2.1` …).

## 2. Become the first subscriber

The storefront needs the store password — Shopify forces password protection on
development stores and the toggle cannot be turned off. Get it from Online
store → Preferences.

Open the storefront, wait for the flyout, and submit with an address you can
actually read. Then **click the confirmation link in the email**. Without that
click the profile stays unconfirmed and enters nothing, which is the whole point
of the design.

The list should now read 1. Check the profile: consent recorded, source
recorded.

## 3. Activate the welcome flow

Flow 1 → **Update status** → Live.

Email 1.1 should arrive within minutes. Email 1.2 arrives three days later.

Do not activate anything before this point. Watch what 1.1 actually looks like
in a real client — not in Klaviyo's preview, which renders in a browser and
tells you nothing about Outlook.

## 4. Trigger the abandoned cart

Activate Flow 2, then on the storefront: add a product, start checkout with the
same address, and abandon it. `Checkout Started` fires, and email 2.1 arrives
four hours later.

Then test the part that matters: **abandon a second cart, and complete that one
before the four hours are up.** No email should arrive. That is the exit
condition working, and it is the single most useful thing to be able to say you
verified rather than assumed.

## 5. The win-back cannot be demonstrated yet

Flow 3 triggers on entry to the `At risk` segment, which requires 91 or more
days since the last order. The seeded orders are days old. Structurally, this
flow cannot produce data until December — there is no way around that which
does not involve inventing data.

There is one honest way to exercise the mechanism now. `sync_klaviyo.py` takes
`--as-of`, which pins the reference date the recency calculation runs against:

```bash
python src/sync_klaviyo.py --orders data/orders.csv --consent data/consent.csv --as-of 2026-12-15
```

Relative to that date the real orders genuinely are more than 90 days old, so
the model assigns `At risk` by its own unmodified rules. That is a stated
reference date, not a fabricated order — the same device any cohort analysis
uses. If you run it `--live` and it moves a consenting profile into the segment,
say plainly in the write-up that the date was pinned, or the number stops
meaning anything.

## 6. Fill in the results

[`../reports/results.md`](../reports/results.md) has the structure. Record
counts, not rates: two opens out of six is two opens, and calling it 33% invites
the reader to compare it with a benchmark it cannot support.

The **What broke** section matters more than the numbers. Something will
misfire — a merge tag rendering raw, a link without its UTM parameters, an
email arriving at 3am because a delay landed badly. Write down what happened and
what changed as a result. A portfolio project where nothing went wrong reads as
one that was never actually run.

## What this will and will not show

| | |
| --- | --- |
| Real | The mechanism end to end: consent captured, flow triggered, email delivered, exit condition respected |
| Not real | The volume. One subscriber and a handful of sends support no claim about performance |
| Not yet | Anything from the win-back flow, unless the reference date is pinned and that is disclosed |

Send only to yourself, or to people who have gone through the double opt-in
themselves. The suppression logic in [`consent.md`](consent.md) is only worth
documenting if it is also obeyed.
