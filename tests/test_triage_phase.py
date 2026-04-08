"""Tests for triage_phase.py — TriagePhase."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

from tests.conftest import TaskFactory, TriageResultFactory
from tests.helpers import make_triage_phase, supply_once

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from models import TriageResult


# ---------------------------------------------------------------------------
# Triage phase
# ---------------------------------------------------------------------------


class TestTriagePhase:
    """Tests for TriagePhase.triage_issues()."""

    @pytest.mark.asyncio
    async def test_triage_promotes_ready_issue_to_planning(
        self, config: HydraFlowConfig
    ) -> None:
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(id=1, title="Implement feature X", body="A" * 100)

        triage.evaluate = AsyncMock(
            return_value=TriageResultFactory.create(issue_number=1, ready=True)
        )
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        triage.evaluate.assert_awaited_once_with(issue)
        prs.transition.assert_called_once_with(1, "plan")
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_triage_parks_unready_issue_instead_of_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """Unclear issues should be parked, not escalated to HITL."""
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(id=2, title="Fix the bug please", body="")

        triage.evaluate = AsyncMock(
            return_value=TriageResultFactory.create(
                issue_number=2,
                ready=False,
                reasons=["Body is too short or empty (minimum 50 characters)"],
            )
        )
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        prs.swap_pipeline_labels.assert_called_once_with(2, config.parked_label[0])
        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Needs More Information" in comment
        assert "Body is too short" in comment

    @pytest.mark.asyncio
    async def test_triage_park_does_not_record_hitl_state(
        self, config: HydraFlowConfig
    ) -> None:
        """Parked issues should NOT have HITL origin/cause set."""
        phase, state, triage, _prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(id=2, title="Fix the bug please", body="")

        triage.evaluate = AsyncMock(
            return_value=TriageResultFactory.create(
                issue_number=2,
                ready=False,
                reasons=["Body is too short or empty (minimum 50 characters)"],
            )
        )
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        assert state.get_hitl_origin(2) is None
        assert state.get_hitl_cause(2) is None

    @pytest.mark.asyncio
    async def test_triage_closes_duplicate_issue(self, config: HydraFlowConfig) -> None:
        """When an open issue with the same title exists, close as duplicate."""
        phase, state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(id=50, title="Fix login timeout", body="A" * 100)

        prs.find_existing_issue = AsyncMock(return_value=30)
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        # Should close without even evaluating triage
        triage.evaluate.assert_not_called()
        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Duplicate" in comment
        assert "#30" in comment

    @pytest.mark.asyncio
    async def test_triage_stops_when_stop_event_set(
        self, config: HydraFlowConfig
    ) -> None:
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issues = [
            TaskFactory.create(id=1, title="Issue one long enough", body="A" * 100),
            TaskFactory.create(id=2, title="Issue two long enough", body="B" * 100),
        ]

        call_count = 0

        async def evaluate_then_stop(issue: object) -> TriageResult:
            nonlocal call_count
            call_count += 1
            phase._stop_event.set()  # Stop after first evaluation
            return TriageResultFactory.create(issue_number=1, ready=True)

        triage.evaluate = AsyncMock(side_effect=evaluate_then_stop)
        store.get_triageable = supply_once(issues)

        await phase.triage_issues()

        # Only the first issue should be evaluated; second skipped due to stop
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_triage_skips_when_no_issues_found(
        self, config: HydraFlowConfig
    ) -> None:
        phase, _state, _triage, prs, store, _stop = make_triage_phase(config)

        store.get_triageable = lambda _max_count: []  # type: ignore[method-assign]

        await phase.triage_issues()

        prs.remove_label.assert_not_called()

    @pytest.mark.asyncio
    async def test_triage_marks_active_during_processing(
        self, config: HydraFlowConfig
    ) -> None:
        """Triage should mark issues active to prevent re-queuing by refresh."""
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(id=1, title="Triage test", body="A" * 100)

        was_active_during_evaluate = False

        async def check_active(issue_obj: object) -> TriageResult:
            nonlocal was_active_during_evaluate
            was_active_during_evaluate = store.is_active(1)
            return TriageResultFactory.create(issue_number=1, ready=True)

        triage.evaluate = AsyncMock(side_effect=check_active)
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        assert was_active_during_evaluate, "Issue should be marked active during triage"
        assert not store.is_active(1), "Issue should be released after triage"

    @pytest.mark.asyncio
    async def test_triage_runs_concurrently_with_semaphore(
        self, config: HydraFlowConfig
    ) -> None:
        """Multiple issues should be triaged concurrently up to max_triagers."""
        config.max_triagers = 2
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issues = [
            TaskFactory.create(id=i, title=f"Issue {i}", body="A" * 100)
            for i in range(1, 4)
        ]

        concurrency_high_water = 0
        active_count = 0
        lock = asyncio.Lock()

        async def track_concurrency(issue: object) -> TriageResult:
            nonlocal concurrency_high_water, active_count
            async with lock:
                active_count += 1
                concurrency_high_water = max(concurrency_high_water, active_count)
            await asyncio.sleep(0.01)
            async with lock:
                active_count -= 1
            return TriageResultFactory.create(
                issue_number=getattr(issue, "id", 0), ready=True
            )

        triage.evaluate = AsyncMock(side_effect=track_concurrency)
        store.get_triageable = supply_once(*[[i] for i in issues])

        processed = await phase.triage_issues()

        assert processed == 3
        # Semaphore allows up to 2 concurrent, so high water should be <= 2
        assert concurrency_high_water <= 2
        # With 3 issues and semaphore=2, at least 2 should run in parallel
        assert concurrency_high_water == 2

    @pytest.mark.asyncio
    async def test_adr_issue_routes_to_ready_when_shape_is_valid(
        self, config: HydraFlowConfig
    ) -> None:
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(
            id=77,
            title="[ADR] Adopt event-sourced state snapshots",
            body=(
                "## Context\n"
                "Current pipeline state persistence causes replay costs and stale views.\n\n"
                "## Decision\n"
                "Adopt periodic event-sourced snapshots with compaction to reduce replay.\n\n"
                "## Consequences\n"
                "Adds compaction complexity but improves startup and dashboard freshness."
            ),
        )
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        triage.evaluate.assert_not_awaited()
        prs.transition.assert_called_once_with(77, "ready")
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_adr_issue_parked_when_shape_invalid(
        self, config: HydraFlowConfig
    ) -> None:
        """Invalid ADR shape should park the issue, not escalate to HITL."""
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(
            id=78,
            title="[ADR] Simplify build graph",
            body="Need to simplify this soon.",
        )
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        triage.evaluate.assert_not_awaited()
        prs.swap_pipeline_labels.assert_called_once_with(78, config.parked_label[0])
        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Needs More Information" in comment
        assert "Missing required ADR sections" in comment

    @pytest.mark.asyncio
    async def test_adr_issue_closed_as_duplicate_when_topic_exists_on_disk(
        self, config: HydraFlowConfig
    ) -> None:
        """ADR issue whose topic already exists in docs/adr/ is closed at triage."""
        adr_dir = config.repo_root / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-event-sourced-state-snapshots.md").write_text("# ADR\n")

        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(
            id=79,
            title="[ADR] Draft decision from memory #100: Event sourced state snapshots",
            body=(
                "## Context\nSome context.\n\n"
                "## Decision\nAdopt event sourced snapshots for state persistence.\n\n"
                "## Consequences\nReduces replay cost."
            ),
        )
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        triage.evaluate.assert_not_awaited()
        prs.transition.assert_not_called()
        prs.close_task.assert_called_once_with(79)
        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Duplicate" in comment

    @pytest.mark.asyncio
    async def test_triage_infra_error_does_not_escalate_to_hitl(
        self,
        config: HydraFlowConfig,
    ) -> None:
        """RuntimeError (empty LLM response) should NOT send the issue to HITL.

        The issue should stay in the find queue for retry on the next cycle.
        """
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(id=99, title="Well-formed issue", body="A" * 200)

        triage.evaluate = AsyncMock(
            side_effect=RuntimeError("LLM returned empty response")
        )
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        # Issue should NOT be escalated to HITL
        prs.swap_pipeline_labels.assert_not_called()
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_triage_routes_vague_issue_to_discover(
        self, config: HydraFlowConfig
    ) -> None:
        """Vague issues with needs_discovery=True route to discover."""
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(
            id=10, title="Build a better Calendly", body="A" * 100
        )

        triage.evaluate = AsyncMock(
            return_value=TriageResultFactory.create(
                issue_number=10,
                ready=True,
                needs_discovery=True,
                clarity_score=3,
            )
        )
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        prs.transition.assert_called_once_with(10, "discover")

    @pytest.mark.asyncio
    async def test_triage_routes_low_clarity_to_discover(
        self, config: HydraFlowConfig
    ) -> None:
        """Issues with low clarity_score route to discover even if ready=True."""
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(
            id=11, title="Improve onboarding experience", body="A" * 100
        )

        triage.evaluate = AsyncMock(
            return_value=TriageResultFactory.create(
                issue_number=11,
                ready=True,
                clarity_score=4,  # Below default threshold of 7
            )
        )
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        prs.transition.assert_called_once_with(11, "discover")

    @pytest.mark.asyncio
    async def test_triage_clear_issue_still_routes_to_plan(
        self, config: HydraFlowConfig
    ) -> None:
        """Clear issues with high clarity score route to plan as before."""
        phase, _state, triage, prs, store, _stop = make_triage_phase(config)
        issue = TaskFactory.create(
            id=12, title="Add pagination to users endpoint", body="A" * 100
        )

        triage.evaluate = AsyncMock(
            return_value=TriageResultFactory.create(
                issue_number=12,
                ready=True,
                clarity_score=9,
            )
        )
        store.get_triageable = supply_once([issue])

        await phase.triage_issues()

        prs.transition.assert_called_once_with(12, "plan")


class TestTriagePhaseBatchScaling:
    """Pool respects max_triagers for concurrency control."""

    @pytest.mark.asyncio
    async def test_supply_called_with_one_for_pool(
        self, config: HydraFlowConfig
    ) -> None:
        """get_triageable should be called with 1 (pool fetches one at a time)."""
        from unittest.mock import MagicMock

        phase, _state, _triage, _prs, store, _stop = make_triage_phase(config)
        store.get_triageable = MagicMock(return_value=[])  # type: ignore[method-assign]

        config.max_triagers = 4  # type: ignore[assignment]
        await phase.triage_issues()

        store.get_triageable.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_supply_always_called_with_one(self, config: HydraFlowConfig) -> None:
        """Regardless of max_triagers, supply fetches 1 at a time."""
        from unittest.mock import MagicMock

        phase, _state, _triage, _prs, store, _stop = make_triage_phase(config)
        store.get_triageable = MagicMock(return_value=[])  # type: ignore[method-assign]

        config.max_triagers = 1  # type: ignore[assignment]
        await phase.triage_issues()
        store.get_triageable.assert_called_with(1)

        config.max_triagers = 5  # type: ignore[assignment]
        await phase.triage_issues()
        store.get_triageable.assert_called_with(1)


class TestComplexityRank:
    """Tests for TriagePhase._complexity_rank threshold mapping (#6422).

    The "high" boundary is tied to
    config.epic_decompose_complexity_threshold so the cache rank
    label agrees with the epic-decomposition routing decision.
    """

    def test_high_threshold_matches_config(self, config: HydraFlowConfig) -> None:
        phase, *_ = make_triage_phase(config)
        threshold = config.epic_decompose_complexity_threshold
        assert phase._complexity_rank(threshold) == "high"
        assert phase._complexity_rank(threshold + 1) == "high"

    def test_score_below_high_threshold_is_medium(
        self, config: HydraFlowConfig
    ) -> None:
        phase, *_ = make_triage_phase(config)
        threshold = config.epic_decompose_complexity_threshold
        # Just below the high threshold should NOT be high.
        assert phase._complexity_rank(threshold - 1) != "high"

    def test_medium_low_trivial_thresholds(self, config: HydraFlowConfig) -> None:
        phase, *_ = make_triage_phase(config)
        # Boundary values for the lower thresholds.
        assert phase._complexity_rank(5) == "medium"
        assert phase._complexity_rank(4) == "low"
        assert phase._complexity_rank(2) == "low"
        assert phase._complexity_rank(1) == "trivial"
        assert phase._complexity_rank(0) == "trivial"

    def test_lowered_high_threshold_changes_boundary(
        self, config: HydraFlowConfig
    ) -> None:
        """If an operator lowers epic_decompose_complexity_threshold,
        scores at that level should newly be classified "high" — proves
        the rank label is tied to config, not a hardcoded constant."""
        phase, *_ = make_triage_phase(config)
        # Use object.__setattr__ to bypass any frozen-model guard.
        object.__setattr__(config, "epic_decompose_complexity_threshold", 6)
        assert phase._complexity_rank(6) == "high"
        assert phase._complexity_rank(7) == "high"
        assert phase._complexity_rank(5) == "medium"
