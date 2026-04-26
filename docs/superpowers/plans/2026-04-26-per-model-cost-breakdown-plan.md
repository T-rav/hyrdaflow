# Per-Model Cost Breakdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-model spend breakdown (cost, calls, tokens, cache split) to the existing Factory Cost tab so we can see when a loop is on Opus that should be on Haiku.

**Architecture:** Pure aggregation change. `inferences.jsonl` already carries the `model` field. Backend gains a `model_breakdown` field on existing per-loop rows plus a new cross-loop `build_cost_by_model` aggregator and `/cost/by-model` endpoint. Frontend adds expand-on-click rows to `PerLoopCostTable` and a new `CostByModelChart` slotted into `FactoryCostTab`.

**Tech Stack:** Python (FastAPI, pytest), React (vitest, @testing-library/react), inline-SVG for the chart (no new deps).

**Spec:** `docs/superpowers/specs/2026-04-26-per-model-cost-breakdown-design.md`

---

## File touchpoints

**Modify:**
- `src/assets/model_pricing.json` — refresh model entries for current IDs
- `src/dashboard_routes/_cost_rollups.py` — extend `build_per_loop_cost`, add `build_cost_by_model`
- `src/dashboard_routes/_diagnostics_routes.py` — wire `/cost/by-model`
- `src/ui/src/components/diagnostics/PerLoopCostTable.jsx` — expand-on-click sub-rows
- `src/ui/src/components/diagnostics/FactoryCostTab.jsx` — fetch new endpoint, slot chart
- `tests/test_cost_rollups_helpers.py` — model_breakdown coverage
- `tests/test_diagnostics_cost_rollup_routes.py` — `/cost/by-model` route smoke
- `src/ui/src/components/diagnostics/__tests__/PerLoopCostTable.test.jsx` — expand interaction

**Create:**
- `src/ui/src/components/diagnostics/CostByModelChart.jsx` — stacked-bar chart
- `tests/test_cost_rollups_by_model.py` — new aggregator
- `src/ui/src/components/diagnostics/__tests__/CostByModelChart.test.jsx` — chart tests

---

## Task 1: Refresh model pricing table

Spec risk #1: pricing JSON is stale. Without this, `model_breakdown` rows from current loops will all show `cost_usd: 0`.

**Files:**
- Modify: `src/assets/model_pricing.json`

- [ ] **Step 1: Replace model entries with current IDs**

Open `src/assets/model_pricing.json` and replace the `models` block. Current production model IDs (from `CLAUDE.md` — "Opus 4.7: 'claude-opus-4-7', Sonnet 4.6: 'claude-sonnet-4-6', Haiku 4.5: 'claude-haiku-4-5-20251001'"). Pricing is the published Anthropic pricing as of 2026-04 (verify against `https://docs.anthropic.com/en/docs/about-claude/models` if uncertain — if pricing differs, prefer the docs).

```json
{
  "schema_version": 1,
  "currency": "USD",
  "updated_at": "2026-04-26",
  "source": "https://docs.anthropic.com/en/docs/about-claude/models",
  "models": {
    "claude-haiku-4-5-20251001": {
      "provider": "anthropic",
      "aliases": ["haiku", "claude-haiku-4-5", "claude-4-5-haiku"],
      "input_cost_per_million": 1.00,
      "output_cost_per_million": 5.00,
      "cache_write_cost_per_million": 1.25,
      "cache_read_cost_per_million": 0.10
    },
    "claude-sonnet-4-6": {
      "provider": "anthropic",
      "aliases": ["sonnet", "claude-sonnet-4-6", "claude-4-6-sonnet"],
      "input_cost_per_million": 3.00,
      "output_cost_per_million": 15.00,
      "cache_write_cost_per_million": 3.75,
      "cache_read_cost_per_million": 0.30
    },
    "claude-opus-4-7": {
      "provider": "anthropic",
      "aliases": ["opus", "claude-opus-4-7", "claude-4-7-opus", "claude-opus-4-7[1m]"],
      "input_cost_per_million": 15.00,
      "output_cost_per_million": 75.00,
      "cache_write_cost_per_million": 18.75,
      "cache_read_cost_per_million": 1.50
    },
    "claude-3-5-haiku-20241022": {
      "provider": "anthropic",
      "aliases": ["claude-3-5-haiku", "claude-3.5-haiku"],
      "input_cost_per_million": 0.80,
      "output_cost_per_million": 4.00,
      "cache_write_cost_per_million": 1.00,
      "cache_read_cost_per_million": 0.08
    },
    "claude-sonnet-4-20250514": {
      "provider": "anthropic",
      "aliases": ["claude-4-sonnet", "claude-sonnet-4"],
      "input_cost_per_million": 3.00,
      "output_cost_per_million": 15.00,
      "cache_write_cost_per_million": 3.75,
      "cache_read_cost_per_million": 0.30
    },
    "claude-opus-4-20250514": {
      "provider": "anthropic",
      "aliases": ["claude-4-opus", "claude-opus-4"],
      "input_cost_per_million": 15.00,
      "output_cost_per_million": 75.00,
      "cache_write_cost_per_million": 18.75,
      "cache_read_cost_per_million": 1.50
    }
  }
}
```

Note: legacy entries kept so historical inferences.jsonl rows still price correctly; new entries added. `aliases` includes `claude-opus-4-7[1m]` because that's the literal `model` string the env reports (per CLAUDE.md system reminder).

- [ ] **Step 2: Verify it loads**

Run: `uv run python -c "from model_pricing import load_pricing; p = load_pricing(); print(sorted(p._table.keys())[:6])"`

Expected: prints six current+legacy model IDs without exception.

- [ ] **Step 3: Run existing pricing tests**

Run: `uv run pytest tests/test_model_pricing.py -v`

Expected: all existing tests pass (no regression on legacy IDs).

- [ ] **Step 4: Commit**

```bash
git add src/assets/model_pricing.json
git commit -m "chore(pricing): refresh model_pricing.json for current model IDs"
```

---

## Task 2: Backend — extend `build_per_loop_cost` with `model_breakdown`

Add a per-`(loop, model)` defaultdict alongside the existing per-loop ones; emit nested `model_breakdown` on each row.

**Files:**
- Modify: `src/dashboard_routes/_cost_rollups.py:364-467`
- Test: `tests/test_cost_rollups_helpers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cost_rollups_helpers.py`:

