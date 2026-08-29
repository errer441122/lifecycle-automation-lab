# Consent and suppression

How this project collects, records and honours marketing consent, and why the
sync script is deliberately unable to grant it.

> Not legal advice. This documents how one small project is configured; a real
> deployment needs its own review.

## Lawful basis

Marketing email here runs on **consent** (GDPR Art. 6(1)(a)), collected via
double opt-in. Consent must be freely given, specific, informed and
unambiguous (Art. 4(11)), which rules out three things this project does not
do:

| Not done | Why |
| --- | --- |
| Pre-ticked boxes | Not unambiguous — settled by *Planet49* (C-673/17) |
| Consent bundled into the terms of sale | Not freely given, not specific |
| Marketing to addresses collected for order fulfilment | Not the purpose they were given for |

**The Italian soft opt-in.** Art. 130(4) of the Codice Privacy allows emailing
an existing customer about *similar* products without prior consent, provided
they were told at collection and every message offers an easy opt-out. This
project does **not** rely on it: everyone goes through double opt-in, which is
simpler to prove and does not require arguing about what counts as "similar".
It is noted here because it is the mechanism an Italian e-commerce actually
operates under, and knowing the difference matters.

## Double opt-in

```
form submit  ─►  unconfirmed profile  ─►  confirmation email (one link, no marketing)
                                                    │
                                    click ──────────┴──────────  no click
                                      │                              │
                                 opted_in                    stays unconfirmed
                              enters welcome flow            receives nothing, ever
```

GDPR does not explicitly mandate double opt-in. It mandates being able to
*demonstrate* consent (Art. 7(1)), and a logged confirmation click is the
cheapest evidence there is. It also filters typo'd and mistyped addresses
before they damage the sending reputation, so the compliance win and the
deliverability win are the same action.

## What is recorded

Per the demonstrability requirement, each consent record carries:

| Field | Example | Why |
| --- | --- | --- |
| `email` | `person@example.com` | Subject |
| `consent_status` | `opted_in` | Current state |
| `consent_source` | `signup_form_double_optin` | Which mechanism, provable |
| `consent_timestamp` | `2026-05-18T09:12:00Z` | When, in UTC |

This is the schema `src/sync_klaviyo.py` reads. Anything whose status is not
exactly `opted_in` is suppressed, including a profile with **no record at
all** — absence is treated as `unknown` and suppressed, never as permission.

## Withdrawal

Withdrawal must be as easy as giving consent (Art. 7(3)):

- Unsubscribe link in the footer of every marketing email, one click, no login
- Takes effect immediately, no confirmation step (a confirmation step to *stop*
  receiving mail is a dark pattern and is not symmetric with a one-click opt-in)
- The address is suppressed, not deleted, so a later import cannot silently
  resurrect it — a deletion request under Art. 17 is handled separately

## Why the sync script cannot grant consent

A Klaviyo bulk profile import writes profile data. It does **not** subscribe
anyone to email marketing — that requires a separate subscription call, which
this project never makes from a script.

This separation is intentional and is the point of the whole design: consent
enters the system through exactly one door, the double opt-in form. The sync
script's only relationship to consent is that it **refuses to act** on anyone
who has not passed through that door. It cannot open it.

Concretely, in `build_profiles()`:

```python
status = consent.get(email, "unknown")
if status != ELIGIBLE_CONSENT:
    suppressed[status] += 1
    continue
```

The gate runs before the lifecycle stage is even computed, and there is no
override — the test suite asserts that the highest-value customer in the file
is still excluded when they have opted out.

## Boundary the code enforces

- No purchased, scraped, rented or scanned-at-an-event lists
- No email address is ever invented or guessed
- The example data uses `example.com`, reserved by RFC 2606 and unable to
  receive mail, so a misconfigured run cannot reach a real person
- `--live` is opt-in; the default run opens no socket
