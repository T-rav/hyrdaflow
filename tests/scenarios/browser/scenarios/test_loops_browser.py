"""Tier-3 browser ports of L1-L8 background-loop scenarios.

Reference tests live in tests/scenarios/test_loops.py.

Pattern (loop variant):
    1. Seed world state matching the reference test.
    2. Run loop(s) Python-side: ``await world.run_with_loops(["<loop>"], cycles=1)``.
    3. Boot dashboard shim: ``url = await world.start_dashboard()``.
    4. Navigate + wait for ``body[data-connected="true"]``.
    5. Assert Python-side world state (loop output).
    6. Negative DOM assertion: dashboard loaded without crash; stage sections visible.

Loop tests have no direct UI surface — per E3 escalation policy we keep
Python-side assertions and add a negative DOM check confirming the dashboard
did not crash and rendered correctly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from playwright.async_api import expect

from tests.scenarios.builders import IssueBuilder, PRBuilder

pytestmark = pytest.mark.scenario_browser

# Minimal control-status payload — same as happy/sad/edge browser tests.
_RUNNING_CONTROL_STATUS = {
    "status": "running",
    "credits_paused_until": None,
    "current_session_id": None,
    "config": {
        "app_version": "0.0.0",
        "latest_version": "",
        "update_available": False,
        "repo": "T-rav/hydraflow",
        "ready_label": ["hydraflow-ready"],
        "find_label": ["hydraflow-find"],
        "planner_label": ["hydraflow-plan"],
        "review_label": ["hydraflow-review"],
        "hitl_label": ["hydraflow-hitl"],
        "hitl_active_label": ["hydraflow-hitl-active"],
        "fixed_label": ["hydraflow-fixed"],
        "max_triagers": 1,
        "max_workers": 2,
        "max_planners": 1,
        "max_reviewers": 1,
        "max_hitl_workers": 1,
        "batch_size": 5,
        "model": "claude-opus-4-5",
        "pr_unstick_batch_size": 3,
        "workspace_base": "/tmp/hydraflow-worktrees",
    },
}


async def _boot_and_navigate(world, page) -> None:
    """Shared helper: intercept control/status, boot shim, navigate, wait."""
    url = await world.start_dashboard(with_orchestrator=False)

    async def _handle_control_status(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    await page.route("**/api/control/status", _handle_control_status)
    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)
    await asyncio.sleep(0.5)


async def _assert_dashboard_alive(page) -> None:
    """Negative DOM assertion: dashboard loaded; no crash; pipeline sections visible."""
    plan_section = page.locator('[data-testid="stage-section-plan"]')
    await expect(plan_section).to_be_visible(timeout=5_000)

    implement_section = page.locator('[data-testid="stage-section-implement"]')
    await expect(implement_section).to_be_visible(timeout=5_000)

    review_section = page.locator('[data-testid="stage-section-review"]')
    await expect(review_section).to_be_visible(timeout=5_000)


# ---------------------------------------------------------------------------
# L1: HealthMonitor bumps max_quality_fix_attempts on low first_pass_rate
# ---------------------------------------------------------------------------


async def test_l1_health_monitor_config_bump(world, page) -> None:
    """L1: When first_pass_rate is below threshold, health monitor bumps attempts.

    Reference: TestL1HealthMonitorConfigAdjustment.test_low_first_pass_rate_bumps_attempts

    Python assertion: stats reports first_pass_rate < 0.2 and adjustments_made >= 1.
    DOM assertion (negative): dashboard renders without crash; pipeline sections visible.
    """
    # --- Step 1: seed outcomes.jsonl with mostly failures (matches reference) ---
    memory_dir = world.harness.config.memory_dir
    memory_dir.mkdir(parents=True, exist_ok=True)
    outcomes = memory_dir / "outcomes.jsonl"
    lines = []
    for i in range(50):
        outcome = "failure" if i < 45 else "success"
        lines.append(f'{{"outcome": "{outcome}", "issue": {i}}}')
    outcomes.write_text("\n".join(lines), encoding="utf-8")

    # --- Step 2: run loop ---
    stats = await world.run_with_loops(["health_monitor"], cycles=1)

    # --- Step 3: Python-side assertions ---
    assert stats["health_monitor"] is not None
    assert stats["health_monitor"]["first_pass_rate"] < 0.2
    assert stats["health_monitor"]["adjustments_made"] >= 1

    # --- Step 4-5: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 6: DOM assertions (negative) ---
    await _assert_dashboard_alive(page)


# ---------------------------------------------------------------------------
# L2: WorkspaceGC cleans stale worktrees
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "workspace_gc state mock returns empty active_workspaces (Phase 1 no-ops) and "
        "_is_safe_to_gc calls `gh api` via run_subprocess which is not stubbed in the "
        "scenario harness. Same xfail as the reference test_loops.py::TestL2. "
        "Remove when the workspace_gc Phase 3B track lands."
    ),
    strict=False,
)
async def test_l2_workspace_gc_cleans_stale(world, page) -> None:
    """L2: workspace_gc destroys stale (closed-issue) worktrees, preserves active.

    Reference: TestL2WorkspaceGCCleansStale.test_closed_issue_worktree_destroyed_active_preserved

    Python assertion: issue 100's worktree is in world._workspace.destroyed; 200 is not.
    DOM assertion (negative): dashboard renders without crash; pipeline sections visible.
    """
    # --- Step 1: seed (matches reference) ---
    IssueBuilder().numbered(100).labeled("hydraflow-done").at(world)
    IssueBuilder().numbered(200).labeled("hydraflow-implementing").at(world)
    world.github.issue(100).state = "closed"

    # Worktrees exist for both
    await world._workspace.create(100, "agent/issue-100")
    await world._workspace.create(200, "agent/issue-200")

    # --- Step 2: run loop ---
    await world.run_with_loops(["workspace_gc"], cycles=1)

    # --- Step 3: Python-side assertions ---
    assert 100 in world._workspace.destroyed, (
        "workspace_gc should have destroyed the closed-issue worktree"
    )
    assert 200 not in world._workspace.destroyed, (
        "workspace_gc should NOT destroy the active-issue worktree"
    )

    # --- Step 4-5: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 6: DOM assertions (negative) ---
    await _assert_dashboard_alive(page)


# ---------------------------------------------------------------------------
# L3: StaleIssueGC closes inactive HITL issues
# ---------------------------------------------------------------------------


async def test_l3_stale_issue_gc_closes_hitl(world, page) -> None:
    """L3: Issues with HITL label inactive beyond threshold get auto-closed.

    Reference: TestL3StaleIssueGCClosesInactive.test_stale_hitl_issue_auto_closed

    Python assertion: stale issue #42 closed; fresh issue #43 still open.
    DOM assertion (negative): dashboard renders without crash; pipeline sections visible.
    """
    # --- Step 1: seed (matches reference) ---
    stale_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    world.github.add_issue(
        42, "Stuck PR", "Needs human help", labels=["hydraflow-hitl"]
    )
    world.github.set_issue_updated_at(42, stale_date)

    fresh_date = datetime.now(UTC).isoformat()
    world.github.add_issue(43, "New HITL", "Just escalated", labels=["hydraflow-hitl"])
    world.github.set_issue_updated_at(43, fresh_date)

    # --- Step 2: run loop ---
    stats = await world.run_with_loops(["stale_issue_gc"], cycles=1)

    # --- Step 3: Python-side assertions ---
    assert stats["stale_issue_gc"] is not None
    assert stats["stale_issue_gc"]["closed"] >= 1
    assert world.github.issue(42).state == "closed"
    assert world.github.issue(43).state == "open"

    # --- Step 4-5: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 6: DOM assertions (negative) ---
    await _assert_dashboard_alive(page)


# ---------------------------------------------------------------------------
# L4: PRUnsticker processes HITL items with open PRs
# ---------------------------------------------------------------------------


async def test_l4_pr_unsticker_processes_hitl(world, page) -> None:
    """L4: pr_unsticker invokes the unsticker on HITL items with open PRs.

    Reference: TestL4PRUnstickerResolves.test_hitl_item_with_pr_is_processed

    Python assertion: stats contains 'resolved' or 'skipped' keys (loop ran).
    DOM assertion (negative): dashboard renders without crash; pipeline sections visible.
    """
    # --- Step 1: seed (matches reference) ---
    IssueBuilder().numbered(10_000).labeled("hydraflow-hitl").at(world)
    await PRBuilder().for_issue(10_000).on_branch("hydraflow/10000-test").at(world)

    # --- Step 2: run loop ---
    stats = await world.run_with_loops(["pr_unsticker"], cycles=1)

    # --- Step 3: Python-side assertions ---
    result = stats["pr_unsticker"]
    assert result is not None, "pr_unsticker returned no stats — loop crashed"
    assert "resolved" in result or "skipped" in result, (
        f"pr_unsticker did not report resolution stats: {result}"
    )

    # --- Step 4-5: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 6: DOM assertions (negative) ---
    await _assert_dashboard_alive(page)


# ---------------------------------------------------------------------------
# L5: CIMonitor creates issue on CI failure
# ---------------------------------------------------------------------------


async def test_l5_ci_monitor_creates_failure_issue(world, page) -> None:
    """L5: When main branch CI is failing, CI monitor files an issue.

    Reference: TestL5CIMonitorCreatesIssue.test_ci_failure_creates_issue

    Python assertion: FakeGitHub has new issue with 'hydraflow-ci-failure' label.
    DOM assertion (negative): dashboard renders without crash; pipeline sections visible.
    """
    # --- Step 1: seed (matches reference) ---
    world.github.set_ci_main_status("failure", "https://ci.example.com/run/123")

    # --- Step 2: run loop ---
    stats = await world.run_with_loops(["ci_monitor"], cycles=1)

    # --- Step 3: Python-side assertions ---
    assert stats["ci_monitor"] is not None
    assert stats["ci_monitor"]["status"] == "red"
    assert "issue_created" in stats["ci_monitor"]

    issue_number = stats["ci_monitor"]["issue_created"]
    issue = world.github.issue(issue_number)
    assert "CI" in issue.title
    assert "hydraflow-ci-failure" in issue.labels

    # --- Step 4-5: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 6: DOM assertions (negative) ---
    await _assert_dashboard_alive(page)


# ---------------------------------------------------------------------------
# L6: CIMonitor closes issue on recovery
# ---------------------------------------------------------------------------


async def test_l6_ci_monitor_closes_on_recovery(world, page) -> None:
    """L6: When CI recovers to green, the failure issue is auto-closed.

    Reference: TestL6CIMonitorClosesOnRecovery.test_ci_recovery_closes_issue

    Python assertion: failure issue state == 'closed' after second cycle.
    DOM assertion (negative): dashboard renders without crash; pipeline sections visible.
    """
    # --- Step 1: seed first cycle — CI fails → creates issue ---
    world.github.set_ci_main_status("failure", "https://ci.example.com/run/123")
    stats1 = await world.run_with_loops(["ci_monitor"], cycles=1)
    issue_number = stats1["ci_monitor"]["issue_created"]
    assert world.github.issue(issue_number).state == "open"

    # --- Step 2: second cycle — CI recovers → closes issue ---
    world.github.set_ci_main_status("success", "")
    stats2 = await world.run_with_loops(["ci_monitor"], cycles=1)

    # --- Step 3: Python-side assertions ---
    assert stats2["ci_monitor"]["status"] == "green"
    assert world.github.issue(issue_number).state == "closed"

    # --- Step 4-5: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 6: DOM assertions (negative) ---
    await _assert_dashboard_alive(page)


# ---------------------------------------------------------------------------
# L7: DependabotMerge auto-merges bot PR on CI pass
# ---------------------------------------------------------------------------


async def test_l7_dependabot_merge_merges_green_pr(world, page) -> None:
    """L7: Bot PRs with passing CI are auto-approved and merged.

    Reference: TestL7DependabotMergeAutoMerges.test_bot_pr_merged_on_ci_pass

    Python assertion: PR 500 is merged in FakeGitHub.
    DOM assertion (negative): dashboard renders without crash; pipeline sections visible.
    """
    # --- Step 1: seed (matches reference) ---
    from mockworld.fakes.fake_github import FakePR
    from models import PRListItem

    bot_pr = PRListItem(
        pr=500,
        title="Bump lodash",
        author="dependabot[bot]",
        branch="dependabot/npm",
    )

    # Seed the PR in FakeGitHub so merge_pr can find it
    world.github._prs[500] = FakePR(number=500, issue_number=0, branch="dependabot/npm")

    # --- Step 2: first run to initialize loop cache/state mock refs ---
    await world.run_with_loops(["dependabot_merge"], cycles=1)
    world._dependabot_cache.get_open_prs.return_value = [bot_pr]

    # --- Step 3: second run with configured cache ---
    stats = await world.run_with_loops(["dependabot_merge"], cycles=1)

    # --- Step 4: Python-side assertions ---
    assert stats["dependabot_merge"]["merged"] == 1
    assert world.github.pr(500).merged is True

    # --- Step 5-6: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 7: DOM assertions (negative) ---
    await _assert_dashboard_alive(page)


# ---------------------------------------------------------------------------
# L8: DependabotMerge skips on CI failure
# ---------------------------------------------------------------------------


async def test_l8_dependabot_merge_skips_red_pr(world, page) -> None:
    """L8: Bot PRs with failing CI are skipped (strategy=skip).

    Reference: TestL8DependabotMergeSkipsOnFailure.test_bot_pr_skipped_on_ci_failure

    Python assertion: stats['skipped'] == 1, PR 600 NOT merged.
    DOM assertion (negative): dashboard renders without crash; pipeline sections visible.
    """
    # --- Step 1: seed (matches reference) ---
    from mockworld.fakes.fake_github import FakePR
    from models import PRListItem

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

    # --- Step 2: first run to initialize loop cache/state mock refs ---
    await world.run_with_loops(["dependabot_merge"], cycles=1)
    world._dependabot_cache.get_open_prs.return_value = [bot_pr]

    # --- Step 3: second run with configured cache ---
    stats = await world.run_with_loops(["dependabot_merge"], cycles=1)

    # --- Step 4: Python-side assertions ---
    assert stats["dependabot_merge"]["skipped"] == 1
    assert stats["dependabot_merge"]["merged"] == 0
    assert world.github.pr(600).merged is False

    # --- Step 5-6: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 7: DOM assertions (negative) ---
    await _assert_dashboard_alive(page)
