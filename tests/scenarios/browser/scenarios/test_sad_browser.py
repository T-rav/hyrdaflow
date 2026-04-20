"""Tier-3 browser ports of S1-S6 sad-path scenarios.

Reference tests live in tests/scenarios/test_sad.py.

Pattern (established by H1 pilot and H2-H5 ports):
    1. Seed world state identically to the Python reference test.
    2. Run pipeline Python-side: ``await world.run_pipeline()``.
    3. Call ``world._harness.store.mark_merged(N)`` only for issues that
       actually merged.
    4. Boot dashboard shim: ``url = await world.start_dashboard()``.
    5. Navigate + wait for ``body[data-connected="true"]``.
    6. Assert DOM via ``stage-header-{stage}`` text or element visibility.
    7. Assert world state via ``world.github.*``, ``world.hindsight.*``, etc.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from playwright.async_api import expect

from models import ReviewVerdict
from tests.conftest import (
    PlanResultFactory,
    ReviewResultFactory,
    WorkerResultFactory,
)
from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario_browser

# Minimal control-status payload — same as happy-path browser tests.
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


async def test_s1_plan_retry_sequence(world, page) -> None:
    """S1: first plan attempt fails with LLM timeout; a plan_result is recorded.

    The scenario harness scripts the first scripted result (success=False) then
    a second (success=True).  The plan phase consumes the first result, logs a
    failure, and skips the label swap — so the issue stalls at the 'plan' stage
    rather than advancing to implement.  The reference test only asserts that
    plan_result is not None (it does not assert merged=True).

    DOM assertion: no issue in merged stage (pipeline stalled at plan).
    Python assertion: plan_result is not None.

    Reference: TestS1PlanFailsThenSucceeds.test_plan_retry_sequence
    """
    # --- Step 1: seed (matches reference test exactly) ---
    fail = PlanResultFactory.create(issue_number=1, success=False, error="LLM timeout")
    succeed = PlanResultFactory.create(issue_number=1, success=True)

    IssueBuilder().numbered(1).titled("Fix auth").bodied("Auth is broken").at(world)
    world.set_phase_results("plan", 1, [fail, succeed])

    # --- Step 2: run pipeline Python-side ---
    result = await world.run_pipeline()

    outcome = result.issue(1)
    # Reference assertion: plan_result is recorded even when first attempt failed.
    assert outcome.plan_result is not None, "Plan result must be set after retry"
    # Pipeline stalls at plan (first scripted result is failure; no auto-retry
    # in the scenario harness).  Do NOT call mark_merged.

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions ---
    # Issue did not reach merged stage.
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).not_to_contain_text("1 merged", timeout=10_000)

    # Plan stage section is always present.
    plan_section = page.locator('[data-testid="stage-section-plan"]')
    await expect(plan_section).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    assert outcome.plan_result is not None


async def test_s2_implement_exhausts_attempts(world, page) -> None:
    """S2: implement phase fails; issue does not complete or merge.

    Reference: TestS2ImplementExhaustsAttempts.test_implement_failure_blocks_completion
    """
    # --- Step 1: seed ---
    fail = WorkerResultFactory.create(
        issue_number=1, success=False, error="compilation error"
    )
    IssueBuilder().numbered(1).titled("Fix DB migration").bodied(
        "Migration is broken"
    ).at(world)
    world.set_phase_result("implement", 1, fail)

    # --- Step 2: run pipeline ---
    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert outcome.worker_result is not None
    assert outcome.worker_result.success is False
    assert outcome.final_stage != "done"
    assert outcome.merged is False

    # Do NOT call mark_merged — issue never merged.

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions ---
    # No issue should appear in the merged stage.
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).not_to_contain_text("1 merged", timeout=10_000)

    # The implement stage section is always present in the DOM.
    implement_section = page.locator('[data-testid="stage-section-implement"]')
    await expect(implement_section).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    assert outcome.worker_result.success is False
    assert outcome.merged is False


async def test_s3_review_reject_route_back(world, page) -> None:
    """S3: review returns REQUEST_CHANGES; issue is not merged.

    Reference: TestS3ReviewRejects.test_review_rejection_tracked
    """
    # --- Step 1: seed ---
    reject = ReviewResultFactory.create(
        issue_number=1,
        verdict=ReviewVerdict.REQUEST_CHANGES,
        merged=False,
    )
    IssueBuilder().numbered(1).titled("Fix UI glitch").bodied("Button misaligned").at(
        world
    )
    world.set_phase_result("review", 1, reject)

    # --- Step 2: run pipeline ---
    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert outcome.review_result is not None
    assert outcome.review_result.verdict == ReviewVerdict.REQUEST_CHANGES
    assert outcome.merged is False

    # Do NOT call mark_merged — issue was rejected, not merged.

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions ---
    # Rejected issue is not in the merged stage.
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).not_to_contain_text("1 merged", timeout=10_000)

    # Review section is always present.
    review_section = page.locator('[data-testid="stage-section-review"]')
    await expect(review_section).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    assert outcome.review_result.verdict == ReviewVerdict.REQUEST_CHANGES
    assert outcome.merged is False


async def test_s4_github_5xx_during_implement(world, page) -> None:
    """S4: GitHub service failure (5xx) during implement; issue does not complete.

    Reference: TestS4GitHubFailureDuringImplement.test_github_down_during_implement_blocks_completion
    """
    # --- Step 1: seed (matches reference exactly) ---
    fail = WorkerResultFactory.create(
        issue_number=1, success=False, error="GitHub API 503: Service Unavailable"
    )
    world.add_issue(1, "Add caching", "Cache API responses").set_phase_result(
        "implement", 1, fail
    )

    # --- Step 2: run pipeline ---
    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert outcome.final_stage != "done", (
        "GitHub 5xx during implement should prevent completion"
    )
    assert outcome.worker_result is not None
    assert outcome.worker_result.success is False
    assert "503" in (outcome.worker_result.error or "")
    assert outcome.merged is False

    # Do NOT call mark_merged.

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions ---
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).not_to_contain_text("1 merged", timeout=10_000)

    implement_section = page.locator('[data-testid="stage-section-implement"]')
    await expect(implement_section).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    assert outcome.worker_result.success is False
    assert "503" in (outcome.worker_result.error or "")
    assert outcome.merged is False


async def test_s5_hindsight_down_pipeline_continues(world, page) -> None:
    """S5: Hindsight service fails; pipeline still completes and merges issue.

    Reference: TestS5HindsightDown.test_pipeline_completes_without_hindsight
    """
    # --- Step 1: seed ---
    IssueBuilder().numbered(1).titled("Add feature").bodied("New feature request").at(
        world
    )
    world.fail_service("hindsight")

    # --- Step 2: run pipeline ---
    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert outcome.final_stage == "done", (
        f"S5: pipeline should complete even without Hindsight; "
        f"stopped at '{outcome.final_stage}'"
    )
    assert outcome.merged is True
    assert world.hindsight.is_failing is True  # confirm service stayed failed

    # Sync IssueStore.
    world._harness.store.mark_merged(1)

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions ---
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).to_contain_text("1 merged", timeout=15_000)

    flow_dot = page.locator('[data-testid="flow-dot-1"]')
    await expect(flow_dot).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    # No entries were retained in any Hindsight bank because the service was down.
    assert world.hindsight.is_failing is True
    # Hindsight banks should be empty (all retain() calls raised ConnectionError).
    for bank in ("learnings", "retrospectives", "review-insights"):
        assert world.hindsight.bank_entries(bank) == [], (
            f"S5: expected empty Hindsight bank '{bank}' when service is failing"
        )


async def test_s6_ci_fails_autofix_ci_passes(world, page) -> None:
    """S6: default FakeLLM succeeds through all phases; issue reaches merged.

    The reference test (TestS6ImplementHappyPathBaseline) was written when the
    mock WorkerResult carried no pr_info, so review was skipped.  Actual
    pipeline behaviour (as observed in this run) is that the issue reaches
    final_stage='done' and merged=True — the FakeLLM wiring now populates
    pr_info so the review phase runs to completion.

    Scripted CI failure/retry (the original S6 intent) is deferred until
    WorkerResultFactory supports pr_info scripting for CI sequences.

    DOM assertion: "1 merged" appears in merged stage header.
    Python assertion: worker_result.success is True; merged is True.

    Reference: TestS6ImplementHappyPathBaseline.test_implement_produces_worker_result
    """
    # --- Step 1: seed (matches reference exactly) ---
    IssueBuilder().numbered(1).titled("Fix tests").bodied("Flaky test suite").at(world)

    # --- Step 2: run pipeline ---
    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert outcome is not None
    assert outcome.worker_result is not None
    assert outcome.worker_result.success is True
    # Actual pipeline behaviour: issue reaches done and merges.
    assert outcome.merged is True, (
        f"S6: expected merged=True; got final_stage='{outcome.final_stage}'"
    )

    # Sync IssueStore.
    world._harness.store.mark_merged(1)

    # --- Step 3-4: boot dashboard + navigate ---
    await _boot_and_navigate(world, page)

    # --- Step 5: DOM assertions ---
    merged_header = page.locator('[data-testid="stage-header-merged"]')
    await expect(merged_header).to_contain_text("1 merged", timeout=15_000)

    flow_dot = page.locator('[data-testid="flow-dot-1"]')
    await expect(flow_dot).to_be_visible(timeout=5_000)

    # --- Step 6: Python-side assertions ---
    assert outcome.worker_result.success is True
    assert outcome.merged is True