```python
def test_per_loop_cost_includes_model_breakdown_for_mixed_models(
    tmp_path, monkeypatch
) -> None:
    """build_per_loop_cost emits model_breakdown with one entry per model used."""
    from datetime import UTC, datetime, timedelta

    config = MagicMock()
    config.data_root = tmp_path
    config.data_path = lambda *parts: tmp_path.joinpath(*parts)

    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    started = now - timedelta(minutes=5)
    _write_inference(
        config,
        timestamp=(started + timedelta(seconds=10)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=10_000,
        output_tokens=2_000,
        cache_read_input_tokens=20_000,
        cache_creation_input_tokens=1_000,
    )
    _write_inference(
        config,
        timestamp=(started + timedelta(seconds=20)).isoformat(),
        source="implementer",
        model="claude-sonnet-4-6",
        input_tokens=5_000,
        output_tokens=500,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    _write_loop_trace(
        config,
        "ImplementerLoop",
        started_at=started.isoformat(),
        duration_ms=60_000,
    )

    rows = build_per_loop_cost(config, since=now - timedelta(hours=1), until=now)

    assert len(rows) == 1
    row = rows[0]
    assert row["loop"] == "implementer"
    breakdown = row["model_breakdown"]
    assert set(breakdown.keys()) == {"claude-opus-4-7", "claude-sonnet-4-6"}
    opus = breakdown["claude-opus-4-7"]
    assert opus["calls"] == 1
    assert opus["input_tokens"] == 10_000
    assert opus["output_tokens"] == 2_000
    assert opus["cache_read_tokens"] == 20_000
    assert opus["cache_write_tokens"] == 1_000
    assert opus["cost_usd"] > 0
    sonnet = breakdown["claude-sonnet-4-6"]
    assert sonnet["calls"] == 1
    assert sonnet["input_tokens"] == 5_000


def test_per_loop_cost_buckets_missing_model_under_unknown(
    tmp_path,
) -> None:
    """Records with empty/missing model bucket under 'unknown'."""
    from datetime import UTC, datetime, timedelta

    config = MagicMock()
    config.data_root = tmp_path
    config.data_path = lambda *parts: tmp_path.joinpath(*parts)

    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    started = now - timedelta(minutes=5)
    _write_inference(
        config,
        timestamp=(started + timedelta(seconds=10)).isoformat(),
        source="implementer",
        model="",
        input_tokens=100,
        output_tokens=50,
    )
    _write_loop_trace(
        config,
        "ImplementerLoop",
        started_at=started.isoformat(),
        duration_ms=60_000,
    )

    rows = build_per_loop_cost(config, since=now - timedelta(hours=1), until=now)

    assert rows[0]["model_breakdown"].keys() == {"unknown"}
    assert rows[0]["model_breakdown"]["unknown"]["calls"] == 1


def test_per_loop_cost_existing_fields_unchanged(tmp_path) -> None:
    """Regression: adding model_breakdown does not change existing field values."""
    from datetime import UTC, datetime, timedelta

    config = MagicMock()
    config.data_root = tmp_path
    config.data_path = lambda *parts: tmp_path.joinpath(*parts)

    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    started = now - timedelta(minutes=5)
    _write_inference(
        config,
        timestamp=(started + timedelta(seconds=10)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=1_000,
        output_tokens=200,
    )
    _write_loop_trace(
        config,
        "ImplementerLoop",
        started_at=started.isoformat(),
        duration_ms=60_000,
    )

    rows = build_per_loop_cost(config, since=now - timedelta(hours=1), until=now)

    row = rows[0]
    expected_keys = {
        "loop", "cost_usd", "tokens_in", "tokens_out", "llm_calls",
        "issues_filed", "issues_closed", "escalations", "ticks",
        "ticks_errored", "tick_cost_avg_usd", "wall_clock_seconds",
        "last_tick_at", "tick_cost_avg_usd_prev_period", "model_breakdown",
    }
    assert set(row.keys()) == expected_keys
    assert row["tokens_in"] == 1_000
    assert row["tokens_out"] == 200
    assert row["llm_calls"] == 1
```

If `_write_inference` and `_write_loop_trace` helpers are not already in the file, add them (mirror the ones in `tests/test_diagnostics_cost_rollup_routes.py`):

```python
import json

def _write_inference(config, **fields) -> None:
    d = config.data_root / "metrics" / "prompt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "inferences.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_loop_trace(config, loop, **fields) -> None:
    from trace_collector import _slug_for_loop  # noqa: PLC0415

    d = config.data_root / "traces" / "_loops" / _slug_for_loop(loop)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "loop", "loop": loop, **fields}
    (d / f"run-{fields['started_at'].replace(':', '')}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
```

Add `from unittest.mock import MagicMock` and `from dashboard_routes._cost_rollups import build_per_loop_cost` to the file's imports if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cost_rollups_helpers.py::test_per_loop_cost_includes_model_breakdown_for_mixed_models tests/test_cost_rollups_helpers.py::test_per_loop_cost_buckets_missing_model_under_unknown tests/test_cost_rollups_helpers.py::test_per_loop_cost_existing_fields_unchanged -v`

Expected: 3 FAIL with `KeyError: 'model_breakdown'` or `expected_keys` mismatch.

- [ ] **Step 3: Implement model_breakdown**

In `src/dashboard_routes/_cost_rollups.py`, edit `build_per_loop_cost` (around lines 364–467).

Add a new defaultdict alongside the existing per-loop ones (insert after line 393, the `per_loop_wall` line):

```python
    per_loop_model: dict[str, dict[str, dict[str, float | int]]] = defaultdict(
        lambda: defaultdict(lambda: {
            "cost_usd": 0.0,
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        })
    )
```

In the inner inference-attribution loop (around lines 402–407), after `per_loop_llm_calls[name] += 1`, add:

```python
                    model_key = str(rec.get("model") or "").strip() or "unknown"
                    bucket = per_loop_model[name][model_key]
                    bucket["cost_usd"] += float(rec.get("cost_usd", 0.0) or 0.0)
                    bucket["calls"] += 1
                    bucket["input_tokens"] += int(rec.get("input_tokens", 0) or 0)
                    bucket["output_tokens"] += int(rec.get("output_tokens", 0) or 0)
                    bucket["cache_read_tokens"] += int(
                        rec.get("cache_read_input_tokens", 0) or 0
                    )
                    bucket["cache_write_tokens"] += int(
                        rec.get("cache_creation_input_tokens", 0) or 0
                    )
```

