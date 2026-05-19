"""ComplexityGate routing tests — DiscoverPhase entry bypass for trivial issues.

The earlier-adversarial pipeline inserts a ComplexityGate at the top of
the discover stage. TRIVIAL issues bypass Discovery + Shape entirely and
transition straight to ``hydraflow-ready``. LOAD_BEARING issues proceed
through the full Discovery flow.

Backward-compat: phases without a gate attached behave as before.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.adversarial_labels import (
    ADVERSARIAL_ASSUMPTION_REVIEW_LABEL,
    ADVERSARIAL_COUNCIL_REVIEW_LABEL,
    ADVERSARIAL_SPEC_GATE_LABEL,
    LABELS_ADVERSARIAL_TRANSIENT,
)
from src.complexity_gate import ComplexityGate

from config import HydraFlowConfig
from discover_phase import DiscoverPhase
from models import Task


@pytest.fixture
def deps() -> dict:
    """Shared dependencies for DiscoverPhase."""
    return {
        "config": HydraFlowConfig(repo="test/repo"),
        "state": MagicMock(),
        "store": MagicMock(),
        "prs": AsyncMock(),
        "event_bus": AsyncMock(),
        "stop_event": asyncio.Event(),
    }


@pytest.fixture
def phase(deps: dict) -> DiscoverPhase:
    return DiscoverPhase(**deps)


def _trivial_issue() -> Task:
    return Task(
        id=42,
        title="Fix typo in README",
        body="Fix a typo.",
        tags=["hydraflow-discover", "hydraflow-typo"],
    )


def _load_bearing_issue() -> Task:
    return Task(
        id=43,
        title="Add new runner for X",
        body="Introduces a new runner for X with public interface.",
        tags=["hydraflow-discover", "hydraflow-load-bearing"],
    )


class TestTransientLabelsRegistry:
    def test_all_three_labels_present(self) -> None:
        """The three intra-stage adversarial labels are all exported."""
        assert ADVERSARIAL_ASSUMPTION_REVIEW_LABEL == "hydraflow-assumption-review"
        assert ADVERSARIAL_COUNCIL_REVIEW_LABEL == "hydraflow-council-review"
        assert ADVERSARIAL_SPEC_GATE_LABEL == "hydraflow-spec-gate"
        assert set(LABELS_ADVERSARIAL_TRANSIENT) == {
            "hydraflow-assumption-review",
            "hydraflow-council-review",
            "hydraflow-spec-gate",
        }

    def test_labels_are_not_stage_routing(self) -> None:
        """Transient labels must NOT appear in the IssueStore label map.

        These are intra-stage markers, not stage transitions — carrying
        one of these labels should not move the issue to a new queue.
        """
        from unittest.mock import MagicMock as MM

        from issue_store import IssueStore

        store = IssueStore.__new__(IssueStore)
        store._config = HydraFlowConfig(repo="test/repo")
        store._fetcher = MM()
        label_map = store._build_label_map()
        for label in LABELS_ADVERSARIAL_TRANSIENT:
            assert label not in label_map, (
                f"transient label {label!r} must not be a stage-routing label"
            )


class TestComplexityGateRouting:
    @pytest.mark.asyncio
    async def test_trivial_issue_bypasses_discover_and_shape(
        self, phase: DiscoverPhase, deps: dict
    ) -> None:
        """Trivial issue routes directly to hydraflow-ready, skipping
        Discovery + Shape adversarial stages."""
        issue = _trivial_issue()
        phase.attach_complexity_gate(ComplexityGate(llm=None))

        result = await phase._discover_single(issue)

        assert result == 1
        # Bypass transition: ready, not shape.
        deps["prs"].transition.assert_awaited_once_with(42, "ready")
        deps["store"].enqueue_transition.assert_called_once_with(issue, "ready")
        # No research brief comment, no discovered counter — the gate
        # bypassed the discovery flow.
        deps["prs"].post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_load_bearing_issue_proceeds_through_discovery(
        self, phase: DiscoverPhase, deps: dict
    ) -> None:
        """Load-bearing issue does NOT bypass — it proceeds to shape per
        the canonical discovery flow."""
        issue = _load_bearing_issue()
        phase.attach_complexity_gate(ComplexityGate(llm=None))

        result = await phase._discover_single(issue)

        assert result == 1
        # Canonical flow: discover transitions to shape.
        deps["prs"].transition.assert_awaited_once_with(43, "shape")
        deps["store"].enqueue_transition.assert_called_once_with(issue, "shape")
        # Research brief was posted.
        deps["prs"].post_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_gate_attached_behaves_as_before(
        self, phase: DiscoverPhase, deps: dict
    ) -> None:
        """Backward-compat: without a gate attached, even trivial-looking
        issues proceed through Discovery normally."""
        issue = _trivial_issue()
        # No attach_complexity_gate call.

        result = await phase._discover_single(issue)

        assert result == 1
        # Canonical flow — gate never ran.
        deps["prs"].transition.assert_awaited_once_with(42, "shape")
        deps["store"].enqueue_transition.assert_called_once_with(issue, "shape")
