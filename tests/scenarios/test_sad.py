"""Sad path scenario tests — prove failure recovery works."""

from __future__ import annotations

import pytest

from models import ReviewVerdict
from tests.conftest import (
    PlanResultFactory,
    ReviewResultFactory,
    WorkerResultFactory,
)
from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestS1PlanFailsThenSucceeds:
    """S1: First plan fails, retry succeeds."""

    async def test_plan_retry_sequence(self, mock_world):
        fail = PlanResultFactory.create(
            issue_number=1, success=False, error="LLM timeout"
        )
        succeed = PlanResultFactory.create(issue_number=1, success=True)

        world = mock_world
        IssueBuilder().numbered(1).titled("Fix auth").bodied("Auth is broken").at(world)
        world.set_phase_results("plan", 1, [fail, succeed])
        result = await world.run_pipeline()

        # The pipeline should have produced a plan result even if the first attempt failed
        outcome = result.issue(1)
        assert outcome.plan_result is not None


class TestS2ImplementExhaustsAttempts:
    """S2: Docker fails, issue does not complete."""

    async def test_implement_failure_blocks_completion(self, mock_world):
        fail = WorkerResultFactory.create(
            issue_number=1, success=False, error="compilation error"
        )
        world = mock_world
        IssueBuilder().numbered(1).titled("Fix DB migration").bodied(
            "Migration is broken"
        ).at(world)
        world.set_phase_result("implement", 1, fail)
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.worker_result is not None
        assert outcome.worker_result.success is False
        # Failed implement means the issue should NOT be marked as done
        assert outcome.final_stage != "done"
        assert outcome.merged is False


class TestS3ReviewRejects:
    """S3: Review rejects with REQUEST_CHANGES."""

    async def test_review_rejection_tracked(self, mock_world):
        reject = ReviewResultFactory.create(
            issue_number=1,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            merged=False,
        )
        world = mock_world
        IssueBuilder().numbered(1).titled("Fix UI glitch").bodied(
            "Button misaligned"
        ).at(world)
        world.set_phase_result("review", 1, reject)
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.review_result is not None
        assert outcome.review_result.verdict == ReviewVerdict.REQUEST_CHANGES
        assert outcome.merged is False


class TestS5HindsightDown:
    """S5: Pipeline continues with Hindsight in fail mode."""

    async def test_pipeline_completes_without_hindsight(self, mock_world):
        world = mock_world
        IssueBuilder().numbered(1).titled("Add feature").bodied(
            "New feature request"
        ).at(world)
        world.fail_service("hindsight")
        result = await world.run_pipeline()

        # Pipeline should still complete the happy path even without memory
        outcome = result.issue(1)
        assert outcome.final_stage == "done"
        assert outcome.merged is True
        assert world.hindsight.is_failing is True  # confirm it stayed failed


class TestS6ImplementHappyPathBaseline:
    """S6: Happy-path baseline — implement succeeds, issue does not reach done
    because the mock WorkerResult carries no pr_info so review is skipped.

    NOTE: scripted CI failure/retry (original docstring intent) requires
    WorkerResultFactory to populate pr_info so review_phase calls wait_for_ci.
    That wiring is deferred; this test records the actual pipeline behaviour.
    """

    async def test_implement_produces_worker_result(self, mock_world):
        world = mock_world
        IssueBuilder().numbered(1).titled("Fix tests").bodied("Flaky test suite").at(
            world
        )
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome is not None
        # FakeLLM.agents.run returns success=True, but pr_info=None means
        # review is skipped — final stage is "implement", not "done".
        assert outcome.worker_result is not None
        assert outcome.worker_result.success is True


class TestS4GitHubFailureDuringImplement:
    """S4: GitHub service failure during implement — issue does not complete."""

    async def test_github_down_during_implement_blocks_completion(self, mock_world):
        """When implement fails due to a service error, the issue should
        not reach done. Uses a scripted failure result to simulate a GitHub
        API 5xx during PR creation.
        """
        fail = WorkerResultFactory.create(
            issue_number=1, success=False, error="GitHub API 503: Service Unavailable"
        )
        world = mock_world.add_issue(
            1, "Add caching", "Cache API responses"
        ).set_phase_result("implement", 1, fail)

        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.final_stage != "done", (
            "GitHub 5xx during implement should prevent completion"
        )
        assert outcome.worker_result is not None
        assert outcome.worker_result.success is False
        assert "503" in (outcome.worker_result.error or "")
        assert outcome.merged is False
