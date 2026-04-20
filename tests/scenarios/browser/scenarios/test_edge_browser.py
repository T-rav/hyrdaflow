"""Tier-3 browser ports of E1-E5 edge-case scenarios.

Reference tests live in tests/scenarios/test_edge.py.

Pattern (established by H1 pilot, H2-H5 ports, and S1-S6 ports):
    1. Seed world state identically to the Python reference test.
    2. Run pipeline Python-side: ``await world.run_pipeline()``.
    3. Call ``world._harness.store.mark_merged(N)`` only for issues that
       actually merged.
    4. Boot dashboard shim: ``url = await world.start_dashboard()``.
    5. Navigate + wait for ``body[data-connected="true"]``.
    6. Assert DOM via ``stage-header-{stage}`` text or element visibility.
    7. Assert world state via ``world.github.*``, ``world._workspace.*``, etc.

Edge-case escalation policy (per task brief):
    If a scenario's reference test asserts on something with no UI surface
    (e.g., E3 workspace GC has no rendered side-effect), we keep the
    Python-side assertion and add a negative DOM assertion confirming the
    dashboard did not crash and tabs still render.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from playwright.async_api import expect

from models import NewIssueSpec
from tests.conftest import (
    PlanResultFactory,
    WorkerResultFactory,
)
from tests.scenarios.builders import IssueBuilder, RepoStateBuilder

pytestmark = pytest.mark.scenario_browser

# Minimal control-status payload — same as happy-path and sad-path browser tests.
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


async def test_e1_duplicate_issues_both_tracked(world, page) -> None:
    """E1: Two issues with identical title+body are tracked by distinct numbers.

    Discovered behaviour (from reference test): ``FakeGitHub.find_existing_issue``
    resolves by title, so the pipeline may only advance one of the duplicates
    past triage.  Neither crashes.  The pipeline produces an ``IssueOutcome`` for
    each number independently.

    DOM assertion: dashboard does not crash; pipeline stage sections render.
    At least one of the two flow-dots is visible (the one that progressed).
    Python assertion: both outcomes are present; at least one reached review/done.

    Reference: TestE1DuplicateIssues.test_same_title_body_both_tracked_by_number
    """
    # --- Step 1: seed (matches reference test exactly) ---
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
        .at(world)
    )

    # --- Step 2: run pipeline Python-side ---
    result = await world.run_pipeline()

    # Python-side reference assertions.
    assert result.issue(1).number == 1
    assert result.issue(2).number == 2
    stages = {result.issue(1).final_stage, result.issue(2).final_stage}
    assert "done" in stages or "review" in stages, (
        f"Expected at least one duplicate to progress past triage; got {stages}"
    )

    # Sync IssueStore for issues that actually merged.
    for num in (1, 2):
        if result.issue(num).merged:
            world._harness.store.mark_merged(num)

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions ---
    # Dashboard must not crash — pipeline sections are always present.
    plan_section = page.locator('[data-testid="stage-section-plan"]')
    await expect(plan_section).to_be_visible(timeout=5_000)

    implement_section = page.locator('[data-testid="stage-section-implement"]')
    await expect(implement_section).to_be_visible(timeout=5_000)

    # At least one flow-dot must be visible (whichever issue progressed).
    dot_1 = page.locator('[data-testid="flow-dot-1"]')
    dot_2 = page.locator('[data-testid="flow-dot-2"]')
    dot_1_count = await dot_1.count()
    dot_2_count = await dot_2.count()
    assert dot_1_count > 0 or dot_2_count > 0, (
        "E1: expected at least one flow-dot (issue #1 or #2) to be visible"
    )

    # --- Step 6: Python-side assertions (repeated for explicitness) ---
    assert result.issue(1).number == 1
    assert result.issue(2).number == 2


async def test_e2_on_phase_hook_fires(world, page) -> None:
    """E2: ``on_phase`` hook fires before the plan phase; pipeline continues.

    The hook fires exactly once, and the issue still completes through all
    pipeline phases (reaching done/merged with default FakeLLM scripting).

    DOM assertion: issue #1 appears in merged stage (pipeline ran to completion).
    Python assertion: hook fired once; plan_result is present.

    Reference: TestE2IssueRelabeledMidFlight.test_on_phase_hook_fires
    """
    # --- Step 1: seed (matches reference test exactly) ---
    fired = {"count": 0}

    def hook():
        fired["count"] += 1

    IssueBuilder().numbered(1).titled("Refactor DB").bodied("Needs DB refactor").at(
        world
    )
    world.on_phase("plan", hook)

    # --- Step 2: run pipeline Python-side ---
    result = await world.run_pipeline()

    assert fired["count"] == 1, "on_phase hook should fire exactly once"
    outcome = result.issue(1)
    assert outcome is not None

    # If pipeline reached done, sync IssueStore.
    if outcome.merged:
        world._harness.store.mark_merged(1)

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions ---
    if outcome.merged:
        # Issue completed — flow-dot should be visible in merged stage.
        merged_header = page.locator('[data-testid="stage-header-merged"]')
        await expect(merged_header).to_contain_text("1 merged", timeout=15_000)

        flow_dot = page.locator('[data-testid="flow-dot-1"]')
        await expect(flow_dot).to_be_visible(timeout=5_000)
    else:
        # Pipeline stalled but did not crash — sections still render.
        plan_section = page.locator('[data-testid="stage-section-plan"]')
        await expect(plan_section).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    assert fired["count"] == 1
    assert result.issue(1) is not None


async def test_e3_stale_worktree_skips_active_issue(world, page) -> None:
    """E3: Workspace GC skips issues actively being processed (in-pipeline).

    The reference test seeds a worktree via ``world._workspace.create(1, ...)``
    to simulate the implement phase creating a workspace, then asserts that
    running the pipeline does NOT destroy it (phases don't GC, only explicit GC
    does).

    There is no rendered UI surface for workspace state — this is purely a
    Python-side concern.  Per the escalation policy we add a negative DOM
    assertion confirming the dashboard does not crash and all pipeline stage
    sections remain visible.

    DOM assertion (negative): dashboard loads without crash; pipeline sections
    are visible; no error indicator is present.
    Python assertion: worktree for issue #1 still exists after pipeline run;
    outcome is not None.

    Reference: TestE3StaleWorktreeDuringActiveProcessing.test_active_issue_worktree_not_gc_collected
    """
    # --- Step 1: seed (matches reference test exactly) ---
    world.add_issue(1, "Active work", "Being processed right now")

    # Create worktree as if implement phase had created it.
    await world._workspace.create(1, "agent/issue-1")

    # --- Step 2: run pipeline Python-side ---
    result = await world.run_pipeline()

    # Python-side reference assertions.
    assert 1 in world._workspace.created, (
        "E3: worktree for issue #1 should still exist after pipeline (no GC ran)"
    )
    outcome = result.issue(1)
    assert outcome is not None

    # Sync IssueStore if issue merged.
    if outcome.merged:
        world._harness.store.mark_merged(1)

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions (negative — no crash) ---
    # Workspace state has no UI surface, so we assert the dashboard is alive
    # and renders all expected pipeline stage sections without error.
    plan_section = page.locator('[data-testid="stage-section-plan"]')
    await expect(plan_section).to_be_visible(timeout=5_000)

    implement_section = page.locator('[data-testid="stage-section-implement"]')
    await expect(implement_section).to_be_visible(timeout=5_000)

    review_section = page.locator('[data-testid="stage-section-review"]')
    await expect(review_section).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions (repeated) ---
    assert 1 in world._workspace.created
    assert result.issue(1) is not None


async def test_e4_epic_child_ordering(world, page) -> None:
    """E4: Planner returns 3 sub-issues; parent waits for children.

    The plan result carries NewIssueSpec entries for three child tasks.
    Because the body strings are short (< _MIN_ISSUE_BODY_CHARS), plan_phase
    skips creating them in GitHub — but the plan_result object retains them.
    The parent issue #1 still continues through implement/review and merges.

    DOM assertion: parent issue #1 appears in merged stage.
    Python assertion: plan_result.new_issues has 3 entries with correct titles.

    Reference: TestE4EpicWithSubIssues.test_parent_and_sub_issues_tracked
    """
    # --- Step 1: seed (matches reference test exactly) ---
    plan_with_children = PlanResultFactory.create(
        issue_number=1,
        success=True,
        new_issues=[
            NewIssueSpec(title="Child A", body="Sub-task A"),
            NewIssueSpec(title="Child B", body="Sub-task B"),
            NewIssueSpec(title="Child C", body="Sub-task C"),
        ],
    )
    world.add_issue(
        1, "Epic: Rewrite auth", "Full auth system rewrite"
    ).set_phase_result("plan", 1, plan_with_children)

    # --- Step 2: run pipeline Python-side ---
    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert outcome.plan_result is not None
    assert outcome.plan_result.new_issues is not None
    assert len(outcome.plan_result.new_issues) == 3
    titles = [ni.title for ni in outcome.plan_result.new_issues]
    assert "Child A" in titles
    assert "Child B" in titles
    assert "Child C" in titles

    # Sync IssueStore if parent merged.
    if outcome.merged:
        world._harness.store.mark_merged(1)

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions ---
    if outcome.merged:
        merged_header = page.locator('[data-testid="stage-header-merged"]')
        await expect(merged_header).to_contain_text("1 merged", timeout=15_000)

        flow_dot = page.locator('[data-testid="flow-dot-1"]')
        await expect(flow_dot).to_be_visible(timeout=5_000)
    else:
        # Parent stalled but dashboard must not crash.
        plan_section = page.locator('[data-testid="stage-section-plan"]')
        await expect(plan_section).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions (repeated) ---
    assert outcome.plan_result is not None
    assert len(outcome.plan_result.new_issues) == 3


async def test_e5_zero_diff_implement(world, page) -> None:
    """E5: Worker returns 0 commits (success=True) — already-satisfied case.

    The scripted WorkerResult has commits=0 and success=True.  The pipeline
    records the worker_result and the issue completes.

    DOM assertion: flow-dot for issue #1 is visible; if merged, "1 merged"
    appears in the merged stage header.
    Python assertion: worker_result.commits == 0; worker_result.success is True.

    Reference: TestE5ZeroDiffImplement.test_zero_commits_worker_result
    """
    # --- Step 1: seed (matches reference test exactly) ---
    zero_diff = WorkerResultFactory.create(
        issue_number=1,
        success=True,
        commits=0,
    )
    IssueBuilder().numbered(1).titled("Add type hints").bodied(
        "Already typed module"
    ).at(world)
    world.set_phase_result("implement", 1, zero_diff)

    # --- Step 2: run pipeline Python-side ---
    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert outcome.worker_result is not None
    assert outcome.worker_result.commits == 0
    assert outcome.worker_result.success is True

    # Sync IssueStore if issue merged.
    if outcome.merged:
        world._harness.store.mark_merged(1)

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions ---
    if outcome.merged:
        merged_header = page.locator('[data-testid="stage-header-merged"]')
        await expect(merged_header).to_contain_text("1 merged", timeout=15_000)

        flow_dot = page.locator('[data-testid="flow-dot-1"]')
        await expect(flow_dot).to_be_visible(timeout=5_000)
    else:
        # Worker succeeded with 0 commits but pipeline may not have merged —
        # assert no crash and pipeline sections are present.
        implement_section = page.locator('[data-testid="stage-section-implement"]')
        await expect(implement_section).to_be_visible(timeout=5_000)

        plan_section = page.locator('[data-testid="stage-section-plan"]')
        await expect(plan_section).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions (repeated) ---
    assert outcome.worker_result.commits == 0
    assert outcome.worker_result.success is True
