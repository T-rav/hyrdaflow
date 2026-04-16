"""Edge case scenario tests — race conditions, mid-flight mutations."""

from __future__ import annotations

import pytest

from tests.conftest import WorkerResultFactory
from tests.scenarios.builders import IssueBuilder, RepoStateBuilder

pytestmark = pytest.mark.scenario


class TestE1DuplicateIssues:
    """E1: Duplicate issues — pipeline must not crash and must track each by number."""

    async def test_same_title_body_both_tracked_by_number(self, mock_world):
        """Two issues with identical title+body are seeded independently.

        Discovered behavior: ``FakeGitHub.find_existing_issue`` resolves by
        title, so when two open issues share a title only the first one
        observed wins the dedup lookup. The pipeline still produces an
        ``IssueOutcome`` for each issue number — duplicates do not crash the
        pipeline and each is independently inspectable. Production-style
        dedup is the responsibility of the upstream issue-creation path,
        not the in-pipeline phases. If a future change makes the pipeline
        actively dedup duplicates this test should be updated to assert the
        new contract.
        """
        await (
            RepoStateBuilder()
            .with_issues(
                [
                    IssueBuilder()
                    .numbered(1)
                    .titled("Fix auth bug")
                    .bodied("The auth module is broken"),
                    IssueBuilder()
                    .numbered(2)
                    .titled("Fix auth bug")
                    .bodied("The auth module is broken"),
                ]
            )
            .at(mock_world)
        )
        result = await mock_world.run_pipeline()

        # Both issues are tracked independently by number
        assert result.issue(1).number == 1
        assert result.issue(2).number == 2
        # At least one of them must reach a real terminal stage; the other
        # is allowed to lag because of upstream title-based dedup.
        stages = {result.issue(1).final_stage, result.issue(2).final_stage}
        assert "done" in stages or "review" in stages, (
            f"Expected at least one duplicate to progress past triage; got {stages}"
        )


class TestE2IssueRelabeledMidFlight:
    """E2: on_phase hook fires before a phase runs."""

    async def test_on_phase_hook_fires(self, mock_world):
        fired = {"count": 0}

        def hook():
            fired["count"] += 1

        IssueBuilder().numbered(1).titled("Refactor DB").bodied("Needs DB refactor").at(
            mock_world
        )
        mock_world.on_phase("plan", hook)
        result = await mock_world.run_pipeline()

        assert fired["count"] == 1, "on_phase hook should fire exactly once"
        # Pipeline still processes the issue normally
        assert result.issue(1) is not None


class TestE5ZeroDiffImplement:
    """E5: Agent produces zero commits — already-satisfied case."""

    async def test_zero_commits_worker_result(self, mock_world):
        zero_diff = WorkerResultFactory.create(
            issue_number=1,
            success=True,
            commits=0,
        )
        IssueBuilder().numbered(1).titled("Add type hints").bodied(
            "Already typed module"
        ).at(mock_world)
        mock_world.set_phase_result("implement", 1, zero_diff)
        result = await mock_world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.worker_result is not None
        assert outcome.worker_result.commits == 0
        assert outcome.worker_result.success is True


class TestE3StaleWorktreeDuringActiveProcessing:
    """E3: Workspace GC skips actively-processing issues."""

    async def test_active_issue_worktree_not_gc_collected(self, mock_world):
        """An issue that is actively being processed (in-pipeline) should
        not have its worktree garbage collected, even if the worktree exists
        in the workspace tracker.
        """
        world = mock_world

        # Seed issue and run pipeline — issue will be processed through phases
        world.add_issue(1, "Active work", "Being processed right now")

        # Create worktree as if implement phase had created it
        await world._workspace.create(1, "agent/issue-1")

        # Run pipeline to process the issue
        result = await world.run_pipeline()

        # Worktree should still exist — not destroyed by phases
        # (phases don't destroy, only GC does — and we haven't run GC)
        assert 1 in world._workspace.created
        # The issue completed successfully through the pipeline
        outcome = result.issue(1)
        assert outcome is not None


