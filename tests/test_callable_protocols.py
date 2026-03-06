"""Tests for issue #1058 — Callable signature Protocol replacements.

Verifies that the new Protocol classes (EscalateFn, PublishFn, CiGateFn,
StatusCallback, WorkFn) are importable, structurally compatible with
AsyncMock/MagicMock, and match the actual implementation method signatures.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from models import (
    CiGateFn,
    EscalateFn,
    GitHubIssue,
    PRInfo,
    PublishFn,
    ReviewResult,
    StatusCallback,
    Task,
    WorkFn,
)

# ---------------------------------------------------------------------------
# EscalateFn Protocol
# ---------------------------------------------------------------------------


class TestEscalateFnProtocol:
    """Tests for the EscalateFn Protocol."""

    def test_escalate_fn_importable_from_models(self) -> None:
        """EscalateFn should be importable from models."""
        assert EscalateFn is not None

    @pytest.mark.asyncio
    async def test_async_mock_satisfies_protocol(self) -> None:
        """AsyncMock should work as EscalateFn with the expected args."""
        fn: EscalateFn = AsyncMock()
        await fn(
            1,
            2,
            cause="test",
            origin_label="review",
            comment="test comment",
            event_cause="test_cause",
        )
        fn.assert_called_once()  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_async_mock_with_all_optional_args(self) -> None:
        """AsyncMock should accept all optional keyword args."""
        fn: EscalateFn = AsyncMock()
        await fn(
            1,
            2,
            cause="test",
            origin_label="review",
            comment="test comment",
            post_on_pr=False,
            event_cause="test_cause",
            extra_event_data={"key": "value"},
            task=Task(id=1, title="foo"),
        )
        fn.assert_called_once()  # type: ignore[union-attr]

    def test_signature_matches_review_phase(self) -> None:
        """EscalateFn Protocol params should match ReviewPhase._escalate_to_hitl."""
        from review_phase import ReviewPhase

        method_sig = inspect.signature(ReviewPhase._escalate_to_hitl)
        method_params = list(method_sig.parameters.keys())
        # Remove 'self'
        method_params.remove("self")

        protocol_sig = inspect.signature(EscalateFn.__call__)
        protocol_params = list(protocol_sig.parameters.keys())
        protocol_params.remove("self")

        assert method_params == protocol_params


# ---------------------------------------------------------------------------
# PublishFn Protocol
# ---------------------------------------------------------------------------


class TestPublishFnProtocol:
    """Tests for the PublishFn Protocol."""

    def test_publish_fn_importable_from_models(self) -> None:
        """PublishFn should be importable from models."""
        assert PublishFn is not None

    @pytest.mark.asyncio
    async def test_async_mock_satisfies_protocol(self) -> None:
        """AsyncMock should work as PublishFn with (pr, worker_id, status)."""
        fn: PublishFn = AsyncMock()
        pr = PRInfo(number=1, issue_number=1, branch="test")
        await fn(pr, 0, "start")
        fn.assert_called_once_with(pr, 0, "start")  # type: ignore[union-attr]

    def test_signature_matches_review_phase(self) -> None:
        """PublishFn Protocol params should match ReviewPhase._publish_review_status."""
        from review_phase import ReviewPhase

        method_sig = inspect.signature(ReviewPhase._publish_review_status)
        method_params = list(method_sig.parameters.keys())
        method_params.remove("self")

        protocol_sig = inspect.signature(PublishFn.__call__)
        protocol_params = list(protocol_sig.parameters.keys())
        protocol_params.remove("self")

        assert method_params == protocol_params


# ---------------------------------------------------------------------------
# CiGateFn Protocol
# ---------------------------------------------------------------------------


class TestCiGateFnProtocol:
    """Tests for the CiGateFn Protocol."""

    def test_ci_gate_fn_importable_from_models(self) -> None:
        """CiGateFn should be importable from models."""
        assert CiGateFn is not None

    @pytest.mark.asyncio
    async def test_async_mock_satisfies_protocol(self) -> None:
        """AsyncMock(return_value=True) should work as CiGateFn."""
        fn: CiGateFn = AsyncMock(return_value=True)
        pr = PRInfo(number=1, issue_number=1, branch="test")
        issue = GitHubIssue(number=1, title="test")
        result = ReviewResult(pr_number=1, issue_number=1)
        ok = await fn(pr, issue, Path("/tmp/wt"), result, 0)
        assert ok is True

    def test_signature_matches_review_phase(self) -> None:
        """CiGateFn Protocol params should match ReviewPhase.wait_and_fix_ci."""
        from review_phase import ReviewPhase

        method_sig = inspect.signature(ReviewPhase.wait_and_fix_ci)
        method_params = list(method_sig.parameters.keys())
        method_params.remove("self")

        protocol_sig = inspect.signature(CiGateFn.__call__)
        protocol_params = list(protocol_sig.parameters.keys())
        protocol_params.remove("self")

        assert method_params == protocol_params


# ---------------------------------------------------------------------------
# StatusCallback Protocol
# ---------------------------------------------------------------------------


class TestStatusCallbackProtocol:
    """Tests for the StatusCallback Protocol."""

    def test_status_callback_importable_from_models(self) -> None:
        """StatusCallback should be importable from models."""
        assert StatusCallback is not None

    def test_lambda_satisfies_protocol(self) -> None:
        """A lambda with matching signature should satisfy StatusCallback."""
        cb: StatusCallback = lambda name, status, details=None: None  # noqa: E731
        cb("worker", "ok", {"key": "value"})

    def test_callable_with_optional_details(self) -> None:
        """StatusCallback should allow calling without the details arg."""
        calls: list[tuple[str, str, dict[str, Any] | None]] = []

        def my_cb(
            name: str, status: str, details: dict[str, Any] | None = None
        ) -> None:
            calls.append((name, status, details))

        cb: StatusCallback = my_cb
        cb("worker", "ok")
        cb("worker", "error", None)
        cb("worker", "ok", {"key": "value"})
        assert len(calls) == 3
        assert calls[0] == ("worker", "ok", None)
        assert calls[1] == ("worker", "error", None)
        assert calls[2] == ("worker", "ok", {"key": "value"})

    def test_signature_matches_orchestrator(self) -> None:
        """StatusCallback Protocol params should match update_bg_worker_status."""
        from orchestrator import HydraFlowOrchestrator

        method_sig = inspect.signature(HydraFlowOrchestrator.update_bg_worker_status)
        method_params = list(method_sig.parameters.keys())
        method_params.remove("self")

        protocol_sig = inspect.signature(StatusCallback.__call__)
        protocol_params = list(protocol_sig.parameters.keys())
        protocol_params.remove("self")

        assert method_params == protocol_params


# ---------------------------------------------------------------------------
# WorkFn Protocol
# ---------------------------------------------------------------------------


class TestWorkFnProtocol:
    """Tests for the WorkFn Protocol."""

    def test_work_fn_importable_from_models(self) -> None:
        """WorkFn should be importable from models."""
        assert WorkFn is not None

    @pytest.mark.asyncio
    async def test_async_mock_satisfies_protocol(self) -> None:
        """AsyncMock should work as a zero-arg WorkFn."""
        fn: WorkFn = AsyncMock()
        await fn()
        fn.assert_called_once()  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_async_function_returning_none_satisfies_protocol(self) -> None:
        """A real async function returning None should satisfy WorkFn."""
        called = False

        async def my_work() -> None:
            nonlocal called
            called = True

        fn: WorkFn = my_work
        await fn()
        assert called

    @pytest.mark.asyncio
    async def test_async_function_returning_value_satisfies_protocol(self) -> None:
        """A real async function returning a value should satisfy WorkFn.

        WorkFn uses ``object`` return type so that work functions like
        ``plan_issues`` (returning ``list[PlanResult]``) are accepted.
        """

        async def my_work() -> list[int]:
            return [1, 2, 3]

        fn: WorkFn = my_work
        result = await fn()
        assert result == [1, 2, 3]


# ---------------------------------------------------------------------------
# Integration: merge_conflict_resolver call pattern
# ---------------------------------------------------------------------------


class TestMergeConflictResolverCallPatterns:
    """Verify that the callback call patterns in merge_conflict_resolver are compatible."""

    @pytest.mark.asyncio
    async def test_escalate_fn_call_pattern(self) -> None:
        """The escalate_fn call in merge_conflict_resolver should work with AsyncMock."""
        escalate_fn: EscalateFn = AsyncMock()
        # Matches the call pattern at merge_conflict_resolver.py:85-97
        await escalate_fn(
            42,  # issue_number
            99,  # pr_number
            cause="Merge conflict with main branch",
            origin_label="hydraflow-review",
            comment="Merge conflicts could not be resolved automatically.",
            event_cause="merge_conflict",
        )
        escalate_fn.assert_called_once()  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_publish_fn_call_pattern(self) -> None:
        """The publish_fn call in merge_conflict_resolver should work with AsyncMock."""
        publish_fn: PublishFn = AsyncMock()
        pr = PRInfo(number=99, issue_number=42, branch="agent/issue-42")
        # Matches merge_conflict_resolver.py:58
        await publish_fn(pr, 0, "merge_main")
        publish_fn.assert_called_once_with(pr, 0, "merge_main")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Integration: post_merge_handler call pattern
# ---------------------------------------------------------------------------


class TestPostMergeHandlerCallPatterns:
    """Verify that the callback call patterns in post_merge_handler are compatible."""

    @pytest.mark.asyncio
    async def test_ci_gate_fn_call_pattern(self) -> None:
        """The ci_gate_fn call in post_merge_handler should work with AsyncMock."""
        ci_gate_fn: CiGateFn = AsyncMock(return_value=True)
        pr = PRInfo(number=99, issue_number=42, branch="agent/issue-42")
        issue = GitHubIssue(number=42, title="Test issue")
        result = ReviewResult(pr_number=99, issue_number=42)
        # Matches post_merge_handler.py:69-75
        ok = await ci_gate_fn(pr, issue, Path("/worktrees/issue-42"), result, 0)
        assert ok is True

    @pytest.mark.asyncio
    async def test_escalate_fn_call_pattern(self) -> None:
        """The escalate_fn call in post_merge_handler should work with AsyncMock."""
        escalate_fn: EscalateFn = AsyncMock()
        # Matches post_merge_handler.py:130-140
        await escalate_fn(
            42,
            99,
            cause="PR merge failed on GitHub",
            origin_label="hydraflow-review",
            comment="Merge failed — PR could not be merged.",
            event_cause="merge_failed",
        )
        escalate_fn.assert_called_once()  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_publish_fn_call_pattern(self) -> None:
        """The publish_fn call in post_merge_handler should work with AsyncMock."""
        publish_fn: PublishFn = AsyncMock()
        pr = PRInfo(number=99, issue_number=42, branch="agent/issue-42")
        # Matches post_merge_handler.py:79
        await publish_fn(pr, 0, "merging")
        publish_fn.assert_called_once_with(pr, 0, "merging")  # type: ignore[union-attr]
