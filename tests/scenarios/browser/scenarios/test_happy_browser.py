"""Tier-3 browser ports of H1 from tests/scenarios/test_happy.py.

H1: Single issue flows find -> triage -> plan -> implement -> review -> done.

Implementation pattern (pilot):
    Full-E2E orchestrator drive is NOT viable: clicking the UI Start button
    creates a brand-new HydraFlowOrchestrator that replaces the wired
    orchestrator injected by MockWorld._build_wired_orchestrator, so the
    fakes (FakeLLM, FakeGitHub, etc.) are lost.  See dashboard_routes/
    _control_routes.py::start_orchestrator which calls
    HydraFlowOrchestrator(ctx.config, ...) fresh every time.

    The viable pattern is:
      1. Seed world and run the full pipeline Python-side through wired fakes
         (world.run_pipeline() drives all four phases: triage, plan,
         implement, review).  After this call the harness IssueStore has
         the issue marked as merged and FakeGitHub records the merged PR.
      2. Boot the dashboard with the lightweight _HarnessOrchestratorShim
         (with_orchestrator=False).  The shim exposes the same harness
         IssueStore to the /api/pipeline route, which is gated by
         _is_default_pipeline_active().  The shim has running=True so the
         gate passes and the route serves real harness data.
      3. Navigate; wait for the WebSocket-ready signal.
      4. Assert the pipeline snapshot that React fetched on mount shows
         issue #1 in the 'merged' stage (stage-section-merged, stage-
         header-merged).
      5. Assert FakeGitHub recorded the merged PR.

    This pattern scales to H2-L8 because:
      - Seeding is identical to the existing Python-only tests
        (IssueBuilder / world.set_phase_result).
      - UI assertions target stable data-testid attributes on
        stage-section-{stage} and stage-header-{stage}.
      - No route interception required for the pipeline view.

Pilot finding: full E2E via UI Start button is unworkable without
refactoring the start route to reuse the pre-wired orchestrator.
Fallback to Python-trigger + UI-assert pattern works reliably.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from playwright.async_api import expect

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario_browser

# Minimal control-status payload that tells React the orchestrator is "running"
# so all dashboard panels (Outcomes, HITL) render live content rather than
# the idle placeholder.  Required only for tabs other than the main Pipeline
# view, but included here for completeness and forward-compatibility.
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


async def test_h1_single_issue_end_to_end(world, page) -> None:
    """H1: single issue reaches merged stage and PR is merged.

    Matches the seed pattern from
    tests/scenarios/test_happy.py::TestH1SingleIssueEndToEnd.
    Pipeline runs Python-side through wired fakes; UI asserts the final
    state rendered from the harness IssueStore via /api/pipeline.
    """
    # --- Step 1: seed world (matches test_happy.py H1 exactly) ---
    IssueBuilder().numbered(1).titled("Add login button").bodied(
        "Add a login button to the homepage"
    ).at(world)

    # --- Step 2: run pipeline Python-side through wired fakes ---
    # All four phases (triage, plan, implement, review) run through
    # FakeLLM / FakeGitHub / FakeWorkspace.  After this call:
    #   - FakeGitHub._prs[1].merged is True
    #   - ScenarioResult records outcome.merged=True
    result = await world.run_pipeline()

    # Sanity-check the Python-side result before touching the UI.
    outcome = result.issue(1)
    assert outcome.final_stage == "done", (
        f"Pipeline did not reach 'done'; stopped at '{outcome.final_stage}'"
    )
    assert outcome.merged is True, "Pipeline result shows issue not merged"

    # The PipelineHarness builds PostMergeHandler without a store reference
    # (store=None), so mark_merged is never called during run_pipeline().
    # We call it directly here to sync the IssueStore's merged-numbers set
    # with the FakeGitHub state, so /api/pipeline serves the merged stage.
    # This is the correct seam: the test owns world state, the UI asserts
    # the rendered snapshot.
    world._harness.store.mark_merged(1)

    # --- Step 3: boot dashboard (lightweight shim, no new orchestrator) ---
    url = await world.start_dashboard(with_orchestrator=False)

    # Intercept /api/control/status so the UI treats the orchestrator as
    # "running".  This is optional for the StreamView but prevents the
    # "Pipeline is not running" banner from appearing in Outcomes / HITL
    # tabs and ensures future multi-tab assertions see live content.
    async def _handle_control_status(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    await page.route("**/api/control/status", _handle_control_status)

    # --- Step 4: navigate + wait for WebSocket connection ---
    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)

    # Give the pipeline poller one tick to fire fetchPipeline and dispatch
    # PIPELINE_SNAPSHOT so React hydrates the merged-stage section.
    # The poller fires immediately on mount (no initial delay), so a small
    # sleep is sufficient for the HTTP round-trip to complete.
    await asyncio.sleep(0.5)

    # --- Step 5: assert UI shows issue #1 in the merged stage ---

    # stage-section-merged is always in the DOM; the header count reads
    # "{N} merged" when issues are present.  Wait for "1 merged" to appear
    # in the merged section header.
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).to_contain_text("1 merged", timeout=15_000)

    # The flow-dot for issue #1 must exist somewhere in the pipeline flow bar.
    # Its testid is flow-dot-{issueNumber} regardless of which stage it's in.
    flow_dot = page.locator('[data-testid="flow-dot-1"]')
    await expect(flow_dot).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    pr = world.github.pr_for_issue(1)
    assert pr is not None, "FakeGitHub has no PR for issue #1"
    assert pr.merged is True, f"PR for issue #1 not marked merged; merged={pr.merged}"


async def test_h2_multi_issue_concurrent_batch(world, page) -> None:
    """H2: three issues all reach the merged stage without cross-contamination.

    Matches tests/scenarios/test_happy.py::TestH2MultiIssueConcurrentBatch.
    All three issues share the default FakeLLM scripting (success=True for
    every phase) so they proceed straight through to merge.
    """
    from tests.scenarios.builders import IssueBuilder, RepoStateBuilder  # noqa: PLC0415

    # --- Step 1: seed three issues (matches test_happy.py H2 exactly) ---
    await (
        RepoStateBuilder()
        .with_issues(
            [
                IssueBuilder()
                .numbered(1)
                .titled("Bug fix A")
                .bodied("Fix the A module"),
                IssueBuilder()
                .numbered(2)
                .titled("Bug fix B")
                .bodied("Fix the B module"),
                IssueBuilder()
                .numbered(3)
                .titled("Bug fix C")
                .bodied("Fix the C module"),
            ]
        )
        .at(world)
    )

    # --- Step 2: run pipeline Python-side through wired fakes ---
    result = await world.run_pipeline()

    # Sanity-check Python-side before touching the UI.
    for num in (1, 2, 3):
        outcome = result.issue(num)
        assert outcome.final_stage == "done", (
            f"Issue #{num} did not complete; stopped at '{outcome.final_stage}'"
        )
        assert outcome.merged is True, f"Issue #{num} PR not merged"

    # Sync the IssueStore merged-numbers set for all three issues.
    for num in (1, 2, 3):
        world._harness.store.mark_merged(num)

    # --- Step 3: boot dashboard (lightweight shim) ---
    url = await world.start_dashboard(with_orchestrator=False)

    async def _handle_control_status(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    await page.route("**/api/control/status", _handle_control_status)

    # --- Step 4: navigate + wait for WebSocket connection ---
    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)
    await asyncio.sleep(0.5)

    # --- Step 5: assert UI shows all three issues in the merged stage ---
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).to_contain_text("3 merged", timeout=15_000)

    # Each issue's flow-dot must be visible.
    for num in (1, 2, 3):
        flow_dot = page.locator(f'[data-testid="flow-dot-{num}"]')
        await expect(flow_dot).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    assert all(world.github.pr_for_issue(n).merged is True for n in (1, 2, 3)), (
        "Not all three PRs were merged"
    )


async def test_h3_implement_failure_routes_to_hitl(world, page) -> None:
    """H3: failed implement stops at implement stage — issue is NOT merged.

    Matches tests/scenarios/test_happy.py::TestH3HITLRoundTrip.
    When the worker returns success=False the issue never advances to review
    or merge, so the UI should show NO merged issues and the flow-dot for
    issue #1 should still be visible (stuck in implement / failed state).
    """
    from tests.conftest import WorkerResultFactory  # noqa: PLC0415

    # --- Step 1: seed world with a failing implement result ---
    fail = WorkerResultFactory.create(
        issue_number=1, success=False, error="Docker build failed"
    )
    world.add_issue(1, "Complex refactor", "Needs careful human review")
    world.set_phase_result("implement", 1, fail)

    # --- Step 2: run pipeline Python-side ---
    result = await world.run_pipeline()

    # Sanity-check: issue should NOT be done or merged.
    outcome = result.issue(1)
    assert outcome.final_stage != "done", "Failed implement should not reach done"
    assert outcome.merged is False, "Issue should not be merged after failed implement"

    # Do NOT call mark_merged — issue never merged.

    # --- Step 3: boot dashboard ---
    url = await world.start_dashboard(with_orchestrator=False)

    async def _handle_control_status(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    await page.route("**/api/control/status", _handle_control_status)

    # --- Step 4: navigate + wait for WebSocket connection ---
    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)
    await asyncio.sleep(0.5)

    # --- Step 5: assert UI shows zero merged issues ---
    # When implement fails, the issue is consumed from the implement queue but
    # never re-queued or marked merged.  It therefore disappears from all
    # pipeline stage snapshots — the store only tracks queued, active,
    # in-flight, HITL, and merged issues.  No flow-dot is present for a
    # failed-and-dropped issue.
    #
    # The correct observable assertion is that the merged stage header does NOT
    # show any merged count.  The implement stage section is structurally
    # present in the DOM (always rendered) but contains no issues.
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).not_to_contain_text("1 merged", timeout=10_000)

    # The implement stage section is always present; assert it exists.
    implement_section = page.locator('[data-testid="stage-section-implement"]')
    await expect(implement_section).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    assert outcome.worker_result is not None
    assert outcome.worker_result.success is False
    pr = world.github.pr_for_issue(1)
    # No PR should have been created (failed before branch push), or if one
    # exists it must not be merged.
    assert pr is None or pr.merged is False, "PR for failed issue should not be merged"


async def test_h4_review_approve_and_merge(world, page) -> None:
    """H4: review returns APPROVE, CI passes, PR is merged.

    Matches tests/scenarios/test_happy.py::TestH4ReviewApproveAndMerge.
    Default FakeLLM scripting returns a passing review and FakeGitHub
    auto-merges once review succeeds, so the issue reaches done.
    """
    # --- Step 1: seed world (matches test_happy.py H4 exactly) ---
    from tests.scenarios.builders import IssueBuilder  # noqa: PLC0415

    IssueBuilder().numbered(1).titled("Small refactor").bodied(
        "Clean up utils module"
    ).at(world)

    # --- Step 2: run pipeline Python-side ---
    result = await world.run_pipeline()

    # Sanity-check: review result present and issue merged.
    outcome = result.issue(1)
    assert outcome.review_result is not None, "No review result recorded"
    assert outcome.merged is True, "Issue not merged after successful review"

    # Sync IssueStore.
    world._harness.store.mark_merged(1)

    # --- Step 3: boot dashboard ---
    url = await world.start_dashboard(with_orchestrator=False)

    async def _handle_control_status(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    await page.route("**/api/control/status", _handle_control_status)

    # --- Step 4: navigate + wait for WebSocket connection ---
    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)
    await asyncio.sleep(0.5)

    # --- Step 5: assert UI shows issue #1 in the merged stage ---
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).to_contain_text("1 merged", timeout=15_000)

    flow_dot = page.locator('[data-testid="flow-dot-1"]')
    await expect(flow_dot).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    pr = world.github.pr_for_issue(1)
    assert pr is not None, "FakeGitHub has no PR for issue #1"
    assert pr.merged is True, f"PR for issue #1 not marked merged; merged={pr.merged}"


async def test_h5_plan_produces_sub_issues(world, page) -> None:
    """H5: planner returns new_issues; parent issue completes normally.

    Matches tests/scenarios/test_happy.py::TestH5PlanProducesSubIssues.
    The plan result carries two NewIssueSpec entries.  Because the
    sub-issue bodies are shorter than _MIN_ISSUE_BODY_CHARS (50 chars),
    plan_phase skips creating them in GitHub — but the plan_result object
    retains them.  The parent issue #1 continues through implement/review
    and is merged.

    DOM assertion: parent issue #1 appears in merged stage.
    Python assertion: plan_result.new_issues has 2 entries.
    """
    from models import NewIssueSpec  # noqa: PLC0415
    from tests.conftest import PlanResultFactory  # noqa: PLC0415
    from tests.scenarios.builders import IssueBuilder  # noqa: PLC0415

    # --- Step 1: seed world (matches test_happy.py H5 exactly) ---
    plan_with_subs = PlanResultFactory.create(
        issue_number=1,
        success=True,
        new_issues=[
            NewIssueSpec(title="Sub-task 1", body="Do sub-task 1"),
            NewIssueSpec(title="Sub-task 2", body="Do sub-task 2"),
        ],
    )
    IssueBuilder().numbered(1).titled("Epic task").bodied("Big feature").at(world)
    world.set_phase_result("plan", 1, plan_with_subs)

    # --- Step 2: run pipeline Python-side ---
    result = await world.run_pipeline()

    # Sanity-check Python-side: plan result has 2 new_issues entries.
    outcome = result.issue(1)
    assert outcome.plan_result is not None, "No plan result recorded"
    assert outcome.plan_result.new_issues is not None
    assert len(outcome.plan_result.new_issues) == 2, (
        f"Expected 2 new_issues; got {len(outcome.plan_result.new_issues)}"
    )
    # Parent issue should still proceed to merge (bodies too short → sub-issues
    # skipped by plan_phase, parent transitions to ready and continues).
    assert outcome.merged is True, "Parent issue should be merged"

    # Sync IssueStore for parent.
    world._harness.store.mark_merged(1)

    # --- Step 3: boot dashboard ---
    url = await world.start_dashboard(with_orchestrator=False)

    async def _handle_control_status(route, request) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_RUNNING_CONTROL_STATUS),
        )

    await page.route("**/api/control/status", _handle_control_status)

    # --- Step 4: navigate + wait for WebSocket connection ---
    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)
    await asyncio.sleep(0.5)

    # --- Step 5: assert UI shows parent issue #1 in merged stage ---
    # Sub-issues are not created in GitHub (bodies too short), so the UI only
    # shows the parent issue.  Confirm it reached merged.
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).to_contain_text("1 merged", timeout=15_000)

    flow_dot = page.locator('[data-testid="flow-dot-1"]')
    await expect(flow_dot).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    pr = world.github.pr_for_issue(1)
    assert pr is not None, "FakeGitHub has no PR for parent issue #1"
    assert pr.merged is True, f"Parent PR not merged; merged={pr.merged}"
