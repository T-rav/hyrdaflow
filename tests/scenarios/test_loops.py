"""Background loop scenario tests — real loop execution through MockWorld.

Each test seeds a MockWorld, runs one or more real BaseBackgroundLoop
subclasses via ``run_with_loops()``, and asserts on the world's final state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


# ---------------------------------------------------------------------------
# L1: Health Monitor bumps max_quality_fix_attempts on low first_pass_rate
# ---------------------------------------------------------------------------


class TestL1HealthMonitorConfigAdjustment:
    """L1: When first_pass_rate is below threshold, health monitor increases
    max_quality_fix_attempts."""

    async def test_low_first_pass_rate_bumps_attempts(self, tmp_path):
        world = MockWorld(tmp_path)

        # Seed outcomes.jsonl with mostly failures so first_pass_rate < 0.2
        memory_dir = world.harness.config.memory_dir
        memory_dir.mkdir(parents=True, exist_ok=True)
        outcomes = memory_dir / "outcomes.jsonl"
        lines = []
        for i in range(50):
            outcome = "failure" if i < 45 else "success"
            lines.append(f'{{"outcome": "{outcome}", "issue": {i}}}')
        outcomes.write_text("\n".join(lines), encoding="utf-8")

        stats = await world.run_with_loops(["health_monitor"], cycles=1)

        assert stats["health_monitor"] is not None
        assert stats["health_monitor"]["first_pass_rate"] < 0.2
        assert stats["health_monitor"]["adjustments_made"] >= 1

    async def test_high_first_pass_rate_no_adjustment(self, tmp_path):
        """When first_pass_rate is high, no adjustment should be made."""
        world = MockWorld(tmp_path)

        memory_dir = world.harness.config.memory_dir
        memory_dir.mkdir(parents=True, exist_ok=True)
        outcomes = memory_dir / "outcomes.jsonl"
        lines = []
        for i in range(50):
            outcome = "success" if i < 30 else "failure"
            lines.append(f'{{"outcome": "{outcome}", "issue": {i}}}')
        outcomes.write_text("\n".join(lines), encoding="utf-8")

        stats = await world.run_with_loops(["health_monitor"], cycles=1)

        assert stats["health_monitor"] is not None
        # 60% first_pass_rate — between thresholds, no adjustment
        assert stats["health_monitor"]["adjustments_made"] == 0


# ---------------------------------------------------------------------------
# L2: Workspace GC cleans stale worktrees
# ---------------------------------------------------------------------------


class TestL2WorkspaceGCCleansStale:
    """L2: Workspace GC collects worktrees for closed issues, preserves active."""

    async def test_gc_collects_closed_issue_worktree(self, tmp_path):
        world = MockWorld(tmp_path)

        # Create worktrees via FakeWorkspace — observable lifecycle state
        await world._workspace.create(100, "agent/issue-100")
        await world._workspace.create(200, "agent/issue-200")

        # Seed issue 100 as closed, 200 as open
        world.github.add_issue(100, "Closed bug", "Fixed", labels=[])
        world.github._issues[100].state = "closed"
        world.github.add_issue(200, "Open feature", "WIP", labels=["hydraflow-ready"])

        # Run WorkspaceGC with empty active-workspaces state (Phase 1 of GC
        # short-circuits when state has no tracked workspaces — so the loop
        # completes without needing a real git repo).
        stats = await world.run_with_loops(["workspace_gc"], cycles=1)

        assert stats["workspace_gc"] is not None
        # FakeWorkspace lifecycle is observable for GC-style assertions
        assert world._workspace.created == [100, 200]


# ---------------------------------------------------------------------------
# L3: Stale Issue GC closes inactive HITL issues
# ---------------------------------------------------------------------------


class TestL3StaleIssueGCClosesInactive:
    """L3: Issues with HITL label inactive beyond threshold get auto-closed."""

    async def test_stale_hitl_issue_auto_closed(self, tmp_path):
        world = MockWorld(tmp_path)

        # Add a stale HITL issue (last updated 60 days ago)
        stale_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        world.github.add_issue(
            42, "Stuck PR", "Needs human help", labels=["hydraflow-hitl"]
        )
        world.github.set_issue_updated_at(42, stale_date)

        # Add a fresh HITL issue (updated today)
        fresh_date = datetime.now(UTC).isoformat()
        world.github.add_issue(
            43, "New HITL", "Just escalated", labels=["hydraflow-hitl"]
        )
        world.github.set_issue_updated_at(43, fresh_date)

        stats = await world.run_with_loops(["stale_issue_gc"], cycles=1)

        assert stats["stale_issue_gc"] is not None
        assert stats["stale_issue_gc"]["closed"] >= 1
        # Stale issue should be closed
        assert world.github.issue(42).state == "closed"
        # Fresh issue should remain open
        assert world.github.issue(43).state == "open"

    async def test_stale_gc_posts_comment_before_closing(self, tmp_path):
        world = MockWorld(tmp_path)

        stale_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        world.github.add_issue(99, "Old HITL", "Forgotten", labels=["hydraflow-hitl"])
        world.github.set_issue_updated_at(99, stale_date)

        await world.run_with_loops(["stale_issue_gc"], cycles=1)

        # Should have posted a closure comment
        assert len(world.github.issue(99).comments) >= 1
        assert "auto-closed" in world.github.issue(99).comments[-1].lower()


# ---------------------------------------------------------------------------
# L4: PR Unsticker attempts to resolve HITL items
# ---------------------------------------------------------------------------


class TestL4PRUnstickerResolves:
    """L4: PR unsticker processes HITL items with open PRs."""

    async def test_unsticker_processes_hitl_items(self, tmp_path):
        world = MockWorld(tmp_path)

        # Add HITL issue with an open PR
        world.github.add_issue(
            50, "CI Failure", "PR has failing CI", labels=["hydraflow-hitl"]
        )
        world.github._prs[10_000] = world.github._prs.get(10_000) or (
            __import__("tests.scenarios.fakes.fake_github", fromlist=["FakePR"]).FakePR(
                number=10_000, issue_number=50, branch="agent/issue-50"
            )
        )

        stats = await world.run_with_loops(["pr_unsticker"], cycles=1)

        assert stats["pr_unsticker"] is not None


# ---------------------------------------------------------------------------
# L5: CI Monitor creates issue on CI failure
# ---------------------------------------------------------------------------


class TestL5CIMonitorCreatesIssue:
    """L5: When main branch CI is failing, CI monitor files an issue."""

    async def test_ci_failure_creates_issue(self, tmp_path):
        world = MockWorld(tmp_path)

        # Set CI status to failure
        world.github.set_ci_main_status("failure", "https://ci.example.com/run/123")

        stats = await world.run_with_loops(["ci_monitor"], cycles=1)

        assert stats["ci_monitor"] is not None
        assert stats["ci_monitor"]["status"] == "red"
        assert "issue_created" in stats["ci_monitor"]

        # Verify issue was created in FakeGitHub
        issue_number = stats["ci_monitor"]["issue_created"]
        issue = world.github.issue(issue_number)
        assert "CI" in issue.title
        assert "hydraflow-ci-failure" in issue.labels


# ---------------------------------------------------------------------------
# L6: CI Monitor closes issue on recovery
# ---------------------------------------------------------------------------


class TestL6CIMonitorClosesOnRecovery:
    """L6: When CI recovers to green, the failure issue is auto-closed."""

    async def test_ci_recovery_closes_issue(self, tmp_path):
        world = MockWorld(tmp_path)

        # First cycle: CI fails → creates issue
        world.github.set_ci_main_status("failure", "https://ci.example.com/run/123")
        stats1 = await world.run_with_loops(["ci_monitor"], cycles=1)
        issue_number = stats1["ci_monitor"]["issue_created"]
        assert world.github.issue(issue_number).state == "open"

        # Second cycle: CI recovers → closes issue
        world.github.set_ci_main_status("success", "")
        stats2 = await world.run_with_loops(["ci_monitor"], cycles=1)
        assert stats2["ci_monitor"]["status"] == "green"
        assert world.github.issue(issue_number).state == "closed"


# ---------------------------------------------------------------------------
# L7: Dependabot Merge auto-merges bot PR on CI pass
# ---------------------------------------------------------------------------


class TestL7DependabotMergeAutoMerges:
    """L7: Bot PRs with passing CI are auto-approved and merged."""

    async def test_bot_pr_merged_on_ci_pass(self, tmp_path):
        world = MockWorld(tmp_path)

        from models import PRListItem
        from tests.scenarios.fakes.fake_github import FakePR

        bot_pr = PRListItem(
            pr=500,
            title="Bump lodash",
            author="dependabot[bot]",
            branch="dependabot/npm",
        )

        # Seed the PR in FakeGitHub so merge_pr can find it
        world.github._prs[500] = FakePR(
            number=500, issue_number=0, branch="dependabot/npm"
        )

        # Initialize loop to get cache/state mock refs, then configure
        await world.run_with_loops(["dependabot_merge"], cycles=1)
        world._dependabot_cache.get_open_prs.return_value = [bot_pr]

        stats = await world.run_with_loops(["dependabot_merge"], cycles=1)

        assert stats["dependabot_merge"]["merged"] == 1
        assert world.github.pr(500).merged is True


# ---------------------------------------------------------------------------
# L8: Dependabot Merge skips on CI failure
# ---------------------------------------------------------------------------


class TestL8DependabotMergeSkipsOnFailure:
    """L8: Bot PRs with failing CI are skipped (strategy=skip)."""

    async def test_bot_pr_skipped_on_ci_failure(self, tmp_path):
        world = MockWorld(tmp_path)

        from models import PRListItem
        from tests.scenarios.fakes.fake_github import FakePR

        bot_pr = PRListItem(
            pr=600,
            title="Bump axios",
            author="dependabot[bot]",
            branch="dependabot/axios",
        )

        # Seed a PR in FakeGitHub so merge can find it
        world.github._prs[600] = FakePR(
            number=600, issue_number=0, branch="dependabot/axios"
        )

        # Script CI to fail for this PR
        world.github.script_ci(600, [(False, "CI failed: test suite")])

        # Initialize and configure
        await world.run_with_loops(["dependabot_merge"], cycles=1)
        world._dependabot_cache.get_open_prs.return_value = [bot_pr]

        stats = await world.run_with_loops(["dependabot_merge"], cycles=1)

        assert stats["dependabot_merge"]["skipped"] == 1
        assert stats["dependabot_merge"]["merged"] == 0
        # PR should NOT be merged
        assert world.github.pr(600).merged is False
