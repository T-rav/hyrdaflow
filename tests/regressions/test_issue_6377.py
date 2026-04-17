"""Regression test for issue #6377.

Bug: ``ShapePhase._check_for_response`` wraps the WhatsApp state check
in ``except Exception: pass`` with zero logging.  When
``get_shape_response()`` or ``clear_shape_response()`` raises (state
corruption, attribute error, unexpected model change), the exception is
completely invisible — no log, no metric, no Sentry breadcrumb.

Expected behaviour after fix:
  - WhatsApp state access failures are logged at ``warning`` with the
    issue number and ``exc_info=True``.
  - The exception is still caught (non-fatal) — fallback to GitHub
    comment polling still runs.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from models import Task
from shape_phase import ShapePhase


@pytest.fixture
def config() -> HydraFlowConfig:
    return HydraFlowConfig(repo="test/repo")


@pytest.fixture
def deps(config: HydraFlowConfig) -> dict:
    return {
        "config": config,
        "state": MagicMock(),
        "store": MagicMock(),
        "prs": AsyncMock(),
        "event_bus": AsyncMock(),
        "stop_event": asyncio.Event(),
    }


@pytest.fixture
def phase(deps: dict) -> ShapePhase:
    return ShapePhase(**deps)


@pytest.fixture
def sample_task() -> Task:
    return Task(
        id=42,
        title="Build a better Calendly",
        body="Vague idea",
        labels=["hydraflow-shape"],
    )


class TestWhatsAppStateErrorLogging:
    """Issue #6377: WhatsApp state errors must be logged, not silently swallowed."""

    @pytest.mark.asyncio
    async def test_get_shape_response_error_is_logged(
        self,
        phase: ShapePhase,
        sample_task: Task,
        deps: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When get_shape_response raises, a warning must be logged."""
        deps["state"].get_shape_response.side_effect = AttributeError(
            "shape_responses not found"
        )
        # Fallback path returns no GitHub comment
        enriched = sample_task.model_copy(update={"comments": []})
        deps["store"].enrich_with_comments = AsyncMock(return_value=enriched)

        with caplog.at_level(logging.WARNING, logger="shape_phase"):
            result = await phase._check_for_response(sample_task)

        # Should still fall through to GitHub (non-fatal)
        assert result is None

        # The bug: no warning is logged — this assertion is RED
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) >= 1, (
            "Expected a warning log when get_shape_response raises, "
            "but no warning was emitted (exception silently swallowed)"
        )
        assert "42" in warnings[0].message

    @pytest.mark.asyncio
    async def test_clear_shape_response_error_is_logged(
        self,
        phase: ShapePhase,
        sample_task: Task,
        deps: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When clear_shape_response raises after a successful get, a warning must be logged."""
        deps["state"].get_shape_response.return_value = "User picked Direction A"
        deps["state"].clear_shape_response.side_effect = TypeError(
            "unexpected state format"
        )
        # Fallback path
        enriched = sample_task.model_copy(update={"comments": []})
        deps["store"].enrich_with_comments = AsyncMock(return_value=enriched)

        with caplog.at_level(logging.WARNING, logger="shape_phase"):
            result = await phase._check_for_response(sample_task)

        # Should still fall through (non-fatal) — the whatsapp result is lost
        # because clear raised before the return
        assert result is None or result == ("User picked Direction A", "whatsapp")

        # The bug: no warning is logged — this assertion is RED
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) >= 1, (
            "Expected a warning log when clear_shape_response raises, "
            "but no warning was emitted (exception silently swallowed)"
        )
        assert "42" in warnings[0].message

    @pytest.mark.asyncio
    async def test_state_error_still_falls_through_to_github(
        self,
        phase: ShapePhase,
        sample_task: Task,
        deps: dict,
    ) -> None:
        """Even when WhatsApp state raises, GitHub comment polling still runs.

        This test is GREEN — it validates the fallback behaviour that
        already works.  It's included to ensure the fix doesn't break
        the fallback.
        """
        deps["state"].get_shape_response.side_effect = RuntimeError("state corrupt")

        enriched = sample_task.model_copy(
            update={"comments": ["**Shape Turn 1** agent msg", "I pick Direction A"]}
        )
        deps["store"].enrich_with_comments = AsyncMock(return_value=enriched)

        result = await phase._check_for_response(sample_task)

        # GitHub fallback should still work
        assert result is not None
        assert result[1] == "github"
