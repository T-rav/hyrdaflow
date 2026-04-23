# Shape proposal — multi-tenant billing

## Option A — Per-org aggregation on Stripe Connect

Roll usage up at the organisation level and settle via Stripe Connect
standard accounts. Edits: `src/billing/aggregator.py`,
`src/billing/stripe_adapter.py`, `migrations/2026-04-23-org-billing.sql`.

Trade-off: individual team members lose visibility into their own
cost attribution unless we layer a per-user view on top. Stripe
Connect also requires org admins to complete KYC — expect a 5-10%
activation drop-off.

## Option B — Per-org aggregation with our own ledger

Same org-level rollup, but skip Stripe Connect and book invoices
through our existing ledger service.

Trade-off: we take on PCI scope and chargeback handling directly.
Engineering-heavy; pushes the first-dollar date out by a quarter.

## Option C — Defer

Keep the current per-seat pricing. Cost of inaction: two enterprise
deals (~$250k ARR) stalled on consolidated invoicing.
