"""Tests for precondition_gate.PreconditionGate (#6423).

Verifies the consumer-side filter that runs check_preconditions and
routes failures via RouteBackCoordinator. Uses real IssueCache against
tmp_path and an in-memory counter so the tests cover the full
cache → gate → coordinator → counter chain end-to-end.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from issue_cache import CacheRecordKind, IssueCache
from models import Task
from precondition_gate import PreconditionGate
from route_back import RouteBackCoordinator
from stage_preconditions import Stage
from tests.helpers import InMemoryRouteBackCounter

# ---------------------------------------------------------------------------
# Stubs — InMemoryRouteBackCounter is defined in tests/helpers.py to
# stay in sync with test_route_back.py and avoid drift between two
# parallel stubs implementing the same RouteBackCounterPort contract.
# ---------------------------------------------------------------------------


def _task(issue_id: int) -> Task:
    return Task(id=issue_id, title=f"Issue {issue_id}", body="body")


def _build_gate(
    tmp_path: Path,
    *,
    enabled: bool = True,
) -> tuple[PreconditionGate, IssueCache, AsyncMock, InMemoryRouteBackCounter]:
    cache = IssueCache(tmp_path / "cache", enabled=True)
    prs = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    counter = InMemoryRouteBackCounter()
    coordinator = RouteBackCoordinator(
        cache=cache,
        prs=prs,
        counter=counter,
        hitl_label="hydraflow-hitl",
        max_route_backs=2,
    )
    gate = PreconditionGate(
        cache=cache,
        coordinator=coordinator,
        enabled=enabled,
    )
    return gate, cache, prs, counter  # type: ignore[return-value]


def _seed_clean_ready(cache: IssueCache, issue_id: int) -> None:
    """Seed an issue with the records needed to pass Stage.READY."""
    cache.record_classification(
        issue_id,
        issue_type="feature",
        complexity_score=3,
        complexity_rank="low",
        routing_outcome="plan",
    )
    cache.record_plan_stored(issue_id, plan_text="a plan")
    cache.record_review_stored(issue_id, review_text="LGTM", has_blocking=False)


# ---------------------------------------------------------------------------
# Pass-through (enabled=False)
# ---------------------------------------------------------------------------


class TestDisabledGate:
    @pytest.mark.asyncio
    async def test_disabled_gate_returns_all_issues(self, tmp_path: Path) -> None:
        gate, _, prs, _ = _build_gate(tmp_path, enabled=False)
        issues = [_task(1), _task(2), _task(3)]
        result = await gate.filter_and_route(issues, Stage.READY)
        assert result == issues
        # No label swaps because the gate is disabled.
        prs.swap_pipeline_labels.assert_not_awaited()

    def test_disabled_gate_property(self, tmp_path: Path) -> None:
        gate, *_ = _build_gate(tmp_path, enabled=False)
        assert gate.enabled is False

    def test_enabled_gate_property(self, tmp_path: Path) -> None:
        gate, *_ = _build_gate(tmp_path, enabled=True)
        assert gate.enabled is True


# ---------------------------------------------------------------------------
# Pass / fail filtering
# ---------------------------------------------------------------------------


class TestFilterPasses:
    @pytest.mark.asyncio
    async def test_clean_issue_passes_ready_stage(self, tmp_path: Path) -> None:
        gate, cache, prs, counter = _build_gate(tmp_path)
        _seed_clean_ready(cache, 42)

        result = await gate.filter_and_route([_task(42)], Stage.READY)
        assert len(result) == 1
        assert result[0].id == 42
        prs.swap_pipeline_labels.assert_not_awaited()
        assert counter.get_route_back_count(42) == 0

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, tmp_path: Path) -> None:
        gate, *_ = _build_gate(tmp_path)
        result = await gate.filter_and_route([], Stage.READY)
        assert result == []


class TestFilterFails:
    @pytest.mark.asyncio
    async def test_missing_plan_blocks_and_routes_back(self, tmp_path: Path) -> None:
        gate, _, prs, counter = _build_gate(tmp_path)
        # Issue has no plan_stored — should fail has_plan.
        result = await gate.filter_and_route([_task(42)], Stage.READY)
        assert result == []
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "plan")
        assert counter.get_route_back_count(42) == 1

    @pytest.mark.asyncio
    async def test_blocking_review_routes_back_to_plan(self, tmp_path: Path) -> None:
        gate, cache, prs, _ = _build_gate(tmp_path)
        cache.record_classification(
            42,
            issue_type="feature",
            complexity_score=3,
            complexity_rank="low",
            routing_outcome="plan",
        )
        cache.record_plan_stored(42, plan_text="x")
        cache.record_review_stored(
            42, review_text="critical findings", has_blocking=True
        )

        result = await gate.filter_and_route([_task(42)], Stage.READY)
        assert result == []
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "plan")

    @pytest.mark.asyncio
    async def test_review_stage_routes_back_to_ready(self, tmp_path: Path) -> None:
        gate, _, prs, _ = _build_gate(tmp_path)
        # No plan_stored → has_plan fails. From REVIEW stage, that
        # should route back to "ready" (the upstream of REVIEW),
        # not to "plan".
        await gate.filter_and_route([_task(42)], Stage.REVIEW)
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "ready")


# ---------------------------------------------------------------------------
# Mixed batches
# ---------------------------------------------------------------------------


class TestMixedBatch:
    @pytest.mark.asyncio
    async def test_mixed_batch_returns_only_passing_issues(
        self, tmp_path: Path
    ) -> None:
        gate, cache, prs, counter = _build_gate(tmp_path)
        # Three issues: 1 passes, 2 fails (no plan), 3 passes.
        _seed_clean_ready(cache, 1)
        _seed_clean_ready(cache, 3)

        result = await gate.filter_and_route(
            [_task(1), _task(2), _task(3)],
            Stage.READY,
        )

        passed_ids = {t.id for t in result}
        assert passed_ids == {1, 3}
        # Only issue 2 was routed back.
        prs.swap_pipeline_labels.assert_awaited_once_with(2, "plan")
        assert counter.get_route_back_count(2) == 1
        assert counter.get_route_back_count(1) == 0
        assert counter.get_route_back_count(3) == 0

    @pytest.mark.asyncio
    async def test_mixed_batch_preserves_order_of_passing_issues(
        self, tmp_path: Path
    ) -> None:
        gate, cache, *_ = _build_gate(tmp_path)
        for i in (1, 3, 5, 7):
            _seed_clean_ready(cache, i)

        # Interleave passing (odd) and failing (even) issues.
        result = await gate.filter_and_route(
            [_task(1), _task(2), _task(3), _task(4), _task(5), _task(6), _task(7)],
            Stage.READY,
        )
        assert [t.id for t in result] == [1, 3, 5, 7]


# ---------------------------------------------------------------------------
# Cache audit
# ---------------------------------------------------------------------------


class TestCacheAudit:
    @pytest.mark.asyncio
    async def test_route_back_writes_cache_record(self, tmp_path: Path) -> None:
        gate, cache, *_ = _build_gate(tmp_path)
        await gate.filter_and_route([_task(42)], Stage.READY)

        history = cache.read_history(42)
        # Just the route_back record (no other writes for issue 42).
        kinds = [r.kind for r in history]
        assert CacheRecordKind.ROUTE_BACK in kinds
        rb_record = next(r for r in history if r.kind == CacheRecordKind.ROUTE_BACK)
        assert rb_record.payload["from_stage"] == "ready"
        assert rb_record.payload["to_stage"] == "plan"
        assert "no plan_stored" in rb_record.payload["reason"]


# ---------------------------------------------------------------------------
# Coordinator failure handling
# ---------------------------------------------------------------------------


class TestCoordinatorFailureHandling:
    @pytest.mark.asyncio
    async def test_coordinator_exception_drops_issue_from_batch(
        self, tmp_path: Path
    ) -> None:
        """If route_back itself raises, the issue is still excluded
        from the returned list — the caller never processes a gated
        issue, even when the route-back itself fails."""
        gate, _, prs, _ = _build_gate(tmp_path)
        prs.swap_pipeline_labels = AsyncMock(side_effect=RuntimeError("boom"))

        result = await gate.filter_and_route([_task(42)], Stage.READY)
        # Issue 42 fails preconditions; route-back raises (label swap
        # failure → coordinator returns FAILED, not raises). Either
        # way, 42 must NOT appear in the result.
        assert result == []

    @pytest.mark.asyncio
    async def test_passing_issue_unaffected_by_failing_neighbor(
        self, tmp_path: Path
    ) -> None:
        gate, cache, prs, _ = _build_gate(tmp_path)
        _seed_clean_ready(cache, 1)
        # Issue 2 has no records → fails the gate.

        # Make label_swap raise on the first call (for issue 2).
        call_count = {"n": 0}

        async def _maybe_raise(issue_id: int, label: str) -> None:
            del issue_id, label
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient")

        prs.swap_pipeline_labels = AsyncMock(side_effect=_maybe_raise)

        result = await gate.filter_and_route([_task(1), _task(2)], Stage.READY)
        # Issue 1 still passes despite issue 2's route-back failing.
        assert [t.id for t in result] == [1]
