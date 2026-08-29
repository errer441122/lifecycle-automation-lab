# Running the first cycle

Everything is configured and nothing has sent. One fact explains that, and it
is not a missing setting.

| Why nothing has happened | Fixed by |
| --- | --- |
| All three flows are in Draft, and a flow is not retroactive | Step 1 |
| The list has no subscribers, because consent cannot be given on someone's behalf | Step 2 |

Do these in order. Activating a flow before checking its content sends to a
real inbox, and that is not recoverable.

---

## 0. Done already

| | |
| --- | --- |
| Sending domain | `send.negozio-online.org` **Active**. Verified and activated are two separate steps; a domain left merely Verified sends on Klaviyo's shared domain and nothing in the report says so. |
| Email content | All seven flow emails carry the copy in this repo. `python src/build_templates.py --verify` reads them back from Klaviyo and exits non-zero on any drift. |
| Sender | *Torrefazione Nord* on all seven. Three of them still read *Azienda* — setting the account sender does not propagate to messages that already exist. |
| Win-back offer | `TORNA15` in Shopify, 15% off order, one use per customer. |

Two things worth knowing before touching the content again:

**The preheader lives in the HTML, not in Klaviyo's Preview text field.** Each
template opens with a hidden `div` carrying the preheader, which is the
portable way every client understands. Filling Klaviyo's field as well would
render it twice, so that field is deliberately left empty.

**Re-pasting is manual.** See the API constraint in the README. After any copy
change: `python src/build_templates.py --out build/`, paste the changed file
into the flow message's code editor, then `--verify` to prove it took.

## 1. Activate the welcome flow — before subscribing

Flow 1 → **Update status** → Live.

**The order matters and it is the opposite of what feels natural.** A Klaviyo
flow is not retroactive: it only takes in profiles that trigger it *after* it
went live. Subscribe first and the confirmation lands, the profile joins the
list, and nothing else happens — no welcome email, no error, nothing to look
at. It reads exactly like a broken flow.

Activating now is safe because the content is in and checked
(`python src/build_templates.py --verify`). Activating an empty flow is what
sends *"It's time to design"* to a real inbox.

## 2. Become the first subscriber

The storefront is the shop itself, not the admin:
<https://negozio-1-om2cqkph.myshopify.com>. It asks for a password before
showing anything — Shopify forces that on development stores and the toggle
cannot be turned off. The password is in Shopify → Negozio online →
Preferenze.

The form is *Newsletter sign-up (double opt-in)*, a flyout, already **Live**
with 0 submissions. Wait a few seconds on the page, enter an address you can
actually open, tick the consent box, submit.

Then **click the confirmation link in the email**. This is the step the whole
project is about: until that click the profile is `unconfirmed`, it is not on
the list, and it enters no flow. Double opt-in is not a delay before the real
subscription — it *is* the subscription.

The list should now read 1. Check the profile: consent recorded, source
recorded. Email 1.1 arrives within minutes; 1.2 three days later.

Watch 1.1 in a real client — not in Klaviyo's preview, which renders in a
browser and tells you nothing about Outlook.

## 3. Trigger the abandoned cart

Activate Flow 2, then on the storefront: add a product, start checkout with the
same address, and abandon it. `Checkout Started` fires, and email 2.1 arrives
four hours later.

Then test the part that matters: **abandon a second cart, and complete that one
before the four hours are up.** No email should arrive. That is the exit
condition working, and it is the single most useful thing to be able to say you
verified rather than assumed.

## 4. The win-back cannot be demonstrated yet

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

## 5. Fill in the results

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
