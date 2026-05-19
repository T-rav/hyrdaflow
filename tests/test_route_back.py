"""Tests for route_back.RouteBackCoordinator (#6423)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from issue_cache import CacheRecordKind, IssueCache

# ---------------------------------------------------------------------------
# FakeRouteBackCounter lives in src/mockworld/fakes/ (ADR-0047).
# InMemoryRouteBackCounter is a backward-compat alias in tests/helpers.py.
# ---------------------------------------------------------------------------
from mockworld.fakes.fake_route_back_counter import (
    FakeRouteBackCounter as InMemoryRouteBackCounter,
)
from route_back import (
    RouteBackCoordinator,
    RouteBackCounterPort,
    RouteBackOutcome,
)


def _coordinator(
    tmp_path: Path,
    *,
    max_route_backs: int = 2,
    counter: RouteBackCounterPort | None = None,
    diagnose_label: str = "",
) -> tuple[RouteBackCoordinator, IssueCache, AsyncMock, InMemoryRouteBackCounter]:
    cache = IssueCache(tmp_path / "cache", enabled=True)
    prs = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    counter_impl = counter if counter is not None else InMemoryRouteBackCounter()
    coordinator = RouteBackCoordinator(
        cache=cache,
        prs=prs,
        counter=counter_impl,
        hitl_label="hydraflow-hitl",
        diagnose_label=diagnose_label,
        max_route_backs=max_route_backs,
    )
    return coordinator, cache, prs, counter_impl  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# ROUTED outcome
# ---------------------------------------------------------------------------


class TestRouteBackRouted:
    @pytest.mark.asyncio
    async def test_first_route_back_is_routed(self, tmp_path: Path) -> None:
        coordinator, cache, prs, counter = _coordinator(tmp_path)
        result = await coordinator.route_back(
            42,
            from_stage="ready",
            to_stage="plan",
            reason="missing reproduction",
            feedback_context="add tests/regressions/test_issue_42.py",
        )
        assert result.outcome == RouteBackOutcome.ROUTED
        assert result.counter == 1
        assert "missing" in result.reason
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "plan")

    @pytest.mark.asyncio
    async def test_cache_record_written_on_route_back(self, tmp_path: Path) -> None:
        coordinator, cache, prs, _ = _coordinator(tmp_path)
        await coordinator.route_back(
            42,
            from_stage="ready",
            to_stage="plan",
            reason="critical findings",
            feedback_context="fix the logic",
        )
        history = cache.read_history(42)
        assert len(history) == 1
        assert history[0].kind == CacheRecordKind.ROUTE_BACK
        assert history[0].payload["from_stage"] == "ready"
        assert history[0].payload["to_stage"] == "plan"
        assert history[0].payload["feedback_context"] == "fix the logic"
        assert "critical" in history[0].payload["reason"]

    @pytest.mark.asyncio
    async def test_counter_increments_across_calls(self, tmp_path: Path) -> None:
        coordinator, _, _, counter = _coordinator(tmp_path, max_route_backs=5)
        r1 = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r1"
        )
        r2 = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r2"
        )
        r3 = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r3"
        )
        assert (r1.counter, r2.counter, r3.counter) == (1, 2, 3)
        assert counter.get_route_back_count(42) == 3
        assert all(r.outcome == RouteBackOutcome.ROUTED for r in (r1, r2, r3))

    @pytest.mark.asyncio
    async def test_counter_independent_per_issue(self, tmp_path: Path) -> None:
        coordinator, _, _, counter = _coordinator(tmp_path)
        await coordinator.route_back(1, from_stage="ready", to_stage="plan", reason="r")
        await coordinator.route_back(2, from_stage="ready", to_stage="plan", reason="r")
        assert counter.get_route_back_count(1) == 1
        assert counter.get_route_back_count(2) == 1


# ---------------------------------------------------------------------------
# ESCALATED outcome
# ---------------------------------------------------------------------------


class TestRouteBackEscalated:
    @pytest.mark.asyncio
    async def test_escalates_when_counter_exceeds_cap(self, tmp_path: Path) -> None:
        """With max_route_backs=2, the first two route-backs advance,
        the third (count=3, > 2) escalates."""
        coordinator, _, prs, counter = _coordinator(tmp_path, max_route_backs=2)
        await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r1"
        )
        await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r2"
        )
        third = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r3"
        )

        assert third.outcome == RouteBackOutcome.ESCALATED
        assert third.counter == 3
        assert "cap exceeded" in third.reason
        assert "ready" in third.reason

        # Label swap was called with the HITL label, not the upstream stage.
        calls = prs.swap_pipeline_labels.await_args_list
        assert calls[-1].args == (42, "hydraflow-hitl")

    @pytest.mark.asyncio
    async def test_escalation_with_cap_of_zero_escalates_immediately(
        self, tmp_path: Path
    ) -> None:
        """max_route_backs=0 is a valid config for 'no route-backs
        allowed; everything escalates on first failure'."""
        coordinator, _, prs, _ = _coordinator(tmp_path, max_route_backs=0)
        result = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="boom"
        )
        assert result.outcome == RouteBackOutcome.ESCALATED
        assert result.counter == 1
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-hitl")

    @pytest.mark.asyncio
    async def test_cache_record_written_even_on_escalation(
        self, tmp_path: Path
    ) -> None:
        """The audit trail must capture the route-back attempt even
        when it escalates — the feedback context is still useful for
        the human reviewer."""
        coordinator, cache, _, _ = _coordinator(tmp_path, max_route_backs=0)
        await coordinator.route_back(
            42,
            from_stage="ready",
            to_stage="plan",
            reason="critical",
            feedback_context="fix this",
        )
        history = cache.read_history(42)
        assert len(history) == 1
        assert history[0].kind == CacheRecordKind.ROUTE_BACK
        assert history[0].payload["feedback_context"] == "fix this"


