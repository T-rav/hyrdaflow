"""Tests for the discover phase — product research routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from discover_phase import DiscoverPhase
from models import Task


@pytest.fixture
def config() -> HydraFlowConfig:
    return HydraFlowConfig(repo="test/repo")


@pytest.fixture
def deps(config: HydraFlowConfig) -> dict:
    """Shared dependencies for DiscoverPhase."""
    import asyncio

    return {
        "config": config,
        "state": MagicMock(),
        "store": MagicMock(),
        "prs": AsyncMock(),
        "event_bus": AsyncMock(),
        "stop_event": asyncio.Event(),
    }


@pytest.fixture
def phase(deps: dict) -> DiscoverPhase:
    return DiscoverPhase(**deps)


@pytest.fixture
def sample_task() -> Task:
    return Task(
        id=42,
        title="Build a better Calendly",
        body="Vague idea",
        labels=["hydraflow-discover"],
    )


class TestDiscoverPhase:
    """Tests for DiscoverPhase."""

    @pytest.mark.asyncio
    async def test_discover_single_posts_research_brief(
        self, phase: DiscoverPhase, sample_task: Task, deps: dict
    ) -> None:
        """Discovery posts a research brief comment and transitions to shape."""
        result = await phase._discover_single(sample_task)

        assert result == 1
        deps["prs"].post_comment.assert_awaited_once()
        comment = deps["prs"].post_comment.call_args[0][1]
        assert "Product Discovery Brief" in comment
        assert "#42" in comment

    @pytest.mark.asyncio
    async def test_discover_single_transitions_to_shape(
        self, phase: DiscoverPhase, sample_task: Task, deps: dict
    ) -> None:
        """Discovery transitions the issue to the shape stage."""
        await phase._discover_single(sample_task)

        deps["store"].enqueue_transition.assert_called_once_with(sample_task, "shape")
        deps["prs"].transition.assert_awaited_once_with(42, "shape")

    @pytest.mark.asyncio
    async def test_discover_single_increments_counter(
        self, phase: DiscoverPhase, sample_task: Task, deps: dict
    ) -> None:
        """Discovery increments the 'discovered' session counter."""
        await phase._discover_single(sample_task)

        deps["state"].increment_session_counter.assert_called_once_with("discovered")

    @pytest.mark.asyncio
    async def test_discover_single_publishes_events(
        self, phase: DiscoverPhase, sample_task: Task, deps: dict
    ) -> None:
        """Discovery publishes start and completion events."""
        await phase._discover_single(sample_task)

        assert deps["event_bus"].publish.await_count == 2
        calls = deps["event_bus"].publish.call_args_list
        assert calls[0][0][0].data["action"] == "started"
        assert calls[1][0][0].data["action"] == "completed"

    @pytest.mark.asyncio
    async def test_discover_single_dry_run_skips_transition(
        self, deps: dict, sample_task: Task
    ) -> None:
        """In dry_run mode, discovery skips posting and transitioning."""
        deps["config"] = HydraFlowConfig(repo="test/repo", dry_run=True)
        phase = DiscoverPhase(**deps)

        result = await phase._discover_single(sample_task)

        assert result == 1
        deps["prs"].post_comment.assert_not_awaited()
        deps["store"].enqueue_transition.assert_not_called()

    def test_format_research_brief_structure(
        self, phase: DiscoverPhase, sample_task: Task
    ) -> None:
        """Research brief has expected sections."""
        from models import DiscoverResult

        result = DiscoverResult(
            issue_number=42,
            research_brief="Test research findings",
            competitors=["Calendly", "Cal.com"],
            user_needs=["Group scheduling", "Privacy"],
            opportunities=["Open source alternative"],
        )
        brief = phase._format_research_brief(sample_task, result)

        assert "## Product Discovery Brief" in brief
        assert "Test research findings" in brief
        assert "Calendly" in brief
        assert "Cal.com" in brief
        assert "Group scheduling" in brief
        assert "Open source alternative" in brief
