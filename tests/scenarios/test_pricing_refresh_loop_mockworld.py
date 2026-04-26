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