# ---------------------------------------------------------------------------
# FAILED outcome
# ---------------------------------------------------------------------------


class TestRouteBackFailed:
    @pytest.mark.asyncio
    async def test_label_swap_failure_rolls_back_counter(self, tmp_path: Path) -> None:
        """Label swap failures must roll the counter back to its
        pre-attempt value. Without rollback, transient `gh` network
        blips would consume the route-back budget without any actual
        route-back happening, causing spurious HITL escalation."""
        coordinator, _, prs, counter = _coordinator(tmp_path)
        prs.swap_pipeline_labels = AsyncMock(
            side_effect=RuntimeError("gh network blip")
        )

        result = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r"
        )
        assert result.outcome == RouteBackOutcome.FAILED
        assert "gh network blip" in result.reason
        # Counter was rolled back to 0 because the label swap failed.
        assert counter.get_route_back_count(42) == 0
        assert result.counter == 0

    @pytest.mark.asyncio
    async def test_repeated_label_swap_failures_do_not_burn_budget(
        self, tmp_path: Path
    ) -> None:
        """Two consecutive label-swap failures must NOT escalate to HITL.
        With rollback, both attempts find the counter at 0 going in,
        increment to 1, fail the swap, and roll back to 0."""
        coordinator, _, prs, counter = _coordinator(tmp_path, max_route_backs=2)
        prs.swap_pipeline_labels = AsyncMock(side_effect=RuntimeError("network down"))

        for _ in range(5):
            result = await coordinator.route_back(
                42, from_stage="ready", to_stage="plan", reason="r"
            )
            assert result.outcome == RouteBackOutcome.FAILED

        # Counter is still 0 after 5 failed attempts — the budget is intact.
        assert counter.get_route_back_count(42) == 0

    @pytest.mark.asyncio
    async def test_subsequent_successful_route_back_after_failure(
        self, tmp_path: Path
    ) -> None:
        """After a label-swap failure rolls back, a later successful
        route-back must get count=1 (not count=2 from a leaked
        increment)."""
        coordinator, _, prs, counter = _coordinator(tmp_path)
        # First call fails.
        prs.swap_pipeline_labels = AsyncMock(side_effect=RuntimeError("blip"))
        await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r"
        )
        # Network recovers.
        prs.swap_pipeline_labels = AsyncMock()
        result = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r"
        )
        assert result.outcome == RouteBackOutcome.ROUTED
        assert result.counter == 1
        assert counter.get_route_back_count(42) == 1

    @pytest.mark.asyncio
    async def test_counter_failure_returns_failed_without_label_swap(
        self, tmp_path: Path
    ) -> None:
        """If the counter store fails, we don't attempt anything else.
        No label swap, no cache record — the issue stays in its
        current state so the next cycle can retry."""

        class _BrokenCounter:
            def get_route_back_count(self, issue_id: int) -> int:
                del issue_id
                return 0

            def increment_route_back_count(self, issue_id: int) -> int:
                del issue_id
                raise RuntimeError("counter store down")

        coordinator, cache, prs, _ = _coordinator(tmp_path, counter=_BrokenCounter())

        result = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r"
        )
        assert result.outcome == RouteBackOutcome.FAILED
        assert "counter" in result.reason
        prs.swap_pipeline_labels.assert_not_awaited()
        assert cache.read_history(42) == []

    @pytest.mark.asyncio
    async def test_cache_write_failure_does_not_prevent_label_swap(
        self, tmp_path: Path
    ) -> None:
        """Cache is best-effort. If the cache write raises, the label
        swap still happens — the audit trail is less important than
        the pipeline making progress."""
        coordinator, cache, prs, _ = _coordinator(tmp_path)

        # Replace the cache's record_route_back with one that raises.
        def _boom(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("disk full")

        cache.record_route_back = _boom  # type: ignore[assignment]

        result = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r"
        )
        assert result.outcome == RouteBackOutcome.ROUTED
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "plan")


