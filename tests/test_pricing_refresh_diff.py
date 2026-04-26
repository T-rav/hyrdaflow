"""Pure-function tests for pricing_refresh_diff module."""

from __future__ import annotations

from typing import Any

import pytest

from pricing_refresh_diff import (
    filter_anthropic_entries,
    map_litellm_to_local_costs,
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
    assert (
        normalize_litellm_key("claude-haiku-4-5-20251001")
        == "claude-haiku-4-5-20251001"
    )


def test_normalize_strips_only_v1_zero() -> None:
    # Other v-suffixes preserved as-is — only v1:0 is the Bedrock convention.
    assert normalize_litellm_key("claude-future-v2:1") == "claude-future-v2:1"


def test_filter_keeps_only_anthropic_provider() -> None:
    raw = {
        "claude-haiku-4-5": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1e-6,
        },
        "gpt-4": {"litellm_provider": "openai", "input_cost_per_token": 1e-5},
        "anthropic.claude-3-haiku": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1e-7,
        },
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


def test_map_per_token_to_per_million() -> None:
    upstream = {
        "input_cost_per_token": 1e-6,  # 1.00 / M
        "output_cost_per_token": 5e-6,  # 5.00 / M
        "cache_creation_input_token_cost": 1.25e-6,  # 1.25 / M
        "cache_read_input_token_cost": 1e-7,  # 0.10 / M
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


from pricing_refresh_diff import (
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
    upstream = {
        "claude-x": _upstream_entry(input_cost_per_token=2.5e-6)
    }  # 1.0 → 2.5 = +150%
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
    upstream = {
        "claude-x": _upstream_entry(input_cost_per_token=0.4e-6)
    }  # 1.0 → 0.4 = -60%
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


def test_bounds_guard_zero_to_nonzero_not_treated_as_infinite_bounds_violation() -> (
    None
):
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