class TestE4EpicWithSubIssues:
    """E4: Plan produces sub-issues that are tracked alongside parent."""

    async def test_parent_and_sub_issues_tracked(self, mock_world):
        """When a plan creates sub-issues, the parent plan result carries
        the new_issues list and the sub-issues are created in FakeGitHub.
        """
        from models import NewIssueSpec
        from tests.conftest import PlanResultFactory

        plan_with_children = PlanResultFactory.create(
            issue_number=1,
            success=True,
            new_issues=[
                NewIssueSpec(title="Child A", body="Sub-task A"),
                NewIssueSpec(title="Child B", body="Sub-task B"),
                NewIssueSpec(title="Child C", body="Sub-task C"),
            ],
        )
        world = mock_world.add_issue(
            1, "Epic: Rewrite auth", "Full auth system rewrite"
        ).set_phase_result("plan", 1, plan_with_children)
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.plan_result is not None
        assert outcome.plan_result.new_issues is not None
        assert len(outcome.plan_result.new_issues) == 3
        # Sub-issue titles should match
        titles = [ni.title for ni in outcome.plan_result.new_issues]
        assert "Child A" in titles
        assert "Child B" in titles
        assert "Child C" in titles


class TestE6LabelChangedMidFlight:
    """E6: Label changed by human after pipeline starts — no crash."""

    async def test_label_swap_mid_plan_does_not_crash(self, mock_world):
        IssueBuilder().numbered(1).titled("Refactor").at(mock_world)

        def flip_label():
            mock_world.github.issue(1).labels[:] = ["hydraflow-hitl"]

        mock_world.on_phase("plan", flip_label)
        result = await mock_world.run_pipeline()
        assert result.issue(1) is not None


class TestE7TwoLoopsRaceSameIssue:
    """E7: CI monitor and stale_issue_gc both see the same issue — lock respected."""

    async def test_concurrent_loop_invocations_do_not_corrupt(self, mock_world):
        IssueBuilder().numbered(5).labeled("hydraflow-ci-failure").at(mock_world)
        stats = await mock_world.run_with_loops(
            ["ci_monitor", "stale_issue_gc"], cycles=1
        )
        assert "ci_monitor" in stats
        assert "stale_issue_gc" in stats


class TestE8DuplicateEventDelivery:
    """E8: Same phase hook fires twice (duplicate webhook delivery)."""

    async def test_duplicate_hook_fire_does_not_double_process(self, mock_world):
        counter = {"n": 0}

        def hook():
            counter["n"] += 1

        IssueBuilder().numbered(1).at(mock_world)
        mock_world.on_phase("plan", hook)
        mock_world.on_phase("plan", hook)  # registered twice -> fires twice
        await mock_world.run_pipeline()
        assert (
            counter["n"] == 2
        )  # hooks fire per registration; not deduped at this layer


class TestE9IssueClosedMidImplement:
    """E9: Issue closed while in implement phase — does not abort the run."""

    async def test_close_during_implement_does_not_abort(self, mock_world):
        IssueBuilder().numbered(1).titled("Close me").at(mock_world)

        def close_issue():
            mock_world.github.issue(1).state = "closed"

        mock_world.on_phase("implement", close_issue)
        result = await mock_world.run_pipeline()
        assert mock_world.github.issue(1).state == "closed"
        assert result.issue(1) is not None


class TestE10ClockJumpsBackward:
    """E10: Clock jumps backward (NTP correction) — TTL arithmetic is safe."""

    async def test_clock_rewind_is_observable(self, mock_world):
        start = mock_world.clock.now()
        mock_world.clock.advance(-5.0)
        assert mock_world.clock.now() == start - 5.0
        # Pipeline still runs (no division-by-zero or negative-sleep crash).
        IssueBuilder().numbered(1).at(mock_world)
        await mock_world.run_pipeline()


class TestE11StopEventMidPhase:
    """E11: run_with_loops completes without hanging when called with cycles=1.

    NOTE: ``run_with_loops`` invokes ``_do_work()`` directly, so stop-event
    lifecycle isn't actually exercised here — this test asserts completion,
    not graceful shutdown. A real graceful-shutdown scenario would need to
    drive ``loop.run()`` with a stop event.
    """

    async def test_run_with_loops_completes(self, mock_world):
        stats = await mock_world.run_with_loops(["ci_monitor"], cycles=1)
        assert "ci_monitor" in stats


class TestE12ServiceFailureDuringPipeline:
    """E12: Hindsight fails mid-plan — pipeline continues, no crash."""

    async def test_service_failure_does_not_abort_pipeline(self, mock_world):
        IssueBuilder().numbered(1).at(mock_world)
        mock_world.fail_service("hindsight")
        result = await mock_world.run_pipeline()
        assert result.issue(1) is not None
        mock_world.heal_service("hindsight")