In the row-emission loop (around lines 449–466), add a `model_breakdown` field. Replace the appended dict with:

```python
        # model_breakdown is keyed by class_name (matches per_loop_cost). Round
        # cost_usd to 6 decimals; convert nested defaultdict → plain dict for
        # JSON serialization.
        breakdown_raw = per_loop_model.get(class_name, {})
        model_breakdown = {
            model: {
                "cost_usd": round(float(b["cost_usd"]), 6),
                "calls": int(b["calls"]),
                "input_tokens": int(b["input_tokens"]),
                "output_tokens": int(b["output_tokens"]),
                "cache_read_tokens": int(b["cache_read_tokens"]),
                "cache_write_tokens": int(b["cache_write_tokens"]),
            }
            for model, b in breakdown_raw.items()
        }
        rows.append(
            {
                "loop": worker,
                "cost_usd": round(cost, 6),
                "tokens_in": per_loop_tokens_in.get(class_name, 0),
                "tokens_out": per_loop_tokens_out.get(class_name, 0),
                "llm_calls": per_loop_llm_calls.get(class_name, 0),
                "issues_filed": int(stats.get("issues_filed", 0) or 0),
                "issues_closed": int(stats.get("issues_closed", 0) or 0),
                "escalations": int(stats.get("escalations", 0) or 0),
                "ticks": ticks,
                "ticks_errored": int(stats.get("ticks_errored", 0) or 0),
                "tick_cost_avg_usd": avg_cost,
                "wall_clock_seconds": per_loop_wall.get(class_name, 0),
                "last_tick_at": stats.get("last_tick_at", "") or None,
                "tick_cost_avg_usd_prev_period": prev_avg,
                "model_breakdown": model_breakdown,
            }
        )
```

Update the function docstring (line 372–377) to mention the new field:

```python
    """Return the machinery-level per-loop dashboard rows (spec §4.11 point 5).

    Per-row fields: loop, cost_usd, tokens_in, tokens_out, llm_calls,
    issues_filed, issues_closed, escalations, ticks, tick_cost_avg_usd,
    wall_clock_seconds, tick_cost_avg_usd_prev_period, model_breakdown.

    ``model_breakdown`` is a dict keyed by model name (or "unknown" for
    records missing the field), with nested {cost_usd, calls, input_tokens,
    output_tokens, cache_read_tokens, cache_write_tokens}.
    """
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cost_rollups_helpers.py -v`

