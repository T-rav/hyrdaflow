## Intent

Stand up multi-tenant billing so enterprise customers can consolidate
invoicing under a single organisation while still attributing usage to
individual team members. Billing must integrate with our existing
Stripe Connect integration and support both per-org and per-user
aggregation modes.

## Affected area

- `src/billing/aggregator.py` — usage roll-up
- `src/billing/stripe_adapter.py` — Stripe Connect integration
- `migrations/` — new `org_billing_accounts` table
- `src/api/billing_routes.py` — three new endpoints listed below

## Acceptance criteria

- `POST /api/orgs/:id/billing` creates a billing account and returns a
  Stripe Customer ID within 500ms p95.
- `GET /api/orgs/:id/usage` returns per-user rollups when
  `?mode=per-user` and org totals when `?mode=per-org`.
- Invoices are generated on the 1st of each month and emailed to the
  org admin within 6 hours of generation.

## Open questions

(none)

## Known unknowns

- How Stripe handles cross-border tax jurisdictions when the billing
  account org is in one country and the paying user is in another.
- Whether our current auth tokens carry enough org-scoped claims to
  satisfy the billing API without re-issuing.
