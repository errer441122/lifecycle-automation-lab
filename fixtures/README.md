# Schema Test Fixtures

The files in this directory are **minimal platform schema fixtures** (`example.com` addresses only) used to validate CSV parsers, pre-flight QA rules, and UI outputs in automated CI tests. They are **not** real customer lists or performance datasets.

| Fixture | Platform Export Schema Tested |
| --- | --- |
| `shopify_orders_schema.csv` | Shopify Admin → *Orders > Export* (multi-line-item folding, voided order filtering, `Discount Amount`) |
| `klaviyo_list_export_schema.csv` | Klaviyo → *Lists & Segments > Export CSV* (consent status, timestamp, method, DOI flag, suppression reason, last open) |
| `hubspot_contacts_schema.csv` | HubSpot → *CRM > Contacts > Export CSV* (marketing contact status, unsubscribed, bounce reason, legal basis, DOI status) |
| `ga4_traffic_reference_schema.csv` | GA4 → *Reports > Acquisition > Traffic acquisition > Export CSV* (comment header skipping + `Session source / medium`) |
| `broken_klaviyo_email.html` | Klaviyo Liquid template with empty fallback, missing UTMs, dead link, missing unsubscribe, missing `alt`, and discount offer |
| `broken_hubspot_email.html` | HubSpot HubL template with unguarded `contact.firstname`, malformed UTMs, and promo code |
| `clean_klaviyo_email.html` | Passing non-promotional Klaviyo template |

Real company exports should never be committed to git (`data/*.csv` and `build/` are gitignored).