Expected: all tests PASS, including the three new ones.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard_routes/_cost_rollups.py tests/test_cost_rollups_helpers.py
git commit -m "feat(cost): add model_breakdown to build_per_loop_cost rows"
```

---

## Task 3: Backend — new `build_cost_by_model` aggregator

Cross-loop "where is the spend going by model" answer.

**Files:**
- Modify: `src/dashboard_routes/_cost_rollups.py` (append new function)
- Test: `tests/test_cost_rollups_by_model.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cost_rollups_by_model.py`:

```python
"""Tests for build_cost_by_model (cross-loop per-model aggregator)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dashboard_routes._cost_rollups import build_cost_by_model


def _write_inference(config, **fields) -> None:
    d = config.data_root / "metrics" / "prompt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "inferences.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = lambda *parts: tmp_path.joinpath(*parts)
    return cfg


def test_build_cost_by_model_returns_one_row_per_model_sorted_descending(
    config,
) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=100_000,
        output_tokens=20_000,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-haiku-4-5-20251001",
        input_tokens=100_000,
        output_tokens=20_000,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-sonnet-4-6",
        input_tokens=10_000,
        output_tokens=2_000,
    )

    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert [r["model"] for r in rows] == [
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    ]
    for row in rows:
        assert row["calls"] == 1
        assert row["cost_usd"] > 0
        assert "input_tokens" in row
        assert "output_tokens" in row
        assert "cache_read_tokens" in row
        assert "cache_write_tokens" in row


def test_build_cost_by_model_returns_empty_list_for_no_data(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)
    assert rows == []


def test_build_cost_by_model_respects_window(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=1_000,
        output_tokens=100,
    )
    _write_inference(
        config,
        timestamp=(now - timedelta(days=8)).isoformat(),
        source="implementer",
        model="claude-sonnet-4-6",
        input_tokens=1_000,
        output_tokens=100,
    )

    rows = build_cost_by_model(config, since=now - timedelta(days=7), until=now)

    assert [r["model"] for r in rows] == ["claude-opus-4-7"]


def test_build_cost_by_model_handles_unpriced_model(config) -> None:
    """Unknown model: cost is 0, tokens still summed."""
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="claude-future-99",
        input_tokens=5_000,
        output_tokens=500,
    )

    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert len(rows) == 1
    assert rows[0]["model"] == "claude-future-99"
    assert rows[0]["cost_usd"] == 0.0
    assert rows[0]["input_tokens"] == 5_000
    assert rows[0]["output_tokens"] == 500


def test_build_cost_by_model_buckets_missing_model_as_unknown(config) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    _write_inference(
        config,
        timestamp=(now - timedelta(hours=1)).isoformat(),
        source="implementer",
        model="",
        input_tokens=100,
        output_tokens=50,
    )

    rows = build_cost_by_model(config, since=now - timedelta(hours=24), until=now)

    assert [r["model"] for r in rows] == ["unknown"]
    assert rows[0]["calls"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cost_rollups_by_model.py -v`

Expected: 5 FAIL with `ImportError: cannot import name 'build_cost_by_model'`.

- [ ] **Step 3: Implement `build_cost_by_model`**

Append to `src/dashboard_routes/_cost_rollups.py` after `build_per_loop_cost` (after line 467):

```python


def build_cost_by_model(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
    pricing: ModelPricingTable | None = None,
) -> list[dict[str, Any]]:
    """Return cross-loop cost broken out by model in ``[since, until)``.

    Each row: ``{model, cost_usd, calls, input_tokens, output_tokens,
    cache_read_tokens, cache_write_tokens}``. Sorted descending by
    ``cost_usd``. Records with empty/missing ``model`` bucket under the
    literal string ``"unknown"``. Unpriced models surface their token
    counts with ``cost_usd == 0.0``.
    """
    pricing = pricing or load_pricing()

    by_model: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "cost_usd": 0.0,
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
    )

    for rec in iter_priced_inferences(config, since=since, until=until, pricing=pricing):
        model_key = str(rec.get("model") or "").strip() or "unknown"
        bucket = by_model[model_key]
        bucket["cost_usd"] = float(bucket["cost_usd"]) + float(
            rec.get("cost_usd", 0.0) or 0.0
        )
        bucket["calls"] = int(bucket["calls"]) + 1
        bucket["input_tokens"] = int(bucket["input_tokens"]) + int(
            rec.get("input_tokens", 0) or 0
        )
        bucket["output_tokens"] = int(bucket["output_tokens"]) + int(
            rec.get("output_tokens", 0) or 0
        )
        bucket["cache_read_tokens"] = int(bucket["cache_read_tokens"]) + int(
            rec.get("cache_read_input_tokens", 0) or 0
        )
        bucket["cache_write_tokens"] = int(bucket["cache_write_tokens"]) + int(
            rec.get("cache_creation_input_tokens", 0) or 0
        )

    rows = [
        {
            "model": model,
            "cost_usd": round(float(b["cost_usd"]), 6),
            "calls": int(b["calls"]),
            "input_tokens": int(b["input_tokens"]),
            "output_tokens": int(b["output_tokens"]),
            "cache_read_tokens": int(b["cache_read_tokens"]),
            "cache_write_tokens": int(b["cache_write_tokens"]),
        }
        for model, b in by_model.items()
    ]
    rows.sort(key=lambda r: r["cost_usd"], reverse=True)
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cost_rollups_by_model.py -v`

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard_routes/_cost_rollups.py tests/test_cost_rollups_by_model.py
git commit -m "feat(cost): add build_cost_by_model cross-loop aggregator"
```

---

## Task 4: Backend — `/api/diagnostics/cost/by-model` endpoint

**Files:**
- Modify: `src/dashboard_routes/_diagnostics_routes.py:27` (import) and `:344-352` (route block)
- Test: `tests/test_diagnostics_cost_rollup_routes.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_diagnostics_cost_rollup_routes.py`:

```python
# ---------------------------------------------------------------------------
# /api/diagnostics/cost/by-model
# ---------------------------------------------------------------------------


def test_cost_by_model_endpoint_returns_rows_sorted_by_cost(
    client, config, monkeypatch
) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    monkeypatch.setattr("dashboard_routes._cost_rollups._utcnow", lambda: now)
    _write_inference(
        config,
        timestamp="2026-04-22T11:00:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-opus-4-7",
        issue_number=1,
        input_tokens=10_000,
        output_tokens=2_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    _write_inference(
        config,
        timestamp="2026-04-22T11:01:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-haiku-4-5-20251001",
        issue_number=1,
        input_tokens=10_000,
        output_tokens=2_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )

    resp = client.get("/api/diagnostics/cost/by-model?range=24h")

    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert [r["model"] for r in rows][0] == "claude-opus-4-7"  # opus first (more $)
    for row in rows:
        for k in ("cost_usd", "calls", "input_tokens", "output_tokens"):
            assert k in row


def test_cost_by_model_endpoint_rejects_invalid_range(client) -> None:
    resp = client.get("/api/diagnostics/cost/by-model?range=99y")
    assert resp.status_code == 400


def test_cost_by_model_endpoint_returns_empty_list_for_no_data(
    client, monkeypatch
) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    monkeypatch.setattr("dashboard_routes._cost_rollups._utcnow", lambda: now)
    resp = client.get("/api/diagnostics/cost/by-model?range=24h")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_diagnostics_cost_rollup_routes.py::test_cost_by_model_endpoint_returns_rows_sorted_by_cost tests/test_diagnostics_cost_rollup_routes.py::test_cost_by_model_endpoint_rejects_invalid_range tests/test_diagnostics_cost_rollup_routes.py::test_cost_by_model_endpoint_returns_empty_list_for_no_data -v`

Expected: 3 FAIL with `404 Not Found` (route doesn't exist).

- [ ] **Step 3: Add the route**

In `src/dashboard_routes/_diagnostics_routes.py`, update the import block (around line 25–30):

```python
from dashboard_routes._cost_rollups import (
    build_by_loop,
    build_cost_by_model,
    build_per_loop_cost,
    build_rolling_24h,
    build_top_issues,
    iter_priced_inferences_for_issue,
)
```

(Keep alphabetical order; add `build_cost_by_model` between `build_by_loop` and `build_per_loop_cost`.)

Insert a new route after the `/cost/by-loop` route (after line 352, before `/loops/cost`):

```python
    @router.get("/cost/by-model")
    def cost_by_model_route(range: str = Query("7d")) -> list[dict[str, Any]]:
        """Cross-loop spend broken out by model over the range."""
        try:
            window = _parse_range(range)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = datetime.now(UTC)
        return build_cost_by_model(config, since=now - window, until=now)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_diagnostics_cost_rollup_routes.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard_routes/_diagnostics_routes.py tests/test_diagnostics_cost_rollup_routes.py
git commit -m "feat(api): add /api/diagnostics/cost/by-model endpoint"
```

---

## Task 5: Frontend — `PerLoopCostTable` expand-on-click

**Files:**
- Modify: `src/ui/src/components/diagnostics/PerLoopCostTable.jsx`
- Test: `src/ui/src/components/diagnostics/__tests__/PerLoopCostTable.test.jsx`

- [ ] **Step 1: Write the failing tests**

Append to `src/ui/src/components/diagnostics/__tests__/PerLoopCostTable.test.jsx`:

```jsx
import { fireEvent } from '@testing-library/react'

describe('PerLoopCostTable model_breakdown expansion', () => {
  const rowsWithBreakdown = [
    {
      loop: 'implementer',
      cost_usd: 1.5,
      llm_calls: 10,
      ticks: 2,
      tick_cost_avg_usd: 0.75,
      tick_cost_avg_usd_prev_period: 0.5,
      wall_clock_seconds: 60,
      sparkline_points: [],
      model_breakdown: {
        'claude-opus-4-7': {
          cost_usd: 1.4,
          calls: 7,
          input_tokens: 50000,
          output_tokens: 5000,
          cache_read_tokens: 100000,
          cache_write_tokens: 0,
        },
        'claude-haiku-4-5-20251001': {
          cost_usd: 0.1,
          calls: 3,
          input_tokens: 20000,
          output_tokens: 1000,
          cache_read_tokens: 0,
          cache_write_tokens: 0,
        },
      },
    },
  ]

  it('does not show the model sub-table by default', () => {
    render(<PerLoopCostTable rows={rowsWithBreakdown} />)
    expect(screen.queryByText('claude-opus-4-7')).not.toBeInTheDocument()
  })

  it('shows the per-model sub-table when the loop cell is clicked', () => {
    render(<PerLoopCostTable rows={rowsWithBreakdown} />)
    fireEvent.click(screen.getByTestId('expand-toggle-implementer'))
    expect(screen.getByText('claude-opus-4-7')).toBeInTheDocument()
    expect(screen.getByText('claude-haiku-4-5-20251001')).toBeInTheDocument()
  })

  it('shows percent share of loop cost per model', () => {
    render(<PerLoopCostTable rows={rowsWithBreakdown} />)
    fireEvent.click(screen.getByTestId('expand-toggle-implementer'))
    // 1.4 / 1.5 ≈ 93.3%
    expect(screen.getByText(/93\.3%/)).toBeInTheDocument()
    // 0.1 / 1.5 ≈ 6.7%
    expect(screen.getByText(/6\.7%/)).toBeInTheDocument()
  })

  it('omits the expand control when model_breakdown is absent (backward compat)', () => {
    const legacyRow = { ...rowsWithBreakdown[0] }
    delete legacyRow.model_breakdown
    render(<PerLoopCostTable rows={[legacyRow]} />)
    expect(screen.queryByTestId('expand-toggle-implementer')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/ui && npx vitest run src/components/diagnostics/__tests__/PerLoopCostTable.test.jsx`

Expected: 4 new FAIL.

- [ ] **Step 3: Implement expand-on-click**

In `src/ui/src/components/diagnostics/PerLoopCostTable.jsx`:

(a) Below the `Sparkline` component (before `export function PerLoopCostTable`), add a sub-table component:

```jsx
function ModelBreakdownSubTable({ breakdown, totalCost }) {
  const entries = Object.entries(breakdown || {})
  if (entries.length === 0) return null
  const sorted = [...entries].sort(
    (a, b) => Number(b[1].cost_usd || 0) - Number(a[1].cost_usd || 0),
  )
  const total = Number(totalCost) || 0
  return (
    <table style={styles.subTable}>
      <thead>
        <tr>
          <th style={styles.subTh}>Model</th>
          <th style={{ ...styles.subTh, ...styles.subThRight }}>Cost</th>
          <th style={{ ...styles.subTh, ...styles.subThRight }}>%</th>
          <th style={{ ...styles.subTh, ...styles.subThRight }}>Calls</th>
          <th style={{ ...styles.subTh, ...styles.subThRight }}>In</th>
          <th style={{ ...styles.subTh, ...styles.subThRight }}>Out</th>
          <th style={{ ...styles.subTh, ...styles.subThRight }}>Cache R</th>
          <th style={{ ...styles.subTh, ...styles.subThRight }}>Cache W</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map(([model, b]) => {
          const cost = Number(b.cost_usd || 0)
          const pct = total > 0 ? (cost / total) * 100 : 0
          return (
            <tr key={model} data-testid={`model-row-${model}`}>
              <td style={styles.subTd}>{model}</td>
              <td style={{ ...styles.subTd, ...styles.subTdRight }}>
                ${cost.toFixed(4)}
              </td>
              <td style={{ ...styles.subTd, ...styles.subTdRight }}>
                {pct.toFixed(1)}%
              </td>
              <td style={{ ...styles.subTd, ...styles.subTdRight }}>
                {Number(b.calls || 0).toLocaleString()}
              </td>
              <td style={{ ...styles.subTd, ...styles.subTdRight }}>
                {Number(b.input_tokens || 0).toLocaleString()}
              </td>
              <td style={{ ...styles.subTd, ...styles.subTdRight }}>
                {Number(b.output_tokens || 0).toLocaleString()}
              </td>
              <td style={{ ...styles.subTd, ...styles.subTdRight }}>
                {Number(b.cache_read_tokens || 0).toLocaleString()}
              </td>
              <td style={{ ...styles.subTd, ...styles.subTdRight }}>
                {Number(b.cache_write_tokens || 0).toLocaleString()}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
```

(b) In the main `PerLoopCostTable` function, add expansion state above the `useMemo`:

```jsx
  const [expanded, setExpanded] = useState({})

  const toggleExpand = (loop) => {
    setExpanded((prev) => ({ ...prev, [loop]: !prev[loop] }))
  }
```

(c) Replace the row rendering (the `{sorted.map((row) => { ... })}` block) with one that includes the expand toggle and sub-row. Keep the existing structure but wrap each iteration in a fragment that emits the data row + an optional sub-row:

```jsx
        <tbody>
          {sorted.map((row) => {
            const spike = isSpike(row)
            const hasBreakdown = row.model_breakdown
              && typeof row.model_breakdown === 'object'
              && Object.keys(row.model_breakdown).length > 0
            const isExpanded = !!expanded[row.loop]
            return (
              <React.Fragment key={row.loop}>
                <tr
                  data-testid="per-loop-row"
                  data-loop={row.loop}
                  data-spike={String(spike)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  style={{
                    ...styles.tr,
                    ...(spike ? styles.trSpike : {}),
                    ...(onRowClick ? styles.trClickable : {}),
                  }}
                >
                  {COLUMNS.map((c, i) => {
                    const isFirst = i === 0
                    return (
                      <td
                        key={c.key}
                        style={{
                          ...styles.td,
                          ...(c.numeric ? styles.tdRight : {}),
                          ...(spike && c.key === 'tick_cost_avg_usd'
                            ? styles.tdSpike
                            : {}),
                        }}
                      >
                        {isFirst && hasBreakdown ? (
                          <button
                            type="button"
                            data-testid={`expand-toggle-${row.loop}`}
                            onClick={(ev) => {
                              ev.stopPropagation()
                              toggleExpand(row.loop)
                            }}
                            style={styles.expandBtn}
                            aria-label={isExpanded ? 'Collapse' : 'Expand'}
                          >
                            {isExpanded ? '▾' : '▸'} {fmtCell(row[c.key], c)}
                          </button>
                        ) : (
                          fmtCell(row[c.key], c)
                        )}
                      </td>
                    )
                  })}
                  <td style={styles.td}>
                    <Sparkline points={row.sparkline_points} name={row.loop} />
                  </td>
                </tr>
                {isExpanded && hasBreakdown ? (
                  <tr data-testid={`model-subrow-${row.loop}`}>
                    <td colSpan={COLUMNS.length + 1} style={styles.subTdContainer}>
                      <ModelBreakdownSubTable
                        breakdown={row.model_breakdown}
                        totalCost={row.cost_usd}
                      />
                    </td>
                  </tr>
                ) : null}
              </React.Fragment>
            )
          })}
        </tbody>
```

(d) Append to the `styles` object:

```jsx
  expandBtn: {
    background: 'transparent',
    border: 'none',
    color: theme.text,
    cursor: 'pointer',
    padding: 0,
    fontSize: 12,
    fontFamily: 'inherit',
    textAlign: 'left',
  },
  subTdContainer: {
    padding: '0 8px 12px 24px',
    background: theme.surfaceInset,
    borderBottom: `1px solid ${theme.border}`,
  },
  subTable: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 11,
  },
  subTh: {
    textAlign: 'left',
    padding: '4px 8px',
    color: theme.textMuted,
    fontSize: 10,
    fontWeight: 500,
    borderBottom: `1px solid ${theme.border}`,
  },
  subThRight: {
    textAlign: 'right',
  },
  subTd: {
    padding: '4px 8px',
    color: theme.text,
  },
  subTdRight: {
    textAlign: 'right',
    fontFamily: 'monospace',
  },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/ui && npx vitest run src/components/diagnostics/__tests__/PerLoopCostTable.test.jsx`

Expected: all tests (existing + 4 new) PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ui/src/components/diagnostics/PerLoopCostTable.jsx src/ui/src/components/diagnostics/__tests__/PerLoopCostTable.test.jsx
git commit -m "feat(ui): expand-on-click model breakdown rows in PerLoopCostTable"
```

---

## Task 6: Frontend — `CostByModelChart` component

**Files:**
- Create: `src/ui/src/components/diagnostics/CostByModelChart.jsx`
- Test: `src/ui/src/components/diagnostics/__tests__/CostByModelChart.test.jsx`

- [ ] **Step 1: Write the failing tests**

Create `src/ui/src/components/diagnostics/__tests__/CostByModelChart.test.jsx`:

```jsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { CostByModelChart } from '../CostByModelChart'

describe('CostByModelChart', () => {
  const rows = [
    {
      model: 'claude-opus-4-7',
      cost_usd: 12.5,
      calls: 100,
      input_tokens: 800_000,
      output_tokens: 50_000,
      cache_read_tokens: 1_500_000,
      cache_write_tokens: 10_000,
    },
    {
      model: 'claude-sonnet-4-6',
      cost_usd: 2.5,
      calls: 60,
      input_tokens: 400_000,
      output_tokens: 30_000,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
    },
    {
      model: 'claude-haiku-4-5-20251001',
      cost_usd: 0.5,
      calls: 200,
      input_tokens: 1_000_000,
      output_tokens: 80_000,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
    },
  ]

  it('renders a segment per model', () => {
    render(<CostByModelChart rows={rows} />)
    expect(screen.getByTestId('seg-claude-opus-4-7')).toBeInTheDocument()
    expect(screen.getByTestId('seg-claude-sonnet-4-6')).toBeInTheDocument()
    expect(screen.getByTestId('seg-claude-haiku-4-5-20251001')).toBeInTheDocument()
  })

  it('defaults unit to dollars', () => {
    render(<CostByModelChart rows={rows} />)
    expect(screen.getByTestId('cost-by-model-unit')).toHaveTextContent('$')
  })

  it('switches units when a unit button is clicked', () => {
    render(<CostByModelChart rows={rows} />)
    fireEvent.click(screen.getByRole('button', { name: 'Calls' }))
    expect(screen.getByTestId('cost-by-model-unit')).toHaveTextContent('Calls')
    fireEvent.click(screen.getByRole('button', { name: 'Input tokens' }))
    expect(screen.getByTestId('cost-by-model-unit')).toHaveTextContent('Input tokens')
  })

  it('renders empty placeholder when no rows', () => {
    render(<CostByModelChart rows={[]} />)
    expect(screen.getByText(/no model spend data/i)).toBeInTheDocument()
  })

  it('renders empty placeholder when rows is null', () => {
    render(<CostByModelChart rows={null} />)
    expect(screen.getByText(/no model spend data/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/ui && npx vitest run src/components/diagnostics/__tests__/CostByModelChart.test.jsx`

Expected: FAIL — `Cannot find module '../CostByModelChart'`.

- [ ] **Step 3: Implement the chart**

Create `src/ui/src/components/diagnostics/CostByModelChart.jsx`:

```jsx
import React, { useMemo, useState } from 'react'
import { theme } from '../../theme'

/**
 * Cost-by-model horizontal stacked bar (gap #9 — observability).
 *
 * Consumes rows from `/api/diagnostics/cost/by-model?range=<r>`. Toggles
 * between unit views ($, calls, input tokens, output tokens). Empty data
 * renders a placeholder; the parent owns the range selector.
 */

const UNITS = [
  { key: 'cost_usd', label: '$', tooltipFmt: (v) => `$${Number(v).toFixed(4)}` },
  {
    key: 'calls',
    label: 'Calls',
    tooltipFmt: (v) => Number(v).toLocaleString(),
  },
  {
    key: 'input_tokens',
    label: 'Input tokens',
    tooltipFmt: (v) => Number(v).toLocaleString(),
  },
  {
    key: 'output_tokens',
    label: 'Output tokens',
    tooltipFmt: (v) => Number(v).toLocaleString(),
  },
]

const PALETTE = [
  theme.accent,
  '#a78bfa',
  '#34d399',
  '#fbbf24',
  '#f87171',
  '#60a5fa',
  '#fb923c',
  '#c084fc',
]

function colorFor(idx) {
  return PALETTE[idx % PALETTE.length]
}

export function CostByModelChart({ rows }) {
  const [unitKey, setUnitKey] = useState('cost_usd')
  const unit = UNITS.find((u) => u.key === unitKey) || UNITS[0]

  const segments = useMemo(() => {
    if (!Array.isArray(rows) || rows.length === 0) return []
    const total = rows.reduce((acc, r) => acc + (Number(r[unitKey]) || 0), 0)
    if (total <= 0) return []
    return rows.map((r, i) => {
      const value = Number(r[unitKey]) || 0
      return {
        model: r.model,
        value,
        share: value / total,
        color: colorFor(i),
      }
    })
  }, [rows, unitKey])

  if (!Array.isArray(rows) || rows.length === 0) {
    return (
      <div style={styles.empty}>No model spend data in range</div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span data-testid="cost-by-model-unit" style={styles.unitLabel}>
          {unit.label}
        </span>
        <div style={styles.unitButtons}>
          {UNITS.map((u) => (
            <button
              key={u.key}
              type="button"
              onClick={() => setUnitKey(u.key)}
              style={{
                ...styles.unitBtn,
                ...(u.key === unitKey ? styles.unitBtnActive : {}),
              }}
            >
              {u.label}
            </button>
          ))}
        </div>
      </div>

      <div style={styles.bar} role="img" aria-label="Spend share by model">
        {segments.map((s) => (
          <div
            key={s.model}
            data-testid={`seg-${s.model}`}
            title={`${s.model}: ${unit.tooltipFmt(s.value)} (${(s.share * 100).toFixed(1)}%)`}
            style={{
              ...styles.segment,
              width: `${(s.share * 100).toFixed(2)}%`,
              background: s.color,
            }}
          />
        ))}
      </div>

      <ul style={styles.legend}>
        {segments.map((s) => (
          <li key={s.model} style={styles.legendItem}>
            <span
              style={{ ...styles.legendSwatch, background: s.color }}
              aria-hidden="true"
            />
            <span style={styles.legendModel}>{s.model}</span>
            <span style={styles.legendValue}>
              {unit.tooltipFmt(s.value)} · {(s.share * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    background: theme.surfaceInset,
    borderRadius: 8,
    padding: 16,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  unitLabel: {
    fontSize: 11,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  unitButtons: {
    display: 'flex',
    gap: 4,
  },
  unitBtn: {
    background: 'transparent',
    border: `1px solid ${theme.border}`,
    color: theme.textMuted,
    fontSize: 11,
    padding: '2px 8px',
    borderRadius: 4,
    cursor: 'pointer',
  },
  unitBtnActive: {
    background: theme.accentSubtle,
    color: theme.textBright,
    borderColor: theme.accent,
  },
  bar: {
    display: 'flex',
    width: '100%',
    height: 24,
    borderRadius: 4,
    overflow: 'hidden',
    background: theme.border,
  },
  segment: {
    height: '100%',
  },
  legend: {
    listStyle: 'none',
    padding: 0,
    margin: 0,
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
    gap: 4,
    fontSize: 11,
  },
  legendItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  legendSwatch: {
    width: 10,
    height: 10,
    borderRadius: 2,
    flexShrink: 0,
  },
  legendModel: {
    color: theme.text,
    fontFamily: 'monospace',
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  legendValue: {
    color: theme.textMuted,
    fontFamily: 'monospace',
  },
  empty: {
    padding: 40,
    textAlign: 'center',
    color: theme.textMuted,
    fontSize: 11,
    background: theme.surfaceInset,
    borderRadius: 8,
  },
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/ui && npx vitest run src/components/diagnostics/__tests__/CostByModelChart.test.jsx`

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ui/src/components/diagnostics/CostByModelChart.jsx src/ui/src/components/diagnostics/__tests__/CostByModelChart.test.jsx
git commit -m "feat(ui): add CostByModelChart cross-loop spend bar"
```

---

## Task 7: Frontend — wire `CostByModelChart` into `FactoryCostTab`

**Files:**
- Modify: `src/ui/src/components/diagnostics/FactoryCostTab.jsx`

- [ ] **Step 1: Add fetch + render of the new chart**

Edit `src/ui/src/components/diagnostics/FactoryCostTab.jsx`:

(a) Add the import below the existing diagnostics imports (line 5):

```jsx
import { CostByModelChart } from './CostByModelChart'
```

(b) Add a new state hook in the body (after line 24's `loopsCost` state):

```jsx
  const [costByModel, setCostByModel] = useState([])
```

(c) Add a fourth promise to the `Promise.allSettled` (line 33), and a fourth result handler:

```jsx
    Promise.allSettled([
      fetch('/api/diagnostics/cost/rolling-24h').then((r) => r.json()),
      fetch(`/api/diagnostics/cost/top-issues${q}&limit=10`).then((r) => r.json()),
      fetch(`/api/diagnostics/loops/cost${q}`).then((r) => r.json()),
      fetch(`/api/diagnostics/cost/by-model${q}`).then((r) => r.json()),
    ]).then((results) => {
      if (cancelled) return
      const [rolling, top, loops, byModel] = results
      if (rolling.status === 'fulfilled') {
        setRolling24h(rolling.value)
        setRollingError(null)
      } else {
        setRolling24h(null)
        setRollingError(rolling.reason)
      }
      setTopIssues(
        top.status === 'fulfilled' && Array.isArray(top.value) ? top.value : [],
      )
      setLoopsCost(
        loops.status === 'fulfilled' && Array.isArray(loops.value) ? loops.value : [],
      )
      setCostByModel(
        byModel.status === 'fulfilled' && Array.isArray(byModel.value) ? byModel.value : [],
      )
    })
```

(d) Slot the new chart between the `FactoryCostSummary` and the `Per-Loop Cost` section (around line 96):

```jsx
      <FactoryCostSummary rolling24h={rolling24h} error={rollingError} />

      <section style={styles.section}>
        <h3 style={styles.h3}>Cost by Model ({range})</h3>
        <CostByModelChart rows={costByModel} />
      </section>

      <section style={styles.section}>
        <h3 style={styles.h3}>Per-Loop Cost ({range})</h3>
        <PerLoopCostTable rows={loopsCost} />
      </section>
```

- [ ] **Step 2: Verify existing FactoryCostTab tests still pass**

Run: `cd src/ui && npx vitest run src/components/diagnostics/__tests__/`

Expected: all pass. If `DiagnosticsTab.test.jsx` mocks `fetch`, it may need the new endpoint; let it fail in this step and update the mock in the next step if so.

- [ ] **Step 3: If a sibling test mock breaks, update it**

Search for any sibling test that mocks `/api/diagnostics/cost/`:

```bash
grep -rn "diagnostics/cost\|loops/cost" src/ui/src/components/diagnostics/__tests__/ src/ui/src/test/
```

For any mock that intercepts these endpoints, add an entry for `/api/diagnostics/cost/by-model` returning `[]` so existing tests don't break.

If the existing mocks already handle all `/api/diagnostics/cost/*` with a wildcard / passthrough, this step is a no-op.

- [ ] **Step 4: Commit**

```bash
git add src/ui/src/components/diagnostics/FactoryCostTab.jsx
# plus any sibling test mock updates if Step 3 modified them
git commit -m "feat(ui): wire CostByModelChart into FactoryCostTab"
```

---

## Task 8: Backward-compat regression test

Cover the spec's "additive guarantee" — existing API consumers see existing fields unchanged.

**Files:**
- Test: `tests/regressions/test_loops_cost_endpoint_additive.py` (new file)

- [ ] **Step 1: Write the regression test**

Create `tests/regressions/test_loops_cost_endpoint_additive.py`:

```python
"""Regression: /api/diagnostics/loops/cost keeps its existing field set.

