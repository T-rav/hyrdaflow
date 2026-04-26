# PricingRefreshLoop — Design Spec

**Status:** Approved (2026-04-26)
**Goal:** A daily caretaker loop that detects drift between `src/assets/model_pricing.json` and an upstream structured pricing source (LiteLLM's `model_prices_and_context_window.json`), and opens a PR with the diff for human review. Stops the per-model cost dashboard (PR #8447) from going stale as Anthropic ships rate changes.

## 1. Context

PR #8447 added per-model cost breakdown to the Factory Cost dashboard. The dashboard re-prices token counts from `inferences.jsonl` on every request via `model_pricing.estimate_cost(model, ...)`, which reads `src/assets/model_pricing.json`. That file's pricing data goes stale whenever Anthropic publishes a new model or changes existing rates — at which point the dashboard quietly underreports cost.

Today the file is hand-edited. This spec adds a caretaker loop that automates detection-and-proposal of refreshes, while keeping a human in the loop for the final apply.

## 2. Source of truth

**LiteLLM's `model_prices_and_context_window.json`** at:

`https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`

Why LiteLLM and not Anthropic's HTML docs:

- Stable raw URL (GitHub raw blob — no redesign breakage).
- Structured JSON (no HTML parser, no `BeautifulSoup`).
- Community-maintained, typically updated within hours of provider rate changes.
- Trivially testable (snapshot a minimal subset as a fixture).
- Stdlib-only fetch (`urllib.request` + `json.loads`) — no new dependency.

LiteLLM's relevant fields per Claude entry:

```json
{
  "input_cost_per_token": 1e-06,
  "output_cost_per_token": 5e-06,
  "cache_creation_input_token_cost": 1.25e-06,
  "cache_read_input_token_cost": 1e-07,
  "litellm_provider": "anthropic"
}
```

Map to our `model_pricing.json` shape:

| LiteLLM field | Our field | Transform |
|---|---|---|
| `input_cost_per_token` | `input_cost_per_million` | × 1e6 |
| `output_cost_per_token` | `output_cost_per_million` | × 1e6 |
| `cache_creation_input_token_cost` | `cache_write_cost_per_million` | × 1e6 |
| `cache_read_input_token_cost` | `cache_read_cost_per_million` | × 1e6 |

Skip non-anthropic entries (`litellm_provider != "anthropic"`).

## 3. Behavior

```
1. Fetch upstream JSON (urllib.request, 30s timeout)
2. Parse + filter to {k: v for k, v in upstream.items() if v.get("litellm_provider") == "anthropic"}
3. Strip the `anthropic.` prefix and `-v1:0` / `@YYYYMMDD` Bedrock-suffix variants
   so keys match our local naming (e.g. `anthropic.claude-haiku-4-5-20251001-v1:0`
   → `claude-haiku-4-5-20251001`)
4. Compute the proposed file:
   - For each LOCAL model: if upstream has the key and any cost field differs,
     update that field. Aliases preserved.
   - For each UPSTREAM model not in LOCAL: ADD as a new entry (with derived
     aliases — see §6).
   - LOCAL models not in UPSTREAM: KEEP unchanged (we may be ahead of LiteLLM).
5. Diff-bounds guard: if any single cost field changes by more than +100% or
   less than -50%, REJECT the entire proposal (do not write the file). Open
   a `hydraflow-find` issue with the offending deltas instead.
6. If proposed file is byte-equal to current → no-op, return `{drift: False}`.
7. Otherwise: bump `updated_at` to today's ISO date, write proposed file,
   open/update PR via `auto_pr.open_automated_pr_async` on fixed branch
   `pricing-refresh-auto`, title `chore(pricing): refresh from LiteLLM`.
   Return `{drift: True, pr_url: <url>, changed_models: <count>, added_models: <count>}`.
```

The loop **never** auto-merges — every refresh is human-reviewed.

## 4. Failure handling

| Failure mode | Action | Issue created? |
|---|---|---|
| Network error / timeout | Log, return `{drift: False, error: "network"}`, retry next tick | No (avoids spam during transient outages) |
| HTTP non-200 | Same as network error | No |
| JSON parse error | Open `hydraflow-find` issue (deduped by title prefix) | Yes |
| Schema violation (Claude entry missing required cost field) | Open `hydraflow-find` issue with field name | Yes |
| Diff-bounds violation (cost moved >100% up or <-50% down) | Open `hydraflow-find` issue with offending model + delta | Yes |
| `auto_pr.open_automated_pr_async` raised | Log, return `{error: "pr_failed"}`, retry next tick | No (auto_pr has its own dedup) |

Issues use a fixed title prefix `[pricing-refresh] ` and dedup via `find_existing_issue` so we don't spam.

## 5. Cadence + kill-switch

- **Tick interval:** 86400s (daily). Pricing changes infrequently; daily is sufficient.
- **Kill-switch env var:** `HYDRAFLOW_DISABLE_PRICING_REFRESH` per ADR-0049. Same in-body short-circuit pattern as the other 18 caretaker loops.

## 6. Alias derivation for new entries

When LiteLLM has a Claude model we don't, we ADD it with a sensible alias list. Pattern matches our existing convention:

- Family alias: `claude-3-5-haiku`, `claude-haiku-4-5`, etc. (strip the `-YYYYMMDD` suffix)
- Generation alias: when applicable, `claude-4-5-haiku`, `claude-3-7-sonnet`
- Generic: `haiku`, `sonnet`, `opus` ONLY for the latest entry of each family, never for legacy entries (per the §1 model_pricing.json convention introduced in PR #8447).

The "latest" decision is mechanical: highest version number, then most recent date suffix. Implemented as a small ranking helper.

If alias derivation fails (unfamiliar naming pattern), the model is added with NO aliases (only its canonical key) — humans can fill aliases manually during PR review.

## 7. Idempotence

- **PR**: title-prefix lookup before opening. If a PR with title starting `chore(pricing): refresh from LiteLLM` is open on `pricing-refresh-auto`, force-push the branch and update the PR body. Same pattern as L24's `arch-regen-auto`.
- **Issue**: title-prefix lookup `[pricing-refresh] `. If found, append a comment with the new failure detail; do not open a duplicate issue.

## 8. Five-checkpoint wiring (per ADR-0029, gotchas.md)

1. Import `PricingRefreshLoop` in `bg_worker_manager.py`
2. Add `pricing_refresh: PricingRefreshLoop` field to the `Services` dataclass
3. Instantiate in `_create_services` (or equivalent)
4. Constructor wire-up — pass needed ports (`github`, `pr_helper`)
5. Register in `bg_loop_registry`
6. Add to the `run_task` dispatch
7. Update `tests/orchestrator_integration_utils.py` SimpleNamespace (`services.pricing_refresh = FakeBackgroundLoop()`)

Plus catalog wiring for MockWorld:

- `tests/scenarios/catalog/loop_registrations.py` — add `_build_pricing_refresh` to `_BUILDERS` dict (NOT the decorator factory — that's a known gotcha).
- `tests/scenarios/catalog/loop_ports.py` — declare ports the loop consumes (`github`, `pr_helper`).

## 9. Files

**Create:**
- `src/pricing_refresh_loop.py` — the loop class
- `src/pricing_refresh_diff.py` — pure functions for parse, normalize, diff, bounds-check (separated for testability without instantiating the loop)
- `tests/test_pricing_refresh_diff.py` — unit tests on the pure functions
- `tests/test_pricing_refresh_loop_scenario.py` — `_do_work` integration test with mocked seams
- `tests/scenarios/test_pricing_refresh_loop_mockworld.py` — full `run_with_loops` MockWorld scenarios
- `tests/fixtures/litellm_pricing_sample.json` — minimal hand-crafted LiteLLM-shaped JSON

**Modify:**
- `src/bg_worker_manager.py` — five-checkpoint wiring
- `tests/orchestrator_integration_utils.py` — SimpleNamespace entry
- `tests/scenarios/catalog/loop_registrations.py` — `_BUILDERS` entry
- `tests/scenarios/catalog/loop_ports.py` — port declarations

## 10. Testing strategy

**Unit (pure functions in `pricing_refresh_diff.py`):**
- `test_normalize_strips_bedrock_prefix_and_suffix` — `anthropic.claude-haiku-4-5-20251001-v1:0` → `claude-haiku-4-5-20251001`
- `test_filter_keeps_only_anthropic_provider`
- `test_map_litellm_fields_to_local_shape` — × 1e6 conversion correctness
- `test_diff_detects_value_change_only` — same model, different prices
- `test_diff_adds_new_upstream_model`
- `test_diff_keeps_local_only_model_unchanged`
- `test_bounds_guard_rejects_doubling`
- `test_bounds_guard_rejects_halving`
- `test_bounds_guard_accepts_modest_change`
- `test_alias_derivation_for_known_pattern`
- `test_alias_derivation_falls_back_to_canonical_only`

**Loop scenario (`_do_work` directly with mocked seams):**
- `test_no_drift_returns_drift_false`
- `test_drift_detected_opens_pr`
- `test_network_error_does_not_open_issue`
- `test_parse_error_opens_deduped_issue`
- `test_bounds_violation_opens_issue_no_pr`

**MockWorld scenario (`run_with_loops`):**
- `test_no_drift_path` — clean upstream → no PR opened
- `test_drift_path` — divergent upstream → PR opens with `pricing-refresh-auto` branch
- (Mirrors the L24 DiagramLoop scenarios in `test_diagram_loop_mockworld.py`.)

**Fixture content** (`tests/fixtures/litellm_pricing_sample.json`) — 5–10 hand-crafted entries:
- 3 anthropic Claude entries (matches local: haiku-4-5, sonnet-4-6, opus-4-7)
- 1 anthropic Bedrock-prefixed entry (tests stripping)
- 1 non-anthropic entry (tests provider filter)
- Total ~2KB, easy to review in PR.

## 11. Risks

| Risk | Mitigation |
|---|---|
| LiteLLM lags behind Anthropic for new models | Loop never deletes local entries → bleeding-edge config preserved |
| LiteLLM ships a wrong price | Diff-bounds guard catches >100% jumps; smaller errors caught at PR review |
| Alias-derivation gets a new naming pattern wrong | Loop emits canonical-only alias; humans fix in PR review |
| Daily PR noise if pricing changes daily | In practice pricing changes are weeks-apart; no expected noise |
| Loop runs while a refresh PR is already open | Force-pushes to `pricing-refresh-auto`, updates PR — same L24 pattern |
| Network outage triggers issue spam | Network errors specifically don't open issues |

## 12. Out of scope (deferred)

- Generic registry pattern (Plan B from brainstorming) — no second metadata target on the horizon.
- Auto-merge on small price changes — always human review.
- Triple-redundant source (Anthropic docs + LiteLLM + 3rd) — single source for now; if LiteLLM rots, swap source.
- Tracking model context windows / capabilities flags from LiteLLM — pricing only.

## 13. Definition of done

- `make quality` passes (lint, type, security, tests).
- New `PricingRefreshLoop` ticks once per day, has kill-switch, follows five-checkpoint pattern.
- Drift → PR via `auto_pr.open_automated_pr_async` on `pricing-refresh-auto` branch.
- Diff-bounds violation → `hydraflow-find` issue with deltas, no file change.
- MockWorld scenarios cover drift / no-drift paths.
- No new runtime dependencies (stdlib `urllib.request` + `json` only).
- Existing per-loop spend dashboard (PR #8447) continues to function unchanged.

## 14. References

- L24 DiagramLoop pattern: `src/diagram_loop.py`, `tests/scenarios/test_diagram_loop_mockworld.py`
- ADR-0029 (caretaker loop pattern), ADR-0049 (kill-switch convention)
- `docs/wiki/gotchas.md` — five-checkpoint wiring
- LiteLLM pricing JSON: https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json
- Spec for the dashboard this loop keeps fresh: `docs/superpowers/specs/2026-04-26-per-model-cost-breakdown-design.md` (PR #8447)
