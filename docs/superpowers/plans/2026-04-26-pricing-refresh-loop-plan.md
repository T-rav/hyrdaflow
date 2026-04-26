# PricingRefreshLoop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily caretaker loop that detects drift between `src/assets/model_pricing.json` and LiteLLM's structured upstream pricing JSON, opening a PR with the proposed update for human review.

**Architecture:** New `PricingRefreshLoop` (subclass of `BaseBackgroundLoop`, mirrors L24 DiagramLoop pattern). Pure-function diff/normalize logic split into `pricing_refresh_diff.py` for test isolation. Network IO through stdlib `urllib.request`; PR opening via existing `auto_pr.open_automated_pr_async`. Diff-bounds guard rejects suspicious price moves. Five-checkpoint wiring in `service_registry.py` + `orchestrator.py`; catalog wiring for MockWorld scenarios.

**Tech Stack:** Python (stdlib `urllib.request` + `json`, FastAPI N/A here, pytest, MockWorld test harness).

**Spec:** `docs/superpowers/specs/2026-04-26-pricing-refresh-loop-design.md`

---

## File touchpoints

**Create:**
- `src/pricing_refresh_diff.py` — pure functions for parse/normalize/diff/bounds (no IO)
- `src/pricing_refresh_loop.py` — the `BaseBackgroundLoop` subclass
- `tests/test_pricing_refresh_diff.py` — unit tests on pure functions
- `tests/test_pricing_refresh_loop_scenario.py` — `_do_work` integration with mocked seams
- `tests/scenarios/test_pricing_refresh_loop_mockworld.py` — full `run_with_loops` scenarios
- `tests/fixtures/litellm_pricing_sample.json` — minimal LiteLLM-shaped JSON

**Modify:**
- `src/service_registry.py` — add field to `Services` dataclass + instantiate in factory
- `src/orchestrator.py` — register in `bg_loop_registry` + add to `loop_factories`
- `tests/orchestrator_integration_utils.py` — add `services.pricing_refresh_loop = FakeBackgroundLoop()`
- `tests/scenarios/catalog/loop_registrations.py` — add `_build_pricing_refresh_loop` to `_BUILDERS`

---

## Task 1: Pure normalize + filter functions

Pure functions that strip Bedrock prefixes/suffixes from LiteLLM keys and filter to anthropic-provider entries. Tested in isolation, no IO.

**Files:**
- Create: `src/pricing_refresh_diff.py`
- Test: `tests/test_pricing_refresh_diff.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pricing_refresh_diff.py`:

```python
"""Pure-function tests for pricing_refresh_diff module."""

from __future__ import annotations

from pricing_refresh_diff import (
    filter_anthropic_entries,
    normalize_litellm_key,
)


def test_normalize_strips_bedrock_prefix() -> None:
    assert (
        normalize_litellm_key("anthropic.claude-haiku-4-5-20251001-v1:0")
        == "claude-haiku-4-5-20251001"
    )


def test_normalize_strips_bedrock_at_suffix() -> None:
    assert (
        normalize_litellm_key("anthropic.claude-haiku-4-5@20251001")
        == "claude-haiku-4-5-20251001"
    )


def test_normalize_passthrough_canonical() -> None:
    assert normalize_litellm_key("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"


def test_normalize_strips_only_v1_zero() -> None:
    # Other v-suffixes preserved as-is — only v1:0 is the Bedrock convention.
    assert normalize_litellm_key("claude-future-v2:1") == "claude-future-v2:1"


def test_filter_keeps_only_anthropic_provider() -> None:
    raw = {
        "claude-haiku-4-5": {"litellm_provider": "anthropic", "input_cost_per_token": 1e-6},
        "gpt-4": {"litellm_provider": "openai", "input_cost_per_token": 1e-5},
        "anthropic.claude-3-haiku": {"litellm_provider": "anthropic", "input_cost_per_token": 1e-7},
    }
    out = filter_anthropic_entries(raw)
    assert set(out.keys()) == {"claude-haiku-4-5", "claude-3-haiku"}


def test_filter_skips_entries_without_provider_field() -> None:
    raw = {
        "claude-thing": {"litellm_provider": "anthropic", "input_cost_per_token": 1e-6},
        "missing-provider": {"input_cost_per_token": 1e-6},
    }
    out = filter_anthropic_entries(raw)
    assert set(out.keys()) == {"claude-thing"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pricing_refresh_diff.py -v`

Expected: 6 FAIL with `ModuleNotFoundError: No module named 'pricing_refresh_diff'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/pricing_refresh_diff.py`:

```python
"""Pure-function helpers for PricingRefreshLoop.

No IO, no logging, no external state. All functions deterministic and
trivially testable. Importing this module must not trigger any side
effects.
"""

from __future__ import annotations

from typing import Any

_BEDROCK_PREFIX = "anthropic."
_V1_ZERO_SUFFIX = "-v1:0"


def normalize_litellm_key(key: str) -> str:
    """Strip Bedrock-style prefixes/suffixes so a LiteLLM key matches our local naming.

    LiteLLM publishes both bare canonical keys (``claude-haiku-4-5-20251001``)
    and Bedrock-prefixed variants (``anthropic.claude-haiku-4-5-20251001-v1:0``,
    ``anthropic.claude-haiku-4-5@20251001``). All three normalize to the same
    canonical form.
    """
    out = key
    if out.startswith(_BEDROCK_PREFIX):
        out = out[len(_BEDROCK_PREFIX):]
    # The "@YYYYMMDD" convention is treated as "-YYYYMMDD" for our naming.
    out = out.replace("@", "-")
    if out.endswith(_V1_ZERO_SUFFIX):
        out = out[: -len(_V1_ZERO_SUFFIX)]
    return out


def filter_anthropic_entries(raw: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Keep only entries whose ``litellm_provider`` is ``"anthropic"``.

    Returns a NEW dict keyed by :func:`normalize_litellm_key` of the original.
    Entries without a ``litellm_provider`` field are skipped.
    """
    out: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("litellm_provider") != "anthropic":
            continue
        out[normalize_litellm_key(key)] = entry
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pricing_refresh_diff.py -v`

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pricing_refresh_diff.py tests/test_pricing_refresh_diff.py
git commit -m "feat(pricing): pure normalize+filter helpers for LiteLLM upstream"
```

---

## Task 2: Field mapping (LiteLLM → our shape)

Convert per-token costs to cost-per-million across the 4 fields we track. No IO, pure function.

**Files:**
- Modify: `src/pricing_refresh_diff.py` (append)
- Test: `tests/test_pricing_refresh_diff.py` (append)

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_pricing_refresh_diff.py`:

