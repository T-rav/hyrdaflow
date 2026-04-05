"""Tests for the HITLController extracted module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hitl_controller import HITLController


@pytest.fixture
def hitl_phase() -> MagicMock:
    phase = MagicMock()
    phase.active_hitl_issues = set()
    phase.hitl_corrections = {}
    phase.submit_correction = MagicMock()
    phase.get_status = MagicMock(return_value="pending")
    phase.skip_issue = MagicMock()
    phase.process_corrections = AsyncMock()
    return phase


@pytest.fixture
def fetcher() -> MagicMock:
    f = MagicMock()
    f.fetch_issues_by_labels = AsyncMock(return_value=[])
    return f


@pytest.fixture
def controller(hitl_phase: MagicMock, fetcher: MagicMock) -> HITLController:
    return HITLController(hitl_phase, fetcher, hitl_label=["hydraflow-hitl"])


class TestHumanInput:
    """Tests for human input request/response flow."""

    def test_requests_starts_empty(self, controller: HITLController) -> None:
        assert controller.human_input_requests == {}

    def test_responses_starts_empty(self, controller: HITLController) -> None:
        assert controller.human_input_responses == {}

    def test_provide_stores_answer(self, controller: HITLController) -> None:
        controller.provide_human_input(42, "Use option B")
        assert controller.human_input_responses[42] == "Use option B"

    def test_provide_removes_from_requests(self, controller: HITLController) -> None:
        controller._human_input_requests[42] = "Which approach?"
        controller.provide_human_input(42, "Approach A")
        assert 42 not in controller.human_input_requests

    def test_provide_for_non_pending_is_safe(self, controller: HITLController) -> None:
        controller.provide_human_input(99, "Some answer")
        assert controller.human_input_responses[99] == "Some answer"

    def test_requests_reflects_pending(self, controller: HITLController) -> None:
        controller._human_input_requests[7] = "What colour?"
        assert controller.human_input_requests == {7: "What colour?"}


class TestHITLDelegation:
    """Tests for methods that delegate to hitl_phase."""

    def test_submit_correction(
        self, controller: HITLController, hitl_phase: MagicMock
    ) -> None:
        controller.submit_correction(42, "fix the bug")
        hitl_phase.submit_correction.assert_called_once_with(42, "fix the bug")

    def test_get_status(
        self, controller: HITLController, hitl_phase: MagicMock
    ) -> None:
        result = controller.get_status(42)
        assert result == "pending"
        hitl_phase.get_status.assert_called_once_with(42)

    def test_skip_issue(
        self, controller: HITLController, hitl_phase: MagicMock
    ) -> None:
        controller.skip_issue(42)
        hitl_phase.skip_issue.assert_called_once_with(42)

    def test_active_hitl_issues(
        self, controller: HITLController, hitl_phase: MagicMock
    ) -> None:
        hitl_phase.active_hitl_issues.add(10)
        assert 10 in controller.active_hitl_issues

    def test_hitl_corrections(
        self, controller: HITLController, hitl_phase: MagicMock
    ) -> None:
        hitl_phase.hitl_corrections[10] = "fix"
        assert controller.hitl_corrections == {10: "fix"}


class TestDoWork:
    """Tests for do_work async method."""

    @pytest.mark.asyncio
    async def test_fetches_and_processes(
        self, controller: HITLController, fetcher: MagicMock, hitl_phase: MagicMock
    ) -> None:
        fetcher.fetch_issues_by_labels.return_value = [MagicMock()]
        await controller.do_work()
        fetcher.fetch_issues_by_labels.assert_awaited_once_with(
            ["hydraflow-hitl"], limit=50
        )
        hitl_phase.process_corrections.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_processes_corrections_when_no_issues(
        self, controller: HITLController, fetcher: MagicMock, hitl_phase: MagicMock
    ) -> None:
        fetcher.fetch_issues_by_labels.return_value = []
        await controller.do_work()
        hitl_phase.process_corrections.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_failure_skips_process_corrections(
        self, controller: HITLController, fetcher: MagicMock, hitl_phase: MagicMock
    ) -> None:
        fetcher.fetch_issues_by_labels.side_effect = RuntimeError("network error")
        with pytest.raises(RuntimeError, match="network error"):
            await controller.do_work()
        hitl_phase.process_corrections.assert_not_awaited()
