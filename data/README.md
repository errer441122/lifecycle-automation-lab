# Data

Two inputs, both CSV, both one row per event or per person. The example files
are committed and let the script run out of the box; the real exports are
gitignored.

| File | Committed | Source |
| --- | --- | --- |
| `orders_example.csv` | yes | Handwritten, `example.com` addresses |
| `consent_example.csv` | yes | Handwritten, `example.com` addresses |
| `orders.csv` | **no** | Store order export |
| `consent.csv` | **no** | ESP / signup form export |

The real files are gitignored because they contain personal data. Committing a
subscriber list to a public repository is a personal data breach, not an
oversight — there is no anonymisation step that makes it acceptable, so the
files simply never enter git.

## `orders.csv`

| Column | Type | Notes |
| --- | --- | --- |
| `email` | string | Lowercased and trimmed on read |
| `order_date` | `YYYY-MM-DD` | One row per order, not per customer |
| `order_value_eur` | float | Optional; missing is read as 0 |

Extra columns are ignored, so an export can be passed through unmodified as
long as these three exist.

### From a Shopify export

`Orders > Export > Orders by date`. The export gives one row per line item,
with the customer email repeated and the order total only on the first row of
each order. Rename and deduplicate:

| Shopify column | Becomes |
| --- | --- |
| `Email` | `email` |
| `Created at` | `order_date` (truncate the time portion) |
| `Total` | `order_value_eur` |

Keep only rows where `Total` is non-empty — those are the order-level rows.
Otherwise a five-item order counts as five orders and the customer is
misclassified as `Repeat`.

## `consent.csv`

| Column | Type | Notes |
| --- | --- | --- |
| `email` | string | Lowercased and trimmed on read |
| `consent_status` | string | Only exactly `opted_in` passes the gate |
| `consent_source` | string | Not read by the script; kept for the audit trail |
| `consent_timestamp` | ISO 8601 UTC | Not read by the script; kept for the audit trail |

An email present in `orders.csv` but absent from `consent.csv` is suppressed as
`unknown`. That is deliberate: absence of a record is not permission. See
[`../docs/consent.md`](../docs/consent.md).

## Reproducing the example run

```bash
python src/sync_klaviyo.py --as-of 2026-06-01
```

`--as-of` pins the reference date so recency, and therefore every lifecycle
stage, is reproducible. Without it the script uses today and the example
output drifts — every customer eventually ages into `Churned`.

Expected: 7 customers in, 5 eligible across all five stages, 2 suppressed
(one `opted_out`, one with no consent record).
