"""Regression test for issue #8008.

Bug: ``RouteContext.execute_admin_task`` swallows ``CreditExhaustedError`` and
``AuthenticationError``.  Admin tasks that invoke LLM runners or GitHub API
calls can raise these fatal errors; the bare ``except Exception`` handler caught
them, logged, and returned HTTP 500 — bypassing the global credit-pause and
auth-retry circuit breakers entirely.

Fix: call ``reraise_on_credit_or_bug(exc)`` before the generic fallback so that
fatal infrastructure errors propagate and the global handlers can act on them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from dashboard_routes import RouteContext
from subprocess_util import AuthenticationError, CreditExhaustedError

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from state import StateTracker


def _make_ctx(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    tmp_path: Path,
) -> RouteContext:
    from config import Credentials
    from pr_manager import PRManager

    return RouteContext(
        config=config,
        credentials=Credentials(),
        event_bus=event_bus,
        state=state,
        pr_manager=PRManager(config, event_bus),
        get_orchestrator=lambda: None,
        set_orchestrator=lambda o: None,
        set_run_task=lambda t: None,
        ui_dist_dir=tmp_path / "no-dist",
        template_dir=tmp_path / "no-templates",
    )


class TestExecuteAdminTaskExceptBlockHasReraiseGuard:
    """Issue #8008: execute_admin_task must not swallow credit/auth errors."""

    @pytest.mark.asyncio
    async def test_execute_admin_task_propagates_credit_exhausted_error(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        """CreditExhaustedError must propagate, not be silently swallowed as HTTP 500."""
        task_fn = AsyncMock(side_effect=CreditExhaustedError("credits gone"))
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        with pytest.raises(CreditExhaustedError):
            await ctx.execute_admin_task("test-task", task_fn, None)

    @pytest.mark.asyncio
    async def test_execute_admin_task_propagates_authentication_error(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        """AuthenticationError must propagate, not be silently swallowed as HTTP 500."""
        task_fn = AsyncMock(side_effect=AuthenticationError("auth failed"))
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        with pytest.raises(AuthenticationError):
            await ctx.execute_admin_task("test-task", task_fn, None)

    @pytest.mark.asyncio
    async def test_execute_admin_task_still_catches_generic_exceptions(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        """Generic errors (non-fatal) must still be caught and return HTTP 500."""
        task_fn = AsyncMock(side_effect=RuntimeError("something went wrong"))
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        response = await ctx.execute_admin_task("test-task", task_fn, None)

        assert response.status_code == 500
