# Deliverability

Authentication, warm-up and list hygiene. Nothing here affects what the emails
say — it affects whether they arrive at all, which is the part that is
invisible until it goes wrong.

## Why a subdomain

Sending is configured on a **subdomain** (`send.negozio-online.org`), not the
root domain. Sending reputation attaches to the sending domain, so a bad marketing
month cannot take the company's transactional and human email down with it.
Separating them costs one DNS record and is not reversible after the damage.

## The three records

| Record | Answers | Without it |
| --- | --- | --- |
| **SPF** | Is this server allowed to send for this domain? | Receivers cannot verify the sending server |
| **DKIM** | Was this message altered in transit, and does the signature match? | No cryptographic proof of origin |
| **DMARC** | What should a receiver do when SPF or DKIM fails? | Failures are handled at each receiver's discretion |

SPF and DKIM alone tell a receiver how to *check*. DMARC is what tells it what
to *do*, and it is the one people skip.

### Values

Sending domain: **`send.negozio-online.org`**. The registrar is Cloudflare and
the zone is on Cloudflare DNS, so the records below live in the Cloudflare DNS
panel. Routing is **dynamic**, which delegates the whole `send.` subdomain to
Klaviyo's nameservers rather than asking for individual CNAMEs — so the records
are `NS`, not the CNAME pair a static setup would produce.

| Type | Name | Value | Status |
| --- | --- | --- | --- |
| NS | `send` | `ns1.klaviyo.com` | live |
| NS | `send` | `ns2.klaviyo.com` | live |
| NS | `send` | `ns3.klaviyo.com` | live |
| NS | `send` | `ns4.klaviyo.com` | live |
| TXT | `@` | `klaviyo-site-verification=VgsrdN` | live |
| TXT | `_dmarc` | `v=DMARC1; p=none;` | live |

Verified against public DNS rather than against the vendor dashboard:

```
$ nslookup -type=NS send.negozio-online.org
send.negozio-online.org  nameserver = ns1..ns4.klaviyo.com

$ nslookup -type=CNAME s1._domainkey.send.negozio-online.org
s1._domainkey.send.negozio-online.org
    canonical name = s1.domainkey.u161779.wl030.sendgrid.net

$ nslookup -type=TXT s1.domainkey.u161779.wl030.sendgrid.net
"...p=MIIBIjANBgkqhkiG..."          # real published DKIM key

$ nslookup -type=TXT _dmarc.negozio-online.org
"v=DMARC1; p=none;"
```

Once the delegation went live, Klaviyo provisioned the DKIM keypair *inside*
the delegated zone (via SendGrid, one of the providers dynamic routing selects
from). SPF and DKIM therefore never appear in the Cloudflare panel — they are
served by Klaviyo from within `send.negozio-online.org`, which is the whole
point of delegating the subdomain.

`_dmarc` carries no `rua=` yet, so the policy is published but no aggregate
reports are being collected. Adding `rua=mailto:<address>` starts the reports;
that address becomes publicly harvestable, so it is a deliberate choice rather
than a default.

### DMARC, and the order to do it in

DMARC is the one record you write yourself, and the policy is a progression,
not a setting:

```
v=DMARC1; p=none; rua=mailto:dmarc@example.it; fo=1
```

1. **`p=none`** — monitor only. Reports arrive at the `rua` address; nothing is
   rejected. Stay here until the reports show every legitimate sender passing.
2. **`p=quarantine`** — failures go to spam. Move here once the reports are clean.
3. **`p=reject`** — failures are refused outright.

Going straight to `p=reject` before reading the reports is how people
discover, by having them silently blocked, that their invoicing system was
also sending mail as that domain.

## Google and Yahoo bulk sender rules

Since February 2024 both enforce, for bulk senders:

- SPF **and** DKIM **and** DMARC — all three, not one of three
- One-click unsubscribe via the `List-Unsubscribe` header (RFC 8058), honoured
  within two days
- Spam complaint rate kept under **0.3 %**, measured by the receiver, not by you

The complaint threshold is the one that bites: it is low enough that a single
badly-targeted send to a stale segment can breach it. It is also the reason
the `Churned` segment in [`flows.md`](flows.md) gets sunset rather than mailed
indefinitely — people who have forgotten you do not unsubscribe, they report
spam.

## Warm-up

A new sending domain with no history sending to its whole list at once looks
exactly like a compromised domain. The schedule is gradual and prioritises the
most engaged first, because early positive signals set the baseline:

| Days | Volume | Audience |
| --- | --- | --- |
| 1–3 | ~20/day | Most recently engaged only |
| 4–7 | ~50/day | Opened in the last 30 days |
| 8–14 | ~150/day | Opened in the last 90 days |
| 15+ | Full flow volume | All eligible |

At this project's actual list size the warm-up is nominal — the schedule is
documented because the reasoning is the transferable part, not the numbers.

## List hygiene

| Rule | Action |
| --- | --- |
| Hard bounce | Suppress immediately, permanently, after one occurrence |
| Soft bounce | Suppress after 3 consecutive |
| No open in 180 days | Move to a low-frequency track |
| No open in 365 days | Sunset — one final re-permission email, then suppress |
| Spam complaint | Suppress immediately; investigate which flow and step sent it |

Suppression means suppressed, not deleted: a deleted address can be silently
re-imported by the next sync, and the person has to unsubscribe twice. The
sync script in this repo cannot cause that, because it never subscribes
anyone — see [`consent.md`](consent.md).

## What to verify before the first real send

- [ ] SPF, DKIM, DMARC all show as verified in the ESP
- [ ] A test send to a seed address passes all three (check the raw headers,
      not just the ESP's own dashboard)
- [ ] `List-Unsubscribe` header present, and the one-click actually works
- [ ] Unsubscribe link renders and resolves in the footer of every template
- [ ] Reply-to is a monitored address, not `noreply@`
- [ ] Plain-text alternative present and readable
- [ ] Every link carries the UTM parameters from `flows.md`
