---
id: "01KR9A3F20M01PGF32CF88W9A6"
name: "PricingRefreshLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/pricing_refresh_loop.py:PricingRefreshLoop"
aliases: ["pricing refresh loop", "litellm pricing poller", "model pricing caretaker"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Daily caretaker loop that fetches LiteLLM's `model_prices_and_context_window.json` via stdlib `urllib`, filters to Anthropic-provider entries (normalizing Bedrock keys), diffs against `src/assets/model_pricing.json`, and opens or updates a `pricing-refresh-auto` PR when drift is detected (ADR-0029, ADR-0049). A bounds guard rejects suspicious price moves. Bounds violations, parse errors, and schema errors open a single deduplicated `[pricing-refresh]` `hydraflow-find` issue. Network errors log-and-retry on the next tick without filing issues.

## Invariants

- Kill-switch is the `HYDRAFLOW_DISABLE_PRICING_REFRESH=1` env var.
- PR is always on the fixed branch `pricing-refresh-auto`; no-op ticks do not open a PR.
- Bounds violations are separate from network errors; each has a distinct response path.