Adding model_breakdown is additive — older clients that destructure
specific fields must continue to find them. Locks the row schema.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._diagnostics_routes import build_diagnostics_router


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = lambda *parts: tmp_path.joinpath(*parts)
    cfg.factory_metrics_path = tmp_path / "diagnostics" / "factory_metrics.jsonl"
    cfg.repo = "o/r"
    return cfg


@pytest.fixture
def client(config) -> TestClient:
    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    return TestClient(app)


def _write_inference(config, **fields) -> None:
    d = config.data_root / "metrics" / "prompt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "inferences.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_loop_trace(config, loop, **fields) -> None:
    from trace_collector import _slug_for_loop  # noqa: PLC0415

    d = config.data_root / "traces" / "_loops" / _slug_for_loop(loop)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "loop", "loop": loop, **fields}
    (d / f"run-{fields['started_at'].replace(':', '')}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_loops_cost_row_keeps_pre_breakdown_fields(client, config) -> None:
    """All previously-shipped fields still present alongside model_breakdown."""
    _write_inference(
        config,
        timestamp="2026-04-22T11:00:00+00:00",
        source="implementer",
        model="claude-sonnet-4-6",
        issue_number=1,
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    _write_loop_trace(
        config,
        "ImplementerLoop",
        started_at="2026-04-22T11:00:00+00:00",
        duration_ms=60_000,
        command=["x"],
        exit_code=0,
    )

    resp = client.get("/api/diagnostics/loops/cost?range=24h")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "expected at least one loop row"
    row = rows[0]

    pre_breakdown_fields = {
        "loop", "cost_usd", "tokens_in", "tokens_out", "llm_calls",
        "issues_filed", "issues_closed", "escalations", "ticks",
        "ticks_errored", "tick_cost_avg_usd", "wall_clock_seconds",
        "last_tick_at", "tick_cost_avg_usd_prev_period",
    }
    missing = pre_breakdown_fields - set(row.keys())
    assert not missing, f"endpoint dropped pre-existing fields: {missing}"
    assert "model_breakdown" in row
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/regressions/test_loops_cost_endpoint_additive.py -v`

Expected: PASS (Tasks 2–4 already wired this; this just locks the contract).

- [ ] **Step 3: Commit**

```bash
git add tests/regressions/test_loops_cost_endpoint_additive.py
git commit -m "test(regression): lock /loops/cost field set as additive only"
```

---

## Task 9: Final quality gate

**Files:**
- None (verification step only)

- [ ] **Step 1: Run `make quality`**

Run: `make quality`

Expected: lint OK, typecheck OK, security OK, tests OK. If any step fails, fix the offender and re-run; do not skip.

- [ ] **Step 2: Run UI tests in isolation (belt and braces)**

Run: `cd src/ui && npm test -- --run`

Expected: all UI tests pass.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Run: `make dashboard` (or however the dev dashboard is started; check `Makefile`).

Open the Factory Cost tab in the browser. Verify:
- "Cost by Model" chart renders above the per-loop table
- Unit toggle ($ / Calls / Input tokens / Output tokens) works
- Clicking a loop row reveals the per-model sub-table
- Sub-table shows percent share

If `make dashboard` is not the right target, find the right one (`grep -E "^[a-z-]+:" Makefile | head -20`) and use that.

- [ ] **Step 4: No commit** — this task is verification only.

---

## Self-review

**Spec coverage:**

| Spec section | Implementing task |
|---|---|
| §2 Architecture (extend `build_per_loop_cost`) | Task 2 |
| §2 Architecture (`build_cost_by_model`) | Task 3 |
| §2 Endpoints (additive `/loops/cost`) | Task 2 + regression Task 8 |
| §2 Endpoints (`/cost/by-model`) | Task 4 |
| §2 Frontend (`PerLoopCostTable` expand) | Task 5 |
| §2 Frontend (`CostByModelChart`) | Task 6 |
| §2 Frontend (`FactoryCostTab` slot) | Task 7 |
| §4 Backend types | Task 2, 3 (inline dicts; no Pydantic per spec) |
| §5 Error handling — missing `model` → "unknown" | Task 2 (test), Task 3 (test) |
| §5 Error handling — unpriced model | Task 3 (test) |
| §5 Asyncio nested-loop guard | Existing code (Task 2 doesn't modify) |
| §6 Backend tests | Tasks 2, 3, 4 |
| §6 Frontend tests | Tasks 5, 6 |
| §7 Migration / rollout | No data migration; covered by regression Task 8 |
| §8 Risks (pricing currency) | Task 1 (precursor) |
| §9 Definition of done | Task 9 (quality gate) |

No gaps.

**Type consistency check:**

- `model_breakdown` keys: `{cost_usd, calls, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens}` — used identically in Tasks 2, 5.
- `build_cost_by_model` row keys: `{model, cost_usd, calls, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens}` — used identically in Tasks 3, 4, 6.
- "unknown" bucket label spelled exactly the same in Tasks 2, 3.
- Endpoint path `/api/diagnostics/cost/by-model` consistent across Tasks 4, 7.
- Test ID `expand-toggle-${row.loop}` matches between Task 5 implementation and tests.
- Test ID `seg-${model}` matches between Task 6 implementation and tests.

**Placeholder scan:** none found.