# ---------------------------------------------------------------------------
# Escalation label failure
# ---------------------------------------------------------------------------


class TestEscalationLabelFailure:
    @pytest.mark.asyncio
    async def test_hitl_label_failure_returns_failed(self, tmp_path: Path) -> None:
        coordinator, _, prs, _ = _coordinator(tmp_path, max_route_backs=0)
        prs.swap_pipeline_labels = AsyncMock(side_effect=RuntimeError("gh error"))

        result = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r"
        )
        assert result.outcome == RouteBackOutcome.FAILED
        assert "escalation label swap failed" in result.reason


# ---------------------------------------------------------------------------
# Diagnose-first escalation chain
# ---------------------------------------------------------------------------


class TestDiagnoseEscalationChain:
    """When ``diagnose_label`` is configured, the coordinator should
    try to swap to diagnose FIRST when route-backs are exhausted, and
    only fall back to HITL if the diagnose swap fails. Matches the
    existing ``PipelineEscalator`` pattern in src/phase_utils.py and
    keeps autonomy by giving the diagnostic agent one more shot at
    triaging the failure before requiring a human."""

    @pytest.mark.asyncio
    async def test_escalates_to_diagnose_first(self, tmp_path: Path) -> None:
        coordinator, _, prs, _ = _coordinator(
            tmp_path,
            max_route_backs=0,
            diagnose_label="hydraflow-diagnose",
        )

        result = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r"
        )

        assert result.outcome == RouteBackOutcome.ESCALATED
        # Diagnose label was applied — NOT HITL.
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-diagnose")
        assert "diagnose" in result.reason

    @pytest.mark.asyncio
    async def test_falls_back_to_hitl_when_diagnose_swap_fails(
        self, tmp_path: Path
    ) -> None:
        coordinator, _, prs, _ = _coordinator(
            tmp_path,
            max_route_backs=0,
            diagnose_label="hydraflow-diagnose",
        )

        # First call (diagnose) raises, second call (HITL) succeeds.
        call_count = {"n": 0}

        async def _swap(issue_id: int, label: str) -> None:
            del issue_id, label
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("diagnose label swap failed")

        prs.swap_pipeline_labels = AsyncMock(side_effect=_swap)

        result = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r"
        )

        assert result.outcome == RouteBackOutcome.ESCALATED
        # Both diagnose AND hitl swaps were attempted, in that order.
        calls = prs.swap_pipeline_labels.await_args_list
        assert len(calls) == 2
        assert calls[0].args == (42, "hydraflow-diagnose")
        assert calls[1].args == (42, "hydraflow-hitl")

    @pytest.mark.asyncio
    async def test_returns_failed_when_both_diagnose_and_hitl_fail(
        self, tmp_path: Path
    ) -> None:
        coordinator, _, prs, _ = _coordinator(
            tmp_path,
            max_route_backs=0,
            diagnose_label="hydraflow-diagnose",
        )
        prs.swap_pipeline_labels = AsyncMock(
            side_effect=RuntimeError("everything is on fire")
        )

        result = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r"
        )

        assert result.outcome == RouteBackOutcome.FAILED
        # Both swaps were attempted before giving up.
        assert prs.swap_pipeline_labels.await_count == 2

    @pytest.mark.asyncio
    async def test_no_diagnose_label_skips_directly_to_hitl(
        self, tmp_path: Path
    ) -> None:
        """Empty diagnose_label preserves the original direct-HITL
        behavior — operators that don't want the diagnose hop can
        opt out by passing diagnose_label=''."""
        coordinator, _, prs, _ = _coordinator(
            tmp_path,
            max_route_backs=0,
            diagnose_label="",  # disabled
        )

        result = await coordinator.route_back(
            42, from_stage="ready", to_stage="plan", reason="r"
        )

        assert result.outcome == RouteBackOutcome.ESCALATED
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-hitl")


# ---------------------------------------------------------------------------
# max_route_backs property
# ---------------------------------------------------------------------------


class TestMaxRouteBacksProperty:
    def test_exposes_configured_cap(self, tmp_path: Path) -> None:
        coordinator, _, _, _ = _coordinator(tmp_path, max_route_backs=7)
        assert coordinator.max_route_backs == 7