```python
import pytest

from pricing_refresh_diff import map_litellm_to_local_costs


def test_map_per_token_to_per_million() -> None:
    upstream = {
        "input_cost_per_token": 1e-6,           # 1.00 / M
        "output_cost_per_token": 5e-6,          # 5.00 / M
        "cache_creation_input_token_cost": 1.25e-6,  # 1.25 / M
        "cache_read_input_token_cost": 1e-7,    # 0.10 / M
    }
    out = map_litellm_to_local_costs(upstream)
    assert out == {
        "input_cost_per_million": 1.00,
        "output_cost_per_million": 5.00,
        "cache_write_cost_per_million": 1.25,
        "cache_read_cost_per_million": 0.10,
    }


def test_map_handles_missing_cache_fields_as_zero() -> None:
    """Some legacy entries lack cache fields entirely."""
    upstream = {
        "input_cost_per_token": 3e-6,
        "output_cost_per_token": 15e-6,
    }
    out = map_litellm_to_local_costs(upstream)
    assert out["cache_write_cost_per_million"] == 0.0
    assert out["cache_read_cost_per_million"] == 0.0
    assert out["input_cost_per_million"] == 3.00


def test_map_raises_on_missing_required_field() -> None:
    """input_cost_per_token and output_cost_per_token are required."""
    with pytest.raises(KeyError):
        map_litellm_to_local_costs({"output_cost_per_token": 1e-6})
    with pytest.raises(KeyError):
        map_litellm_to_local_costs({"input_cost_per_token": 1e-6})


def test_map_rounds_to_six_decimals() -> None:
    """Floating-point artifacts shouldn't leak into the JSON output."""
    upstream = {
        "input_cost_per_token": 1e-6 / 3,  # repeating decimal
        "output_cost_per_token": 5e-6,
    }
    out = map_litellm_to_local_costs(upstream)
    # 1e-6 / 3 * 1e6 = 0.333... rounded to 6 decimals = 0.333333
    assert out["input_cost_per_million"] == 0.333333
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pricing_refresh_diff.py::test_map_per_token_to_per_million -v`

Expected: FAIL with `ImportError: cannot import name 'map_litellm_to_local_costs'`.

- [ ] **Step 3: Append the implementation**

Append to `src/pricing_refresh_diff.py`:

```python
def map_litellm_to_local_costs(upstream: dict[str, Any]) -> dict[str, float]:
    """Map LiteLLM per-token costs to our per-million-tokens shape.

    Required upstream keys: ``input_cost_per_token``, ``output_cost_per_token``.
    Cache fields (``cache_creation_input_token_cost``, ``cache_read_input_token_cost``)
    default to 0 when absent. All output values rounded to 6 decimals.

    Raises:
        KeyError: a required field is missing.
    """
    return {
        "input_cost_per_million": round(float(upstream["input_cost_per_token"]) * 1e6, 6),
        "output_cost_per_million": round(float(upstream["output_cost_per_token"]) * 1e6, 6),
        "cache_write_cost_per_million": round(
            float(upstream.get("cache_creation_input_token_cost", 0.0)) * 1e6, 6
        ),
        "cache_read_cost_per_million": round(
            float(upstream.get("cache_read_input_token_cost", 0.0)) * 1e6, 6
        ),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pricing_refresh_diff.py -v`

