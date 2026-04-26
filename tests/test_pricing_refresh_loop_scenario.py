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

    pr_result = MagicMock(
        status="opened", pr_url="https://github.com/x/y/pull/1", error=None
    )
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
        on_disk["models"]["claude-haiku-4-5-20251001"]["input_cost_per_million"] == 1.5
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
