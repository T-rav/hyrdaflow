# Per-Model Cost Breakdown — Design Spec

**Status:** Approved (2026-04-26)
**Goal:** Surface per-model spend detail (Opus / Sonnet / Haiku / cache split) inside the existing Factory Cost tab so we can spot loops running expensive models when cheaper would suffice — closes the observability portion of dark-factory roadmap gap #9.

## 1. Context

HydraFlow already ships a Factory Cost tab in the dashboard with `PerLoopCostTable`, `FactoryCostSummary`, `CostByPhaseChart`, `WaterfallView`, `CacheHitChart`. Backend rollups in `src/dashboard_routes/_cost_rollups.py` aggregate `metrics/prompt/inferences.jsonl` and `traces/_loops/<slug>/run-*.json` and re-price them on each request via `model_pricing.estimate_cost`. Each record already carries a `model` field (cost_rollups.py:110).

**The gap:** rollups sum cost per loop but do not break out by model. The dashboard surfaces total cost per loop without telling you whether L24 is hitting Opus or Haiku, or what fraction of spend is cache reads. Without that detail, "loop X is expensive" is unactionable.

This spec adds per-model breakdown to two surfaces:

1. **Per-loop drilldown** — expandable rows in `PerLoopCostTable` show Opus / Sonnet / Haiku split inline.
2. **Cross-loop view** — new `CostByModelChart` shows where the fleet's spend is concentrated by model.

