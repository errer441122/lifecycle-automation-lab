# The rules, in plain words

Everything the workflow decides is a fixed rule in the node `Rules: Grade the Domain (No AI)`. No AI is involved: each check has one right answer, so plain code gives the same verdict every time.

## The three records

| Record | The question it answers | Where it lives |
| --- | --- | --- |
| **SPF** | Which servers may send email for this domain? | A TXT record on the domain that starts with `v=spf1` |
| **DKIM** | Was the message signed by the domain and left unaltered? | A TXT record at `<selector>._domainkey.<domain>` |
| **DMARC** | What should a mailbox provider do with email that fails SPF and DKIM? | A TXT record at `_dmarc.<domain>` that starts with `v=DMARC1` |

The workflow also reads **MX**, the records that say where email for the domain is delivered. A domain without MX cannot receive replies or bounces.

## The verdict

| Status | Meaning |
| --- | --- |
| **FAIL** | At least one blocker: something is broken now |
| **WARN** | No blocker, at least one warning: it works, but it is exposed or fragile |
| **PASS** | Nothing to fix |
| **ERROR** | Public DNS could not be read. No verdict is given, and the last real verdict is kept |

DMARC also gets a stage: `missing`, `monitoring` (p=none), `quarantine`, `reject`, or `invalid`.

## Every finding

Blockers and warnings appear in the Slack digest. Notes appear only in the full verdict.

| Code | Level | What it says | What it means | Fix |
| --- | --- | --- | --- | --- |
| `spf_missing` | blocker | No SPF record on a domain that has mailboxes | Providers cannot tell which servers may send for it | Publish one TXT record that starts with `v=spf1` and lists your sending services |
| `spf_multiple` | blocker | More than one SPF record | Two records cancel each other out: SPF is treated as broken | Merge them into one |
| `spf_allows_everyone` | blocker | SPF ends with `+all` | Every server on the internet may send as you | End with `~all` or `-all` |
| `spf_too_many_lookups` | blocker | SPF needs more than 10 DNS lookups | Past 10, SPF stops working and email counts as unauthenticated | Remove services you no longer use |
| `spf_near_lookup_limit` | warning | SPF uses 9 or 10 of the 10 lookups | One more email tool can break SPF for every message | Clean up before adding a tool |
| `spf_neutral` | warning | SPF ends with `?all`, or has no `all` | Providers get no guidance on unlisted servers | End with `~all`, later `-all` |
| `spf_not_at_this_name` | note | No SPF record, and no mailboxes, at this name | Normal for a subdomain run by an email tool: SPF is checked on the hidden return-path address | Confirm `spf=pass` in the headers of a real email |
| `spf_count_is_minimum` | note | Part of the SPF record could not be followed | The lookup count is a minimum | Nothing to fix |
| `dmarc_missing` | blocker | No DMARC record | Nothing tells providers what to do with email that fakes the domain | Start with `v=DMARC1; p=none; rua=mailto:<an address you read>` |
| `dmarc_not_a_policy` | blocker | A TXT record answers at `_dmarc` but it is not a DMARC policy | A dashboard can show it as verified while providers find no policy. Usually a wildcard on a parked or misconfigured domain | Check the domain, then publish a real `v=DMARC1` record |
| `dmarc_multiple` | blocker | More than one DMARC record | Providers ignore DMARC completely | Keep one |
| `dmarc_bad_policy` | blocker | The `p=` value is missing or not valid | Providers ignore the record | Set `p=none`, `quarantine` or `reject` |
| `dmarc_monitoring_only` | warning | `p=none` | Fake email is still delivered: the policy only asks for reports | Read the reports, fix what fails, move to `quarantine`, then `reject` |
| `dmarc_no_reports` | warning | `p=none` with no `rua=` address | Monitoring that nobody reads | Add `rua=mailto:<an address you read>` |
| `dmarc_no_reports` | note | An enforced policy with no `rua=` address | You cannot see who sends as you or what gets blocked | Add `rua=` |
| `dmarc_subdomains_open` | warning | `sp=none` next to an enforced policy | Fake email from any subdomain is still delivered | Remove `sp=none` |
| `dmarc_partial` | note | `pct=` below 100 | Part of the failing email is delivered as if there were no policy | Raise `pct` to 100 |
| `dmarc_inherited` | note | A subdomain with no record of its own | The policy comes from the closest parent domain that has one, as DMARC intends | Nothing to do |
| `mx_missing` | warning | No MX record | Replies and bounces to that domain are lost | Use a From address on a domain that receives email |
| `dkim_selector_missing` | blocker | No key at a selector you listed | Messages signed with it fail DKIM | Publish the record from your email tool, or correct the selector |
| `dkim_key_revoked` | blocker | The key at a selector is empty | Messages signed with it fail DKIM | Publish the current key |
| `dkim_not_checked` | note | No selector listed for the domain | A DKIM key cannot be found from outside without its selector | Read `s=` in the `DKIM-Signature` header of a real email |

## When the alert fires

The digest goes out on every run. The alert goes out only when a domain:

- got **worse** than in the previous run (for example PASS to WARN),
- **fails on its first check**, or
- has **different SPF or DMARC text** than last run, even with the same status: someone edited the DNS.

A week where nothing changed produces no alert.

## What the check cannot see

- **Inbox placement.** DNS says who may send. Reputation, content and complaints decide the rest.
- **DKIM without a selector.** Keys are found only by selector name.
- **SPF on the return-path.** SPF is evaluated on the hidden bounce address, which email tools often set to their own domain. The workflow reads the domain you list.
- **Domains you did not list.** A tool sending from a subdomain nobody told you about stays invisible until DMARC reports show it. That is what the `rua=` address is for.
- **Which lookups a given message really triggers.** The count covers the whole record, the worst case a receiver can hit. An include mentioned twice counts twice.
