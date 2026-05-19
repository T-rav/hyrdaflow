# ADR-0078 — PricingRefreshLoop: Autonomous LLM Pricing Drift Detection

**Status:** Proposed
**Date:** 2026-05-19

## Context

`src/assets/model_pricing.json` is the source of truth for per-token cost estimates used by HydraFlow's budget-tracking subsystems. LiteLLM maintains an upstream `model_prices_and_context_window.json` that covers all Anthropic-provider models. Without an autonomous refresh path, the local pricing file drifts from upstream as models are updated, new models ship, and price changes land — causing budget estimates to become inaccurate.

The refresh is a bounded, deterministic operation: fetch, filter, diff, bounds-check, open PR if changed. There is no reason to require human involvement unless the bounds check flags a suspicious price movement.

## Decision

`PricingRefreshLoop` (`src/pricing_refresh_loop.py`) subclasses `BaseBackgroundLoop` and runs daily. Each tick:

1. Fetches LiteLLM's JSON via stdlib `urllib` (30-second timeout).
2. Filters to Anthropic-provider entries; normalizes Bedrock key naming via `filter_anthropic_entries`.
3. Computes a diff against `src/assets/model_pricing.json` via `compute_pricing_diff`.
4. If no drift: logs "no drift", returns `{drift: False}`, no PR.
5. If drift passes the bounds guard: writes the proposed file, opens or updates the `pricing-refresh-auto` PR via `auto_pr.open_automated_pr_async`.
6. Bounds violations, parse errors, schema errors: opens one deduplicated `[pricing-refresh] <title>` `hydraflow-find` issue (dedup by title prefix).
7. Network errors: log-and-retry on next tick; no issue filing to avoid noise.

Kill-switch: `HYDRAFLOW_DISABLE_PRICING_REFRESH=1` env var (ADR-0049 convention; no config field).

## Consequences

- Pricing file stays current with upstream without operator involvement.
- Suspicious price movements (bounds violation) surface as `hydraflow-find` issues for human review before the PR merges.
- The PR always targets the fixed branch `pricing-refresh-auto`; updates to an existing open PR rather than opening duplicates.
- Operators who want to block a specific refresh can close the PR and label it `no-auto-fix`.

## Alternatives considered

- **Manual script.** Rejected: already implemented as a one-shot; the loop is the steady-state replacement, same as `EntryEvidenceLoop` replacing its migration script (ADR-0062).
- **Dependabot-style file sync.** Rejected: requires GitHub App configuration; the in-process loop is simpler and already available.

## Related

- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — kill-switch convention
- `src/pricing_refresh_loop.py:PricingRefreshLoop`
- `src/pricing_refresh_diff.py:compute_pricing_diff`
- `src/assets/model_pricing.json` — the file under management
