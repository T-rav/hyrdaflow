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
