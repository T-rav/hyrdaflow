"""Regression test for issue #8812.

Bug: ``run_preflight`` had a bare ``except Exception`` block that swallowed
``CreditExhaustedError`` even though ``BaseSubprocessRunner`` correctly
reraises it.  ``AutoAgentPreflightLoop`` then loops indefinitely burning budget
unless ``auto_agent_daily_budget_usd`` is configured (defaults to unlimited).

Fix: call ``reraise_on_credit_or_bug(exc)`` as the first line of the except
body so that fatal billing signals propagate to the caller.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from preflight.agent import PreflightAgentDeps, run_preflight
from preflight.context import PreflightContext
from subprocess_util import CreditExhaustedError


def _ctx() -> PreflightContext:
    return PreflightContext(
        issue_number=42,
        issue_body="body",
        issue_comments=[],
        sub_label="flaky-test-stuck",
        escalation_context=None,
        wiki_excerpts="",
        sentry_events=[],
        recent_commits=[],
    )


class TestRunPreflightDoesNotSwallowCreditExhausted:
    """Issue #8812: run_preflight must not swallow CreditExhaustedError."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_from_spawn_fn(self) -> None:
        """CreditExhaustedError raised by spawn_fn must propagate, not be swallowed."""
        spawn_fn = AsyncMock(side_effect=CreditExhaustedError("credits exhausted"))
        deps = PreflightAgentDeps(
            persona="test",
            cost_cap_usd=None,
            wall_clock_cap_s=None,
            spawn_fn=spawn_fn,
        )

        with pytest.raises(CreditExhaustedError):
            await run_preflight(
                context=_ctx(),
                repo_slug="x/y",
                worktree_path="/tmp",
                deps=deps,
            )

    @pytest.mark.asyncio
    async def test_generic_runtime_error_still_returns_fatal(self) -> None:
        """Non-fatal errors (RuntimeError etc.) must still be caught and return fatal."""
        spawn_fn = AsyncMock(side_effect=RuntimeError("oom"))
        deps = PreflightAgentDeps(
            persona="test",
            cost_cap_usd=None,
            wall_clock_cap_s=None,
            spawn_fn=spawn_fn,
        )

        result = await run_preflight(
            context=_ctx(),
            repo_slug="x/y",
            worktree_path="/tmp",
            deps=deps,
        )

        assert result.status == "fatal"
        assert "spawn failed" in result.diagnosis