Expected: 10 PASS (6 existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_refresh_diff.py tests/test_pricing_refresh_diff.py
git commit -m "feat(pricing): map LiteLLM per-token costs to per-million shape"
```

---

## Task 3: Diff + bounds guard

Compare a proposed pricing dict against the existing local pricing dict, emit per-model diffs, and reject any field that violates the bounds guard.

**Files:**
- Modify: `src/pricing_refresh_diff.py` (append)
- Test: `tests/test_pricing_refresh_diff.py` (append)

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_pricing_refresh_diff.py`:

```python
from pricing_refresh_diff import (
    BoundsViolation,
    PricingDiff,
    compute_pricing_diff,
)


def _local_entry(input_cost: float = 1.0, output_cost: float = 5.0) -> dict[str, Any]:
    return {
        "provider": "anthropic",
        "aliases": [],
        "input_cost_per_million": input_cost,
        "output_cost_per_million": output_cost,
        "cache_write_cost_per_million": 1.25,
        "cache_read_cost_per_million": 0.10,
    }


def _upstream_entry(
    input_cost_per_token: float = 1e-6,
    output_cost_per_token: float = 5e-6,
) -> dict[str, Any]:
    return {
        "litellm_provider": "anthropic",
        "input_cost_per_token": input_cost_per_token,
        "output_cost_per_token": output_cost_per_token,
        "cache_creation_input_token_cost": 1.25e-6,
        "cache_read_input_token_cost": 1e-7,
    }


def test_diff_no_changes_when_values_match() -> None:
    local = {"claude-x": _local_entry()}
    upstream = {"claude-x": _upstream_entry()}
    diff = compute_pricing_diff(local=local, upstream=upstream)
    assert diff.updated == {}
    assert diff.added == {}
    assert diff.bounds_violations == []


def test_diff_detects_value_change() -> None:
    local = {"claude-x": _local_entry(input_cost=1.0)}
    upstream = {"claude-x": _upstream_entry(input_cost_per_token=1.5e-6)}
    diff = compute_pricing_diff(local=local, upstream=upstream)
    assert "claude-x" in diff.updated
    assert diff.updated["claude-x"]["input_cost_per_million"] == 1.5


def test_diff_adds_upstream_only_model() -> None:
    local: dict[str, Any] = {}
    upstream = {"claude-new": _upstream_entry()}
    diff = compute_pricing_diff(local=local, upstream=upstream)
    assert "claude-new" in diff.added
    assert diff.added["claude-new"]["input_cost_per_million"] == 1.00
    assert diff.added["claude-new"]["provider"] == "anthropic"
    assert diff.added["claude-new"]["aliases"] == []


def test_diff_keeps_local_only_model_unchanged() -> None:
    local = {"claude-bleeding-edge": _local_entry()}
    upstream: dict[str, Any] = {}
    diff = compute_pricing_diff(local=local, upstream=upstream)
    assert diff.updated == {}
    assert diff.added == {}


def test_bounds_guard_rejects_doubling() -> None:
    """A field moving up by >100% (more than 2x) is rejected."""
    local = {"claude-x": _local_entry(input_cost=1.0)}
    upstream = {"claude-x": _upstream_entry(input_cost_per_token=2.5e-6)}  # 1.0 → 2.5 = +150%
    diff = compute_pricing_diff(local=local, upstream=upstream)
    assert diff.updated == {}  # rejected
    assert len(diff.bounds_violations) == 1
    bv = diff.bounds_violations[0]
    assert bv.model == "claude-x"
    assert bv.field == "input_cost_per_million"
    assert bv.old == 1.0
    assert bv.new == 2.5


def test_bounds_guard_rejects_halving() -> None:
    """A field moving down by >50% (less than 0.5x) is rejected."""
    local = {"claude-x": _local_entry(input_cost=1.0)}
    upstream = {"claude-x": _upstream_entry(input_cost_per_token=0.4e-6)}  # 1.0 → 0.4 = -60%
    diff = compute_pricing_diff(local=local, upstream=upstream)
    assert diff.updated == {}
    assert len(diff.bounds_violations) == 1


def test_bounds_guard_accepts_modest_change() -> None:
    """A 50% increase (within +100% bound) is applied."""
    local = {"claude-x": _local_entry(input_cost=1.0)}
    upstream = {"claude-x": _upstream_entry(input_cost_per_token=1.5e-6)}
    diff = compute_pricing_diff(local=local, upstream=upstream)
    assert diff.updated["claude-x"]["input_cost_per_million"] == 1.5
    assert diff.bounds_violations == []


def test_bounds_guard_zero_to_nonzero_not_treated_as_infinite_bounds_violation() -> None:
    """When old=0 (e.g., a previously-free cache field), any new value is allowed.

    The bounds guard divides by the old value; division-by-zero must not
    crash and must not falsely flag a legitimate first-time price.
    """
    local = {"claude-x": _local_entry()}
    local["claude-x"]["cache_write_cost_per_million"] = 0.0  # was free
    upstream = {"claude-x": _upstream_entry()}  # cache_write_cost = 1.25 / M
    diff = compute_pricing_diff(local=local, upstream=upstream)
    assert "claude-x" in diff.updated
    assert diff.updated["claude-x"]["cache_write_cost_per_million"] == 1.25
    assert diff.bounds_violations == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pricing_refresh_diff.py -v`

Expected: 8 new FAIL with `ImportError: cannot import name 'BoundsViolation' / 'PricingDiff' / 'compute_pricing_diff'`.

- [ ] **Step 3: Append the implementation**

Append to `src/pricing_refresh_diff.py`:

```python
from dataclasses import dataclass, field

_COST_FIELDS = (
    "input_cost_per_million",
    "output_cost_per_million",
    "cache_write_cost_per_million",
    "cache_read_cost_per_million",
)
_BOUNDS_UPPER = 2.0  # ≤ +100% allowed
_BOUNDS_LOWER = 0.5  # ≥ -50% allowed


@dataclass(frozen=True)
class BoundsViolation:
    """Single field rejected by the bounds guard."""

    model: str
    field: str
    old: float
    new: float

    @property
    def ratio(self) -> float:
        return self.new / self.old if self.old != 0 else float("inf")


@dataclass
class PricingDiff:
    """Result of comparing local pricing.json to mapped upstream entries.

    ``updated``: model → mapped-cost dict, only for models where every cost
    field passed the bounds guard.
    ``added``: model → fresh entry (with empty aliases) for upstream-only
    models. Bounds guard does not apply to additions.
    ``bounds_violations``: per (model, field) rejections — the entire
    update for a model is rejected if any of its fields violate.
    """

    updated: dict[str, dict[str, float]] = field(default_factory=dict)
    added: dict[str, dict[str, Any]] = field(default_factory=dict)
    bounds_violations: list[BoundsViolation] = field(default_factory=list)


def _within_bounds(old: float, new: float) -> bool:
    if old == 0:
        return True  # zero-baseline can move freely; no infinite-ratio paradox
    ratio = new / old
    return _BOUNDS_LOWER <= ratio <= _BOUNDS_UPPER


def compute_pricing_diff(
    *,
    local: dict[str, dict[str, Any]],
    upstream: dict[str, dict[str, Any]],
) -> PricingDiff:
    """Diff local pricing entries against mapped upstream values.

    ``upstream`` is the raw LiteLLM dict (already filtered to anthropic-
    provider entries via :func:`filter_anthropic_entries`); this function
    re-maps each upstream value via :func:`map_litellm_to_local_costs`.

    Local-only entries are preserved (return type doesn't list them; the
    caller merges added/updated against local).
    """
    diff = PricingDiff()
    for model, upstream_entry in upstream.items():
        try:
            mapped = map_litellm_to_local_costs(upstream_entry)
        except KeyError:
            continue  # skip upstream entries missing required fields

        local_entry = local.get(model)
        if local_entry is None:
            diff.added[model] = {
                "provider": "anthropic",
                "aliases": [],
                **mapped,
            }
            continue

        # All cost fields equal? → no change.
        changed_fields = {
            f: mapped[f] for f in _COST_FIELDS if mapped[f] != local_entry.get(f, 0.0)
        }
        if not changed_fields:
            continue

        # Bounds guard: reject the WHOLE update if any field violates.
        violations: list[BoundsViolation] = []
        for f, new in changed_fields.items():
            old = float(local_entry.get(f, 0.0))
            if not _within_bounds(old, new):
                violations.append(BoundsViolation(model=model, field=f, old=old, new=new))
        if violations:
            diff.bounds_violations.extend(violations)
            continue

        diff.updated[model] = changed_fields
    return diff
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pricing_refresh_diff.py -v`

Expected: 18 PASS (10 existing + 8 new).

- [ ] **Step 5: Commit**

```bash
git add src/pricing_refresh_diff.py tests/test_pricing_refresh_diff.py
git commit -m "feat(pricing): diff + bounds-guard logic for upstream pricing refresh"
```

---

## Task 4: PricingRefreshLoop class — happy path

The loop class itself: `_do_work` happy paths (no-drift, drift-detected). Failure paths and bounds-violation issue creation come in Task 5.

**Files:**
- Create: `src/pricing_refresh_loop.py`
- Test: `tests/test_pricing_refresh_loop_scenario.py`

- [ ] **Step 1: Write the failing test (no-drift path)**

Create `tests/test_pricing_refresh_loop_scenario.py`:

```python
"""PricingRefreshLoop _do_work tests with mocked seams."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pricing_refresh_loop import PricingRefreshLoop


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Worktree-style root with a populated model_pricing.json."""
    pricing_path = tmp_path / "src" / "assets" / "model_pricing.json"
    pricing_path.parent.mkdir(parents=True)
    pricing_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "currency": "USD",
                "updated_at": "2026-04-01",
                "source": "https://docs.anthropic.com/en/docs/about-claude/models",
                "models": {
                    "claude-haiku-4-5-20251001": {
                        "provider": "anthropic",
                        "aliases": ["haiku"],
                        "input_cost_per_million": 1.00,
                        "output_cost_per_million": 5.00,
                        "cache_write_cost_per_million": 1.25,
                        "cache_read_cost_per_million": 0.10,
                    },
                },
            },
            indent=2,
        )
        + "\n"
    )
    return tmp_path


def _build_loop(repo_root: Path) -> tuple[PricingRefreshLoop, AsyncMock]:
    pr_manager = AsyncMock(
        find_existing_issue=AsyncMock(return_value=0),
        create_issue=AsyncMock(return_value=0),
    )
    deps = MagicMock()
    config = MagicMock()
    loop = PricingRefreshLoop(config=config, pr_manager=pr_manager, deps=deps)
    loop._set_repo_root(repo_root)
    return loop, pr_manager


async def test_no_drift_returns_drift_false(repo_root: Path) -> None:
    """Upstream matches local exactly → no PR opened, no issue."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, pr_manager = _build_loop(repo_root)

    pr_helper = AsyncMock()
    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.open_automated_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result == {"drift": False}
    pr_helper.assert_not_awaited()
    pr_manager.create_issue.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pricing_refresh_loop_scenario.py::test_no_drift_returns_drift_false -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'pricing_refresh_loop'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/pricing_refresh_loop.py`:

```python
"""PricingRefreshLoop — daily upstream-pricing refresh caretaker.

Per ADR-0029 (caretaker pattern), ADR-0049 (kill-switch convention),
and the design at docs/superpowers/specs/2026-04-26-pricing-refresh-loop-design.md.

Tick behavior:
  1. Fetch LiteLLM's model_prices_and_context_window.json (urllib stdlib, 30s).
  2. Filter to anthropic-provider entries; normalize Bedrock keys.
  3. Diff against src/assets/model_pricing.json. Bounds-guard rejects
     suspicious price moves.
  4. If no changes: log "no drift", return {drift: False}.
  5. Else: write proposed file, open/update PR via auto_pr.open_automated_pr_async
     on fixed branch `pricing-refresh-auto`.
  6. Bounds violations / parse errors / schema errors → open one
     `[pricing-refresh] ...` hydraflow-find issue (deduped by title prefix).
  7. Network errors → log + retry next tick (no issue spam).

Kill switch: HYDRAFLOW_DISABLE_PRICING_REFRESH=1.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import WorkCycleResult
from pricing_refresh_diff import (
    BoundsViolation,
    PricingDiff,
    compute_pricing_diff,
    filter_anthropic_entries,
)

logger = logging.getLogger(__name__)

_KILL_SWITCH_ENV = "HYDRAFLOW_DISABLE_PRICING_REFRESH"
_REGEN_BRANCH = "pricing-refresh-auto"
_PR_TITLE_PREFIX = "chore(pricing): refresh from LiteLLM"
_ISSUE_TITLE_PREFIX = "[pricing-refresh]"
_LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
_FETCH_TIMEOUT_S = 30


class PricingRefreshLoop(BaseBackgroundLoop):
    """Daily caretaker — keeps src/assets/model_pricing.json in sync with LiteLLM."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager,  # PRPort
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="pricing-refresh-loop",
            config=config,
            deps=deps,
        )
        self._pr_manager = pr_manager
        self._repo_root = Path.cwd()

    def _set_repo_root(self, path: Path) -> None:
        """Test seam: redirect the loop at a worktree without subclassing."""
        self._repo_root = Path(path)

    def _get_default_interval(self) -> int:
        # 24 hours — daily.
        return 86400

    async def _do_work(self) -> WorkCycleResult:
        # Kill-switch (ADR-0049). Belt and suspenders.
        if os.environ.get(_KILL_SWITCH_ENV) == "1":
            return {"skipped": "kill_switch"}

        try:
            upstream_raw = await self._fetch_upstream()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Network errors are silent — retry next tick, no issue spam.
            logger.warning("PricingRefreshLoop fetch failed: %s", exc)
            return {"drift": False, "error": "network"}
        except json.JSONDecodeError as exc:
            # Upstream returned non-JSON (or partial JSON). This is unusual
            # enough to deserve a dedup'd issue — not silent.
            logger.warning("PricingRefreshLoop upstream parse failed: %s", exc)
            await self._open_parse_issue(str(exc))
            return {"drift": False, "error": "parse"}

        upstream = filter_anthropic_entries(upstream_raw)
        local = self._read_local_models()

        diff = compute_pricing_diff(local=local, upstream=upstream)

        if diff.bounds_violations:
            await self._open_bounds_issue(diff.bounds_violations)
            return {
                "drift": False,
                "error": "bounds",
                "violations": len(diff.bounds_violations),
            }

        if not diff.updated and not diff.added:
            return {"drift": False}

        # Atomic write+PR: capture original bytes so we can revert if the
        # PR-opening step fails. Without this, a successful file write
        # followed by an auto_pr failure would leave the worktree mutated
        # but no PR open — next tick reads the mutation as "local", sees
        # no diff vs upstream, and never proposes the change again.
        pricing_path = self._repo_root / "src" / "assets" / "model_pricing.json"
        original_bytes = pricing_path.read_bytes()
        self._apply_diff_to_pricing_file(local, diff)

        try:
            pr_url = await self._open_or_update_refresh_pr(diff)
        except Exception:
            pricing_path.write_bytes(original_bytes)
            raise

        if pr_url is None:
            # auto_pr returned a non-success status (logged inside
            # _open_or_update_refresh_pr). Revert so the file is consistent
            # with what landed on the remote.
            pricing_path.write_bytes(original_bytes)
            return {
                "drift": True,
                "updated": len(diff.updated),
                "added": len(diff.added),
                "pr_url": None,
                "error": "pr_failed",
            }

        return {
            "drift": True,
            "updated": len(diff.updated),
            "added": len(diff.added),
            "pr_url": pr_url,
        }

    async def _fetch_upstream(self) -> dict[str, Any]:
        """Fetch LiteLLM JSON via stdlib urllib. Raises on network/HTTP errors.

        ``json.JSONDecodeError`` from a malformed body propagates; the
        caller in ``_do_work`` handles parse errors as a deduped issue.
        """

        def _do() -> dict[str, Any]:
            with urllib.request.urlopen(_LITELLM_URL, timeout=_FETCH_TIMEOUT_S) as resp:
                return json.loads(resp.read())

        return await asyncio.to_thread(_do)

    def _read_local_models(self) -> dict[str, dict[str, Any]]:
        path = self._repo_root / "src" / "assets" / "model_pricing.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        models = data.get("models", {})
        if not isinstance(models, dict):
            return {}
        return models

    def _apply_diff_to_pricing_file(
        self, local: dict[str, dict[str, Any]], diff: PricingDiff
    ) -> None:
        """Merge diff into the on-disk pricing file. Bumps updated_at."""
        path = self._repo_root / "src" / "assets" / "model_pricing.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        models = data.setdefault("models", {})

        for model, fields in diff.updated.items():
            entry = models.get(model)
            if entry is None:
                continue  # safety: shouldn't happen — updated was keyed off local
            entry.update(fields)

        for model, entry in diff.added.items():
            models[model] = entry

        data["updated_at"] = datetime.now(UTC).strftime("%Y-%m-%d")

        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    async def _open_or_update_refresh_pr(self, diff: PricingDiff) -> str | None:
        # Lazy import to avoid a top-level dependency cycle.
        from auto_pr import open_automated_pr_async  # noqa: PLC0415

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        pr_title = f"{_PR_TITLE_PREFIX} — {today}"
        pr_body = self._build_pr_body(diff)

        files_to_commit = [self._repo_root / "src" / "assets" / "model_pricing.json"]

        result = await open_automated_pr_async(
            repo_root=self._repo_root,
            branch=_REGEN_BRANCH,
            files=files_to_commit,
            pr_title=pr_title,
            pr_body=pr_body,
            base="main",
            auto_merge=False,  # Always human-reviewed per spec §3.
            labels=["hydraflow-ready", "pricing-refresh"],
            raise_on_failure=False,
        )
        if result.status in {"opened", "no-diff"}:
            return result.pr_url
        logger.warning("PricingRefreshLoop PR creation failed: %s", result.error)
        return None

    def _build_pr_body(self, diff: PricingDiff) -> str:
        lines = [
            "Auto-generated by `PricingRefreshLoop`. The pricing data in",
            "`src/assets/model_pricing.json` was refreshed from LiteLLM's",
            "structured upstream JSON.",
            "",
        ]
        if diff.updated:
            lines.append(f"**Updated** ({len(diff.updated)} model(s)):")
            lines.append("")
            for model, fields in sorted(diff.updated.items()):
                changes = ", ".join(f"{k}={v}" for k, v in fields.items())
                lines.append(f"- `{model}`: {changes}")
            lines.append("")
        if diff.added:
            lines.append(f"**Added** ({len(diff.added)} model(s)):")
            lines.append("")
            for model in sorted(diff.added):
                lines.append(f"- `{model}`")
            lines.append("")
        lines.extend(
            [
                "Source: <https://github.com/BerriAI/litellm/blob/main/"
                "model_prices_and_context_window.json>",
                "",
                "Per ADR-0029 caretaker pattern. **Human review required**;",
                "loop never auto-merges pricing changes.",
            ]
        )
        return "\n".join(lines)

    async def _open_bounds_issue(self, violations: list[BoundsViolation]) -> None:
        title = f"{_ISSUE_TITLE_PREFIX} bounds violation"
        existing = await self._pr_manager.find_existing_issue(title)
        if existing:
            return
        body_lines = [
            "PricingRefreshLoop rejected an upstream pricing update because",
            "one or more cost fields moved outside the bounds guard "
            "(>+100% or <-50%).",
            "",
            "**Violations:**",
            "",
        ]
        for bv in violations:
            body_lines.append(
                f"- `{bv.model}` `{bv.field}`: {bv.old} → {bv.new} "
                f"(ratio={bv.ratio:.2f})"
            )
        body_lines.extend(
            [
                "",
                "Verify against <https://docs.anthropic.com/en/docs/about-claude/models>",
                "and update `src/assets/model_pricing.json` manually if the",
                "upstream values are correct.",
            ]
        )
        await self._pr_manager.create_issue(
            title=title,
            body="\n".join(body_lines),
            labels=["hydraflow-find", "pricing-refresh"],
        )

    async def _open_parse_issue(self, detail: str) -> None:
        title = f"{_ISSUE_TITLE_PREFIX} upstream parse error"
        existing = await self._pr_manager.find_existing_issue(title)
        if existing:
            return
        body = (
            "PricingRefreshLoop could not parse LiteLLM's upstream JSON.\n\n"
            f"**Source:** <{_LITELLM_URL}>\n\n"
            f"**Error:** `{detail}`\n\n"
            "If this persists, the upstream URL may have moved or the JSON "
            "schema may have changed. Update the loop's source URL or "
            "fetch path as needed."
        )
        await self._pr_manager.create_issue(
            title=title,
            body=body,
            labels=["hydraflow-find", "pricing-refresh"],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pricing_refresh_loop_scenario.py::test_no_drift_returns_drift_false -v`

Expected: PASS.

- [ ] **Step 5: Add the drift-detected test**

Append to `tests/test_pricing_refresh_loop_scenario.py`:

```python
async def test_drift_opens_pr_via_auto_pr(repo_root: Path) -> None:
    """Upstream price differs → PR opened on pricing-refresh-auto branch."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1.5e-6,  # was 1.0/M, now 1.5/M (+50%, within bounds)
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, pr_manager = _build_loop(repo_root)

    pr_result = MagicMock(status="opened", pr_url="https://github.com/x/y/pull/1", error=None)
    pr_helper = AsyncMock(return_value=pr_result)

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.open_automated_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result["drift"] is True
    assert result["updated"] == 1
    assert result["pr_url"] == "https://github.com/x/y/pull/1"
    pr_helper.assert_awaited_once()
    kwargs = pr_helper.await_args.kwargs
    assert kwargs["branch"] == "pricing-refresh-auto"
    assert kwargs["pr_title"].startswith("chore(pricing): refresh from LiteLLM")
    assert kwargs["auto_merge"] is False
    assert "hydraflow-ready" in kwargs["labels"]


async def test_drift_writes_updated_pricing_file(repo_root: Path) -> None:
    """The on-disk file is rewritten with the new value before the PR opens."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1.5e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, _ = _build_loop(repo_root)

    pr_result = MagicMock(status="opened", pr_url="x", error=None)
    pr_helper = AsyncMock(return_value=pr_result)
    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.open_automated_pr_async", pr_helper),
    ):
        await loop._do_work()

    on_disk = json.loads(
        (repo_root / "src" / "assets" / "model_pricing.json").read_text()
    )
    assert (
        on_disk["models"]["claude-haiku-4-5-20251001"]["input_cost_per_million"]
        == 1.5
    )
    assert on_disk["updated_at"] != "2026-04-01"  # bumped


async def test_added_model_lands_in_pricing_file(repo_root: Path) -> None:
    """An upstream-only model is added to the JSON with provider+aliases scaffold."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
        "claude-future-99": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 2e-6,
            "output_cost_per_token": 10e-6,
        },
    }
    loop, _ = _build_loop(repo_root)
    pr_result = MagicMock(status="opened", pr_url="x", error=None)
    pr_helper = AsyncMock(return_value=pr_result)
    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.open_automated_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    on_disk = json.loads(
        (repo_root / "src" / "assets" / "model_pricing.json").read_text()
    )
    assert "claude-future-99" in on_disk["models"]
    new_entry = on_disk["models"]["claude-future-99"]
    assert new_entry["provider"] == "anthropic"
    assert new_entry["aliases"] == []
    assert new_entry["input_cost_per_million"] == 2.0
    assert result["added"] == 1
```

- [ ] **Step 6: Run all loop scenario tests**

Run: `uv run pytest tests/test_pricing_refresh_loop_scenario.py -v`

Expected: 4 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/pricing_refresh_loop.py tests/test_pricing_refresh_loop_scenario.py
git commit -m "feat(loop): PricingRefreshLoop with no-drift / drift / add paths"
```

---

## Task 5: PricingRefreshLoop failure paths

Bounds violation, parse error, network error. Each verified end-to-end.

**Files:**
- Test: `tests/test_pricing_refresh_loop_scenario.py` (append)

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_pricing_refresh_loop_scenario.py`:

```python
import urllib.error


async def test_network_error_returns_no_drift_no_issue(repo_root: Path) -> None:
    """Transient network outage: log + skip, never spam an issue."""
    loop, pr_manager = _build_loop(repo_root)
    pr_helper = AsyncMock()

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            side_effect=urllib.error.URLError("connection refused"),
        ),
        patch("auto_pr.open_automated_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result == {"drift": False, "error": "network"}
    pr_helper.assert_not_awaited()
    pr_manager.create_issue.assert_not_awaited()


async def test_bounds_violation_opens_issue_no_pr(repo_root: Path) -> None:
    """A doubled price triggers issue + no PR + no file write."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 3e-6,  # was 1/M, now 3/M = +200%, REJECT
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, pr_manager = _build_loop(repo_root)
    pr_helper = AsyncMock()

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.open_automated_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result["error"] == "bounds"
    assert result["violations"] == 1
    pr_helper.assert_not_awaited()
    pr_manager.create_issue.assert_awaited_once()
    issue_kwargs = pr_manager.create_issue.await_args.kwargs
    assert issue_kwargs["title"].startswith("[pricing-refresh]")
    assert "hydraflow-find" in issue_kwargs["labels"]
    assert "claude-haiku-4-5-20251001" in issue_kwargs["body"]


async def test_bounds_violation_does_not_overwrite_pricing_file(repo_root: Path) -> None:
    """The on-disk file must NOT be touched when a bounds guard fires."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 3e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, _ = _build_loop(repo_root)
    pricing_path = repo_root / "src" / "assets" / "model_pricing.json"
    before = pricing_path.read_text()

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.open_automated_pr_async", AsyncMock()),
    ):
        await loop._do_work()

    after = pricing_path.read_text()
    assert before == after


async def test_bounds_issue_dedups_by_title_prefix(repo_root: Path) -> None:
    """If an open bounds-violation issue already exists, do not file a duplicate."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 3e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, pr_manager = _build_loop(repo_root)
    pr_manager.find_existing_issue = AsyncMock(return_value=42)  # already open

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.open_automated_pr_async", AsyncMock()),
    ):
        await loop._do_work()

    pr_manager.create_issue.assert_not_awaited()


async def test_kill_switch_short_circuits(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HYDRAFLOW_DISABLE_PRICING_REFRESH=1 → return immediately."""
    monkeypatch.setenv("HYDRAFLOW_DISABLE_PRICING_REFRESH", "1")
    loop, pr_manager = _build_loop(repo_root)
    fetch = AsyncMock()
    pr_helper = AsyncMock()

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream", fetch,
        ),
        patch("auto_pr.open_automated_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result == {"skipped": "kill_switch"}
    fetch.assert_not_called()
    pr_helper.assert_not_awaited()
    pr_manager.create_issue.assert_not_awaited()


async def test_parse_error_opens_deduped_issue(repo_root: Path) -> None:
    """Upstream returns non-JSON → parse-error issue, no PR, no file change."""
    loop, pr_manager = _build_loop(repo_root)
    pr_helper = AsyncMock()
    pricing_path = repo_root / "src" / "assets" / "model_pricing.json"
    before = pricing_path.read_text()

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            side_effect=json.JSONDecodeError("Expecting value", "", 0),
        ),
        patch("auto_pr.open_automated_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result == {"drift": False, "error": "parse"}
    pr_helper.assert_not_awaited()
    pr_manager.create_issue.assert_awaited_once()
    issue_kwargs = pr_manager.create_issue.await_args.kwargs
    assert issue_kwargs["title"] == "[pricing-refresh] upstream parse error"
    assert "hydraflow-find" in issue_kwargs["labels"]
    assert pricing_path.read_text() == before


async def test_parse_error_dedups_when_issue_already_open(repo_root: Path) -> None:
    """Already-open parse-error issue → no duplicate."""
    loop, pr_manager = _build_loop(repo_root)
    pr_manager.find_existing_issue = AsyncMock(return_value=99)

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            side_effect=json.JSONDecodeError("bad", "", 0),
        ),
        patch("auto_pr.open_automated_pr_async", AsyncMock()),
    ):
        await loop._do_work()

    pr_manager.create_issue.assert_not_awaited()


async def test_pr_failure_reverts_pricing_file(repo_root: Path) -> None:
    """If auto_pr returns failure, the on-disk pricing file is restored.

    Locks the atomic-write contract: a successful file write followed by
    a failed PR-open must NOT leave the worktree mutated. Otherwise the
    next tick reads the mutation as "local", sees no diff, and the
    refresh is silently lost.
    """
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1.5e-6,  # +50%, within bounds
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, _ = _build_loop(repo_root)
    pricing_path = repo_root / "src" / "assets" / "model_pricing.json"
    before = pricing_path.read_text()

    pr_result = MagicMock(status="failed", pr_url=None, error="boom")
    pr_helper = AsyncMock(return_value=pr_result)

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.open_automated_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result["error"] == "pr_failed"
    assert result["pr_url"] is None
    # File must be byte-identical to its pre-tick state.
    assert pricing_path.read_text() == before


async def test_pr_helper_exception_reverts_pricing_file(repo_root: Path) -> None:
    """If auto_pr raises (e.g., transient gh failure), revert the file."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1.5e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, _ = _build_loop(repo_root)
    pricing_path = repo_root / "src" / "assets" / "model_pricing.json"
    before = pricing_path.read_text()

    pr_helper = AsyncMock(side_effect=RuntimeError("gh CLI missing"))

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.open_automated_pr_async", pr_helper),
        pytest.raises(RuntimeError),
    ):
        await loop._do_work()

    assert pricing_path.read_text() == before
```

- [ ] **Step 2: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_pricing_refresh_loop_scenario.py -v`

Expected: 13 PASS (4 happy + 5 original failure paths + 4 new parse/atomic tests = 13).

- [ ] **Step 3: Commit**

```bash
git add tests/test_pricing_refresh_loop_scenario.py
git commit -m "test(loop): network/bounds/kill-switch failure paths for PricingRefreshLoop"
```

---

## Task 6: Five-checkpoint wiring (Services + orchestrator)

Wire the loop into the live runtime per ADR-0029 / gotchas.md. Two files modified, mechanical change.

**Files:**
- Modify: `src/service_registry.py`
- Modify: `src/orchestrator.py`

- [ ] **Step 1: Add the import + dataclass field in service_registry.py**

Open `src/service_registry.py`. Find the `from diagram_loop import DiagramLoop  # noqa: TCH001` line (around line 30) — copy the comment style verbatim from the actual line in your file (it MAY or may not have `# noqa: TCH001`; match whatever DiagramLoop uses) and add an alphabetically-adjacent import for `PricingRefreshLoop`:

```python
from pricing_refresh_loop import PricingRefreshLoop  # noqa: TCH001
```

(If the surrounding `from diagram_loop import ...` line has no noqa comment, drop it from the new import too.)

Find the `Services` dataclass (around line 186) — the line `diagram_loop: DiagramLoop` — and add the new field beneath it:

```python
    diagram_loop: DiagramLoop
    pricing_refresh_loop: PricingRefreshLoop
```

- [ ] **Step 2: Instantiate in the factory function**

In the same file, find where `diagram_loop = DiagramLoop(...)` is constructed (around line 741). Below it, add:

```python
    pricing_refresh_loop = PricingRefreshLoop(
        config=config,
        pr_manager=prs,
        deps=loop_deps,
    )
```

Then find the `Services(...)` call near the end of the factory function and add `pricing_refresh_loop=pricing_refresh_loop,` to the kwargs (alphabetical ordering against neighbors is fine; if existing ordering is by-domain, match that).

- [ ] **Step 3: Register in orchestrator.py bg_loop_registry**

Open `src/orchestrator.py`. Find the `bg_loop_registry` dict definition (the block ending around line 175 with `"diagram_loop": svc.diagram_loop,`). Add a new entry beneath:

```python
            "diagram_loop": svc.diagram_loop,
            "pricing_refresh": svc.pricing_refresh_loop,
        }
```

- [ ] **Step 4: Register in orchestrator.py loop_factories**

In the same file, find the `loop_factories` list (around lines 935–960). Add to the end of the tuple list, after the diagram_loop entry:

```python
            ("diagram_loop", self._svc.diagram_loop.run),
            ("pricing_refresh", self._svc.pricing_refresh_loop.run),
        ]
```

- [ ] **Step 5: Run smoke-level checks**

Run: `uv run pyright src/pricing_refresh_loop.py src/service_registry.py src/orchestrator.py`

Expected: 0 errors.

Run: `uv run pytest tests/test_orchestrator_wiring.py tests/test_service_registry*.py -v 2>&1 | tail -10` (or whatever the closest existing smoke test is — find one with `grep -l "Services\|service_registry" tests/`).

Expected: passes (or surface failures for fix in this step).

- [ ] **Step 6: Commit**

```bash
git add src/service_registry.py src/orchestrator.py
git commit -m "feat(loop): wire PricingRefreshLoop into runtime — five-checkpoint pattern"
```

---

## Task 7: Test-helper SimpleNamespace wiring

`tests/orchestrator_integration_utils.py` builds a SimpleNamespace of fake services for orchestrator tests. Each new loop in the live wiring must be added here too.

**Files:**
- Modify: `tests/orchestrator_integration_utils.py`

- [ ] **Step 1: Find the existing `services.diagram_loop = FakeBackgroundLoop()` line**

Run: `grep -n "diagram_loop" tests/orchestrator_integration_utils.py`

Expected: one line near 501.

- [ ] **Step 2: Add the new attribute below it**

Edit `tests/orchestrator_integration_utils.py`:

```python
    services.diagram_loop = FakeBackgroundLoop()
    services.pricing_refresh_loop = FakeBackgroundLoop()
```

- [ ] **Step 3: Run any orchestrator integration tests that touch this helper**

Run: `uv run pytest tests/test_orchestrator*.py -v`

Expected: still passes (the helper is permissive; new attributes don't break existing tests).

- [ ] **Step 4: Commit**

```bash
git add tests/orchestrator_integration_utils.py
git commit -m "test: register pricing_refresh_loop FakeBackgroundLoop in orchestrator helper"
```

---

## Task 8: MockWorld catalog wiring + scenario

The catalog builds loops from a registry; MockWorld scenarios run the full loop through `run_with_loops` rather than `_do_work` directly.

**Files:**
- Modify: `tests/scenarios/catalog/loop_registrations.py`
- Create: `tests/fixtures/litellm_pricing_sample.json`
- Create: `tests/scenarios/test_pricing_refresh_loop_mockworld.py`

- [ ] **Step 1: Create the LiteLLM fixture**

Create `tests/fixtures/litellm_pricing_sample.json`:

```json
{
  "claude-haiku-4-5-20251001": {
    "litellm_provider": "anthropic",
    "input_cost_per_token": 1e-06,
    "output_cost_per_token": 5e-06,
    "cache_creation_input_token_cost": 1.25e-06,
    "cache_read_input_token_cost": 1e-07
  },
  "claude-sonnet-4-6": {
    "litellm_provider": "anthropic",
    "input_cost_per_token": 3e-06,
    "output_cost_per_token": 1.5e-05,
    "cache_creation_input_token_cost": 3.75e-06,
    "cache_read_input_token_cost": 3e-07
  },
  "anthropic.claude-3-haiku-v1:0": {
    "litellm_provider": "anthropic",
    "input_cost_per_token": 2.5e-07,
    "output_cost_per_token": 1.25e-06
  },
  "gpt-4": {
    "litellm_provider": "openai",
    "input_cost_per_token": 3e-05,
    "output_cost_per_token": 6e-05
  }
}
```

- [ ] **Step 2: Add `_build_pricing_refresh_loop` to the catalog**

Open `tests/scenarios/catalog/loop_registrations.py`. Find the `_build_diagram_loop` function (around line 856) and add a sibling beneath it:

```python
def _build_pricing_refresh_loop(
    ports: dict[str, Any], config: Any, deps: Any
) -> Any:
    from pricing_refresh_loop import PricingRefreshLoop  # noqa: PLC0415

    return PricingRefreshLoop(
        config=config,
        pr_manager=ports["github"],
        deps=deps,
    )
```

In the `_BUILDERS: dict[str, Any]` dict (around line 904), add:

```python
    "diagram_loop": _build_diagram_loop,
    "pricing_refresh": _build_pricing_refresh_loop,
```

- [ ] **Step 3: Write the failing scenario tests**

Create `tests/scenarios/test_pricing_refresh_loop_mockworld.py`:

```python
"""MockWorld-based scenarios for PricingRefreshLoop.

Exercises the full ``run_with_loops`` path so the loop's catalog wiring,
port resolution, and dispatch are all under test, not just ``_do_work``
in isolation.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _seed_pricing_file(repo_root: Path) -> None:
    """Mirror src/assets/model_pricing.json into the MockWorld worktree."""
    target = repo_root / "src" / "assets" / "model_pricing.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "currency": "USD",
                "updated_at": "2026-04-01",
                "source": "https://docs.anthropic.com/en/docs/about-claude/models",
                "models": {
                    "claude-haiku-4-5-20251001": {
                        "provider": "anthropic",
                        "aliases": ["haiku"],
                        "input_cost_per_million": 1.00,
                        "output_cost_per_million": 5.00,
                        "cache_write_cost_per_million": 1.25,
                        "cache_read_cost_per_million": 0.10,
                    },
                    "claude-sonnet-4-6": {
                        "provider": "anthropic",
                        "aliases": ["sonnet"],
                        "input_cost_per_million": 3.00,
                        "output_cost_per_million": 15.00,
                        "cache_write_cost_per_million": 3.75,
                        "cache_read_cost_per_million": 0.30,
                    },
                },
            },
            indent=2,
        )
        + "\n"
    )


class TestPricingRefreshLoop:
    """Daily upstream-pricing refresh — drift → PR, no-drift → skip."""

    async def test_no_drift_skips_pr(self, tmp_path) -> None:
        """Upstream values match local exactly → no PR opened.

        Note: ``_FIXTURE_PATH`` carries an "addition" entry by design (for
        the drift case). For this no-drift assertion we use an inline
        payload that mirrors the seeded local file precisely.
        """
        world = MockWorld(tmp_path)
        _seed_pricing_file(tmp_path)

        github = AsyncMock(
            find_existing_issue=AsyncMock(return_value=0),
            create_issue=AsyncMock(return_value=0),
        )
        _seed_ports(world, github=github)

        upstream_payload = {
            "claude-haiku-4-5-20251001": {
                "litellm_provider": "anthropic",
                "input_cost_per_token": 1e-6,
                "output_cost_per_token": 5e-6,
                "cache_creation_input_token_cost": 1.25e-6,
                "cache_read_input_token_cost": 1e-7,
            },
            "claude-sonnet-4-6": {
                "litellm_provider": "anthropic",
                "input_cost_per_token": 3e-6,
                "output_cost_per_token": 15e-6,
                "cache_creation_input_token_cost": 3.75e-6,
                "cache_read_input_token_cost": 3e-7,
            },
        }
        pr_helper = AsyncMock()
        with (
            patch(
                "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
                return_value=upstream_payload,
            ),
            patch("auto_pr.open_automated_pr_async", pr_helper),
        ):
            stats = await world.run_with_loops(["pricing_refresh"], cycles=1)

        assert stats["pricing_refresh"] == {"drift": False}
        pr_helper.assert_not_awaited()
        github.create_issue.assert_not_awaited()

    async def test_drift_opens_pr(self, tmp_path) -> None:
        """Upstream price changed → PR opens with pricing-refresh-auto branch."""
        world = MockWorld(tmp_path)
        _seed_pricing_file(tmp_path)

        github = AsyncMock(
            find_existing_issue=AsyncMock(return_value=0),
            create_issue=AsyncMock(return_value=0),
        )
        _seed_ports(world, github=github)

        # Bump haiku's input cost: 1.0/M → 1.5/M (within bounds).
        upstream_payload = {
            "claude-haiku-4-5-20251001": {
                "litellm_provider": "anthropic",
                "input_cost_per_token": 1.5e-6,
                "output_cost_per_token": 5e-6,
                "cache_creation_input_token_cost": 1.25e-6,
                "cache_read_input_token_cost": 1e-7,
            },
            "claude-sonnet-4-6": {
                "litellm_provider": "anthropic",
                "input_cost_per_token": 3e-6,
                "output_cost_per_token": 15e-6,
                "cache_creation_input_token_cost": 3.75e-6,
                "cache_read_input_token_cost": 3e-7,
            },
        }

        pr_result = MagicMock(
            status="opened", pr_url="https://github.com/x/y/pull/9", error=None
        )
        pr_helper = AsyncMock(return_value=pr_result)

        with (
            patch(
                "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
                return_value=upstream_payload,
            ),
            patch("auto_pr.open_automated_pr_async", pr_helper),
        ):
            stats = await world.run_with_loops(["pricing_refresh"], cycles=1)

        result = stats["pricing_refresh"]
        assert result["drift"] is True
        assert result["updated"] == 1
        assert result["pr_url"] == "https://github.com/x/y/pull/9"

        pr_helper.assert_awaited_once()
        kwargs = pr_helper.await_args.kwargs
        assert kwargs["branch"] == "pricing-refresh-auto"
        assert kwargs["pr_title"].startswith("chore(pricing): refresh from LiteLLM")
        assert kwargs["auto_merge"] is False
```

- [ ] **Step 4: Run the scenario tests to verify they pass**

Run: `uv run pytest tests/scenarios/test_pricing_refresh_loop_mockworld.py -v`

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/scenarios/catalog/loop_registrations.py tests/fixtures/litellm_pricing_sample.json tests/scenarios/test_pricing_refresh_loop_mockworld.py
git commit -m "test(scenario): MockWorld scenarios for PricingRefreshLoop"
```

---

## Task 9: Final quality gate

**Files:**
- None (verification only).

- [ ] **Step 1: Run `make quality`**

Run: `make quality`

Expected: lint OK, typecheck OK, security OK, tests OK.

- [ ] **Step 2: Sanity-check the loop count**

Run: `grep -c '"\w*": svc\.' src/orchestrator.py`

Expected: 25 (was 24 before Task 6 — +1 for `pricing_refresh`).

- [ ] **Step 3: Verify the test file count delta**

Run: `git diff --stat origin/main..HEAD | tail -3`

Expected: ~9 files changed: 2 src/ created, 2 src/ modified, 4 tests/ created, 1 test fixture, 1 test helper modified, 1 catalog modified, 2 docs/ created (spec + plan).

- [ ] **Step 4: No commit — verification only.**

---

## Self-review

**Spec coverage:**

| Spec section | Implementing task |
|---|---|
| §2 Source of truth (LiteLLM URL, field mapping) | Task 1 (filter) + Task 2 (mapping) |
| §3 Behavior (fetch, filter, diff, bounds, PR) | Tasks 3, 4 |
| §4 Failure handling | Task 5 |
| §5 Cadence + kill-switch | Task 4 (`_get_default_interval`, `_KILL_SWITCH_ENV`) |
| §6 Alias derivation | Task 3 (added entries get empty aliases — humans fill in PR review per spec §6 "If alias derivation fails... canonical-only") |
| §7 Idempotence (PR, issue) | Task 4 (PR via `auto_pr.open_automated_pr_async`), Task 5 (issue dedup via `find_existing_issue`) |
| §8 Five-checkpoint wiring | Tasks 6, 7, 8 |
| §9 Files | All tasks |
| §10 Testing strategy | Tasks 1–5 unit + scenario, Task 8 MockWorld |
| §11 Risks | Mitigations baked into Tasks 3, 4, 5 |
| §13 Done definition | Task 9 |

No gaps.

**Type consistency:**

- `PricingDiff.updated: dict[str, dict[str, float]]` — used identically in Tasks 3 and 4.
- `PricingDiff.added: dict[str, dict[str, Any]]` — used identically in Tasks 3 and 4.
- `BoundsViolation` dataclass — Task 3 defines, Task 4 consumes via `_open_bounds_issue(violations)`.
- "Updated" field name in `PricingDiff` matches `result["updated"]` in `_do_work` (Task 4).
- Branch name `pricing-refresh-auto` consistent across Tasks 4, 8.
- PR title prefix `chore(pricing): refresh from LiteLLM` consistent.
- Issue title prefix `[pricing-refresh]` consistent.
- Kill-switch env `HYDRAFLOW_DISABLE_PRICING_REFRESH` consistent.
- Loop name `pricing_refresh` (registry key) vs `pricing_refresh_loop` (services field) — intentional split mirrors `diagram_loop` precedent.

**Placeholder scan:** none.

**Spec §6 alias derivation note:** the plan implements only the conservative path (added entries get empty aliases). The spec's "smart alias derivation for the latest entry of each family" is not implemented in the loop — humans fill aliases during PR review. This matches the spec's fallback path. If a future PR wants the smart-derivation path, that's a separate plan.