Out of scope: hard caps / circuit breakers (gap #2), per-repo dimension (deferred to PSH onboarding), routing recommendations, public Pages dashboard.

## 2. Architecture

Pure aggregation change. No new instrumentation, no schema migration. The data already lives in `inferences.jsonl` and `traces/_loops/<slug>/run-*.json`.

### Backend

`src/dashboard_routes/_cost_rollups.py`:

- **Extend `build_per_loop_cost`** — each row gains a `model_breakdown` field:
  ```python
  model_breakdown: dict[str, dict[str, float | int]]
  # e.g.
  # {
  #   "claude-opus-4-7":   {"cost_usd": 1.234, "calls": 12, "input_tokens": 45000, "output_tokens": 3200, "cache_read_tokens": 89000, "cache_write_tokens": 5000},
  #   "claude-sonnet-4-6": {"cost_usd": 0.045, "calls": 3,  "input_tokens": 8000,  "output_tokens": 600,  "cache_read_tokens": 12000, "cache_write_tokens": 0},
  # }
  ```
  Records with empty/missing `model` bucket under the literal string `"unknown"`.

- **New `build_cost_by_model(config, range)`** — returns
  ```python
  list[dict[str, float | int | str]]
  # [
  #   {"model": "claude-opus-4-7", "cost_usd": 12.4, "calls": 87, "input_tokens": ..., "output_tokens": ..., "cache_read_tokens": ..., "cache_write_tokens": ...},
  #   {"model": "claude-sonnet-4-6", ...},
  # ]
  ```
  Sorted descending by `cost_usd`. Same range vocabulary as existing rollups (`24h`, `7d`, `30d`, `90d`).

Both functions iterate the same three sources `build_per_loop_cost` already uses; the addition is one extra `defaultdict` keyed by `(loop, model)` and `(model,)` respectively.

### Endpoints

`src/dashboard_routes/_diagnostics_routes.py`:

- `GET /api/diagnostics/loops/cost?range=<r>` — **unchanged URL**, additive payload. Existing consumers see existing fields; new consumers read `model_breakdown`.
- `GET /api/diagnostics/cost/by-model?range=<r>` — NEW. Returns the list above plus a `range` echo and `generated_at` ISO timestamp (matches existing endpoint conventions).

### Frontend (`src/ui/src/components/diagnostics/`)

- **`PerLoopCostTable.jsx`** — add expand-on-click. Clicking the Loop *cell* of a data row toggles an embedded sub-table showing per-model rows with columns: **Model · Cost · Calls · Input Tokens · Output Tokens · Cache Read · Cache Write**. Sub-table rows also show percent share of the loop's total cost. No new top-level columns (the table already has 6). A small chevron in the Loop cell signals expandability.

- **`CostByModelChart.jsx`** — NEW. Horizontal stacked bar of cost-by-model for the selected range. Toggle button switches the bar units between **$**, **calls**, **input tokens**, **output tokens**. Tooltip on hover shows the absolute number and % share. Accepts the same `range` URL param vocabulary as `/api/diagnostics/loops/cost` (`24h` / `7d` / `30d` / `90d`); the chart's range control is wired by the parent `FactoryCostTab` so the existing range selection state is reused — no new selector component.

- **`FactoryCostTab.jsx`** — slot `CostByModelChart` between `FactoryCostSummary` and `PerLoopCostTable`. The chart is the "where is the spend going" answer; the table is the drilldown.

## 3. Data flow

```
inferences.jsonl ─┐
traces/_loops/ ───┼─► iter_priced_inferences (existing)
trace subprocess ─┘                │
                                   ▼
                  defaultdict[(loop, model)] sum
                                   │
                  ┌────────────────┴────────────────┐
                  ▼                                 ▼
         build_per_loop_cost              build_cost_by_model
       (existing + nested model)               (new)
                  │                                 │
                  ▼                                 ▼
   /api/diagnostics/loops/cost      /api/diagnostics/cost/by-model
                  │                                 │
                  ▼                                 ▼
         PerLoopCostTable                  CostByModelChart
        (expand-on-click rows)              (stacked bar)
```

The pricing call (`ModelPricingTable.estimate_cost(model, ...)`) is already per-record. Bucketing by model before summing requires no change to pricing logic.

## 4. Components

### Backend types

```python
class ModelBreakdownEntry(TypedDict):
    cost_usd: float
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int

class CostByModelRow(TypedDict):
    model: str
    cost_usd: float
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
```

(Chosen over Pydantic models because the surrounding `_cost_rollups.py` already uses plain dicts as the wire format; switching to Pydantic for one new field would be inconsistent.)

### Frontend props

```jsx
// PerLoopCostTable: existing rows now have row.model_breakdown — optional, no breakage if absent
// CostByModelChart: { rows: [{model, cost_usd, calls, ...}], range, onRangeChange }
```

## 5. Error handling

- **Missing `model` field on a record** → bucket as `"unknown"`. Surfaces in UI as a literal "unknown" row, which is the correct signal that something upstream is dropping model attribution.
- **Empty data** (no inferences in range) → empty list / empty `model_breakdown` dict. UI renders "no data in this window" placeholder for the chart, omits the expand control on rows with no breakdown.
- **Unpriced model** (in `inferences.jsonl` but missing from `model_pricing.json`) → `model_pricing.estimate_cost` already returns 0 cost. Counts and tokens are still surfaced. The "0 cost" row signals "update pricing table." This is consistent with existing behavior; no new logic required.
- **Asyncio nested-loop edge case** — `build_per_loop_cost` already has a `nested event loop` guard (line 416). The new aggregator follows the same pattern.

## 6. Testing strategy

### Backend

- `tests/test_cost_rollups_per_loop.py` (existing — extend):
  - `test_model_breakdown_present_for_mixed_model_loop` — loop with Opus + Sonnet records returns both keys with correct totals
  - `test_model_breakdown_buckets_missing_model_under_unknown`
  - `test_model_breakdown_preserves_cache_token_split` — cache_read + cache_write tracked separately per model
  - `test_existing_fields_unchanged` — additive guarantee (regression)

- `tests/test_cost_rollups_by_model.py` (NEW):
  - `test_build_cost_by_model_happy_path` — three models, sorted descending by cost
  - `test_build_cost_by_model_empty_data_returns_empty_list`
  - `test_build_cost_by_model_respects_range` — `7d` filter excludes 8-day-old records
  - `test_build_cost_by_model_handles_unpriced_model` — model in records but not in pricing table → 0 cost, tokens still summed

- `tests/test_diagnostics_routes_cost_by_model.py` (NEW):
  - Endpoint smoke + range query + 400 on invalid range

### Frontend

- `src/ui/src/components/diagnostics/__tests__/PerLoopCostTable.test.jsx` (extend):
  - `expand_row_click_reveals_per_model_subtable`
  - `expand_row_omitted_when_model_breakdown_absent` — backward compat
  - `subtable_shows_percent_share_per_model`

- `src/ui/src/components/diagnostics/__tests__/CostByModelChart.test.jsx` (NEW):
  - `renders_stacked_bar_for_three_models`
  - `unit_toggle_switches_between_dollars_calls_tokens`
  - `range_change_refetches_data`
  - `empty_data_renders_placeholder`

## 7. Migration / rollout

- No data migration. New fields are additive on the wire and in storage (storage unchanged).
- Existing dashboards continue to render. The new chart appears once `FactoryCostTab.jsx` is updated.
- Backward compatibility: any external consumer of `/api/diagnostics/loops/cost` keeps working — `model_breakdown` is a new optional field, not a renamed one.

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `model_pricing.json` doesn't price current model IDs (Opus 4.7-1M etc.) | Medium | Verify before implementation; if missing, separate task to update the asset. Aggregation still produces correct token/call counts; only `cost_usd` would underreport. |
| Cache token split makes the bar chart visually noisy | Medium | Default chart units to `$`. Cache distinction belongs in the per-loop drilldown, not the cross-loop overview. |
| Records with empty `model` field create a large `"unknown"` bucket | Low | Treated as signal — the dashboard surfacing it is the right outcome. |
| Performance on large `inferences.jsonl` from a +1 dimension on the defaultdict | Low | `inferences.jsonl` is already iterated once per request. Adding a dict key per record is O(1). |

## 9. Definition of done

- `make quality` passes (lint, type, security, tests).
- Click any loop in `PerLoopCostTable` → sub-row shows model split with cost, calls, I/O tokens, cache split, % share.
- `CostByModelChart` renders on `FactoryCostTab` for last-24h by default; range and unit toggles work.
- New backend tests cover happy path, empty data, range filter, missing model, unpriced model.
- New frontend tests cover expand row, unit toggle, range change, empty data placeholder.
- Existing `/api/diagnostics/loops/cost` consumers unaffected (regression test green).
- No new dependencies added.

## 10. References

- Existing infrastructure: `src/dashboard_routes/_cost_rollups.py`, `src/model_pricing.py`, `src/ui/src/components/diagnostics/PerLoopCostTable.jsx`, `src/ui/src/components/diagnostics/FactoryCostTab.jsx`
- Roadmap context: `docs/methodology/self-documenting-architecture.md` (gap #9 in dark-factory landscape report, April 2026)
- Related but out of scope: `src/cost_budget_alerts.py` (would tie in if gap #2 lands)
