"""Tests for the shape phase — product direction selection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from models import Task
from shape_phase import _SHAPE_OPTIONS_MARKER, ShapePhase


@pytest.fixture
def config() -> HydraFlowConfig:
    return HydraFlowConfig(repo="test/repo")


@pytest.fixture
def deps(config: HydraFlowConfig) -> dict:
    """Shared dependencies for ShapePhase."""
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


class TestShapePhaseGenerate:
    """Tests for option generation (Part A)."""

    @pytest.mark.asyncio
    async def test_generate_options_posts_comment(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """Shape posts direction options as a comment."""
        # No existing comments with options marker
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(update={"comments": []})
        )
        await phase._shape_single(sample_task)

        deps["prs"].post_comment.assert_awaited_once()
        comment = deps["prs"].post_comment.call_args[0][1]
        assert _SHAPE_OPTIONS_MARKER in comment
        assert "Direction A" in comment

    @pytest.mark.asyncio
    async def test_generate_options_re_enqueues(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """After posting options, issue is re-enqueued for polling."""
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(update={"comments": []})
        )
        await phase._shape_single(sample_task)

        # Should re-enqueue to shape for the polling cycle
        deps["store"].enqueue_transition.assert_called_with(sample_task, "shape")


class TestShapePhaseSelection:
    """Tests for selection detection (Part B)."""

    @pytest.mark.asyncio
    async def test_detects_direction_selection(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """Shape detects a direction selection in comments."""
        comments = [
            f"{_SHAPE_OPTIONS_MARKER} for #42\n\n### Direction A: ...",
            "Direction B — but scope it to MVP only",
        ]
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(update={"comments": comments})
        )
        result = await phase._shape_single(sample_task)

        assert result == 1
        deps["store"].enqueue_transition.assert_called_once_with(sample_task, "plan")
        deps["prs"].transition.assert_awaited_once_with(42, "plan")

    @pytest.mark.asyncio
    async def test_no_selection_re_enqueues(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """When no selection is found, issue is re-enqueued."""
        comments = [
            f"{_SHAPE_OPTIONS_MARKER} for #42\n\n### Direction A: ...",
            "Hmm, interesting options. Let me think about it.",
        ]
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(update={"comments": comments})
        )
        result = await phase._shape_single(sample_task)

        assert result == 0
        deps["store"].enqueue_transition.assert_called_once_with(sample_task, "shape")

    @pytest.mark.asyncio
    async def test_selection_increments_counter(
        self, phase: ShapePhase, sample_task: Task, deps: dict
    ) -> None:
        """Selection increments the 'shaped' session counter."""
        comments = [
            f"{_SHAPE_OPTIONS_MARKER} for #42\n\n### Direction A: ...",
            "Direction A",
        ]
        deps["store"].enrich_with_comments = AsyncMock(
            return_value=sample_task.model_copy(update={"comments": comments})
        )
        await phase._shape_single(sample_task)

        deps["state"].increment_session_counter.assert_called_once_with("shaped")


class TestSelectionParsing:
    """Tests for the _find_selection helper."""

    def test_finds_direction_a(self, phase: ShapePhase) -> None:
        comments = [f"{_SHAPE_OPTIONS_MARKER} for #42", "Direction A"]
        assert phase._find_selection(comments) == "A"

    def test_finds_direction_b_case_insensitive(self, phase: ShapePhase) -> None:
        comments = [f"{_SHAPE_OPTIONS_MARKER} for #42", "direction b please"]
        assert phase._find_selection(comments) == "B"

    def test_finds_option_c(self, phase: ShapePhase) -> None:
        comments = [f"{_SHAPE_OPTIONS_MARKER} for #42", "Option C — but scoped down"]
        assert phase._find_selection(comments) == "C"

    def test_ignores_comments_before_options(self, phase: ShapePhase) -> None:
        comments = ["Direction A", f"{_SHAPE_OPTIONS_MARKER} for #42"]
        # "Direction A" appears before the marker, should not be found
        assert phase._find_selection(comments) is None

    def test_returns_none_when_no_selection(self, phase: ShapePhase) -> None:
        comments = [f"{_SHAPE_OPTIONS_MARKER} for #42", "Still thinking..."]
        assert phase._find_selection(comments) is None

    def test_returns_none_with_no_options_marker(self, phase: ShapePhase) -> None:
        comments = ["Just a regular comment", "Direction A"]
        assert phase._find_selection(comments) is None


class TestFormatOptions:
    """Tests for option formatting."""

    def test_format_includes_marker(self, phase: ShapePhase, sample_task: Task) -> None:
        from models import ProductDirection, ShapeResult

        result = ShapeResult(
            issue_number=42,
            directions=[
                ProductDirection(
                    name="Simple",
                    approach="Keep it simple",
                    tradeoffs="Less features",
                    effort="Low",
                    risk="Low",
                ),
                ProductDirection(
                    name="Complex",
                    approach="Full featured",
                    tradeoffs="More work",
                    effort="High",
                    risk="Medium",
                    differentiator="Strong",
                ),
            ],
            recommendation="Go with A for MVP",
        )
        formatted = phase._format_options(sample_task, result)

        assert _SHAPE_OPTIONS_MARKER in formatted
        assert "Direction A: Simple" in formatted
        assert "Direction B: Complex" in formatted
        assert "**Differentiator:** Strong" in formatted
        assert "Go with A for MVP" in formatted
        assert "Reply with your selection" in formatted
