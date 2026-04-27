"""Tests for FakeLLM scripted runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import (
    PlanResultFactory,
    ReviewResultFactory,
    TaskFactory,
    TriageResultFactory,
    WorkerResultFactory,
)

pytestmark = pytest.mark.scenario


class TestFakeLLMScriptedResults:
    async def test_returns_scripted_triage_result(self):
        from mockworld.fakes.fake_llm import FakeLLM

        llm = FakeLLM()
        scripted = TriageResultFactory.create(issue_number=1, ready=False)
        llm.script_triage(1, [scripted])

        task = TaskFactory.create(id=1)
        result = await llm.triage_runner.evaluate(task)
        assert result.ready is False

    async def test_triage_default_when_no_script(self):
        from mockworld.fakes.fake_llm import FakeLLM

        llm = FakeLLM()
        task = TaskFactory.create(id=1)
        result = await llm.triage_runner.evaluate(task)
        assert result.ready is True

    async def test_plan_pops_sequence(self):
        from mockworld.fakes.fake_llm import FakeLLM

        llm = FakeLLM()
        fail = PlanResultFactory.create(issue_number=1, success=False)
        succeed = PlanResultFactory.create(issue_number=1, success=True)
        llm.script_plan(1, [fail, succeed])

        task = TaskFactory.create(id=1)
        r1 = await llm.planners.plan(task)
        r2 = await llm.planners.plan(task)
        assert r1.success is False
        assert r2.success is True

    async def test_implement_returns_scripted_worker_result(self):
        from mockworld.fakes.fake_llm import FakeLLM

        llm = FakeLLM()
        fail_result = WorkerResultFactory.create(
            issue_number=1, success=False, error="compilation error"
        )
        llm.script_implement(1, [fail_result])

        task = TaskFactory.create(id=1)
        result = await llm.agents.run(task, Path("/tmp"), "branch")
        assert result.success is False
        assert result.error == "compilation error"

    async def test_review_returns_scripted_result(self):
        from mockworld.fakes.fake_llm import FakeLLM
        from models import ReviewVerdict
        from tests.conftest import PRInfoFactory

        llm = FakeLLM()
        reject = ReviewResultFactory.create(
            issue_number=1, verdict=ReviewVerdict.REQUEST_CHANGES
        )
        llm.script_review(1, [reject])

        pr = PRInfoFactory.create(issue_number=1)
        task = TaskFactory.create(id=1)
        result = await llm.reviewers.review(pr, task, Path("/tmp"), "diff")
        assert result.verdict == ReviewVerdict.REQUEST_CHANGES

    async def test_last_scripted_result_is_sticky(self):
        from mockworld.fakes.fake_llm import FakeLLM

        llm = FakeLLM()
        reject = PlanResultFactory.create(issue_number=1, success=False)
        llm.script_plan(1, [reject])

        task = TaskFactory.create(id=1)
        r1 = await llm.planners.plan(task)
        r2 = await llm.planners.plan(task)
        r3 = await llm.planners.plan(task)
        # All three calls return the scripted rejection, not the default success
        assert r1.success is False
        assert r2.success is False
        assert r3.success is False

    async def test_tracing_context_methods_are_noops(self):
        from mockworld.fakes.fake_llm import FakeLLM

        llm = FakeLLM()
        # These must not raise
        llm.triage_runner.set_tracing_context(None)
        llm.triage_runner.clear_tracing_context()
        llm.planners.set_tracing_context(None)
        llm.planners.clear_tracing_context()
        llm.agents.set_tracing_context(None)
        llm.agents.clear_tracing_context()
        llm.reviewers.set_tracing_context(None)
        llm.reviewers.clear_tracing_context()


async def test_token_budget_planner_passes_first_call_then_fails() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_plan(
        1,
        [
            PlanResultFactory.create(issue_number=1, success=True),
            PlanResultFactory.create(issue_number=1, success=True),
        ],
    )
    llm.set_token_budget(issue_number=1, max_tokens=200, tokens_per_call=150)

    first = await llm.planners.plan(TaskFactory.create(id=1))
    second = await llm.planners.plan(TaskFactory.create(id=1))

    assert first.success is True
    assert second.success is False
    assert "token_budget" in (second.error or "")


async def test_token_budget_reviewer_same_behavior() -> None:
    """Reviewer also honors the token budget."""
    from mockworld.fakes.fake_llm import FakeLLM
    from tests.conftest import PRInfoFactory

    llm = FakeLLM()
    llm.script_review(
        1,
        [
            ReviewResultFactory.create(pr_number=42, issue_number=1),
            ReviewResultFactory.create(pr_number=42, issue_number=1),
        ],
    )
    llm.set_token_budget(issue_number=1, max_tokens=200, tokens_per_call=150)

    pr = PRInfoFactory.create(number=42, issue_number=1, branch="feat/x")
    issue = TaskFactory.create(id=1)
    worktree = Path("/tmp/wt")

    first = await llm.reviewers.review(pr, issue, worktree, "")
    second = await llm.reviewers.review(pr, issue, worktree, "")

    assert first.verdict is not None  # normal scripted result
    # Second call exceeds budget — replaced with a failure result
    assert "token_budget" in (second.error or "")


async def test_no_budget_set_means_no_gating() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_plan(1, [PlanResultFactory.create(issue_number=1, success=True)])
    result = await llm.planners.plan(TaskFactory.create(id=1))
    assert result.success is True


async def test_triage_runner_script_decomposition_returns_scripted_result() -> None:
    from mockworld.fakes.fake_llm import FakeLLM
    from models import EpicDecompResult, NewIssueSpec

    llm = FakeLLM()
    decomp = EpicDecompResult(
        should_decompose=True,
        children=[
            NewIssueSpec(title="child-a", body=""),
            NewIssueSpec(title="child-b", body=""),
        ],
    )
    llm.triage_runner.script_decomposition(42, decomp)

    result = await llm.triage_runner.run_decomposition(TaskFactory.create(id=42))
    assert result.should_decompose is True
    assert len(result.children) == 2


async def test_triage_runner_default_decomposition_is_false() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    result = await llm.triage_runner.run_decomposition(TaskFactory.create(id=99))
    assert result.should_decompose is False


async def test_review_runner_captures_code_scanning_alerts() -> None:
    from mockworld.fakes.fake_llm import FakeLLM
    from models import CodeScanningAlert
    from tests.conftest import PRInfoFactory

    llm = FakeLLM()
    alerts = [
        CodeScanningAlert(
            number=1,
            severity="error",
            security_severity="high",
            path="x.py",
            start_line=1,
            rule="r",
            message="m",
        ),
    ]
    pr = PRInfoFactory.create(number=42, issue_number=7, branch="feat/x")
    task = TaskFactory.create(id=7)
    await llm.reviewers.review(pr, task, Path("/tmp"), "", code_scanning_alerts=alerts)

    assert llm.alerts_received_by_reviewer(7) == alerts


async def test_review_runner_no_alerts_captures_empty_list() -> None:
    from mockworld.fakes.fake_llm import FakeLLM
    from tests.conftest import PRInfoFactory

    llm = FakeLLM()
    pr = PRInfoFactory.create(number=42, issue_number=7, branch="feat/x")
    task = TaskFactory.create(id=7)
    await llm.reviewers.review(pr, task, Path("/tmp"), "")

    assert llm.alerts_received_by_reviewer(7) == []


async def test_fix_ci_default_returns_fixes_made_true() -> None:
    """Default fix_ci (no script) returns fixes_made=True."""
    from mockworld.fakes.fake_llm import FakeLLM
    from tests.conftest import PRInfoFactory

    llm = FakeLLM()
    pr = PRInfoFactory.create(number=42, issue_number=1, branch="feat/x")
    task = TaskFactory.create(id=1)
    result = await llm.reviewers.fix_ci(pr, task, Path("/tmp"), "CI failed")

    assert result.fixes_made is True
    assert result.ci_passed is True


async def test_fix_ci_scripted_result_overrides_default() -> None:
    """script_fix_ci causes fix_ci to return the scripted result (fixes_made=False)."""
    from mockworld.fakes.fake_llm import FakeLLM
    from models import ReviewVerdict
    from tests.conftest import PRInfoFactory

    llm = FakeLLM()
    scripted = ReviewResultFactory.create(
        pr_number=42,
        issue_number=1,
        verdict=ReviewVerdict.REQUEST_CHANGES,
        fixes_made=False,
        ci_passed=False,
    )
    llm.script_fix_ci(1, scripted)

    pr = PRInfoFactory.create(number=42, issue_number=1, branch="feat/x")
    task = TaskFactory.create(id=1)
    result = await llm.reviewers.fix_ci(pr, task, Path("/tmp"), "CI failed")

    assert result.fixes_made is False
    assert result.ci_passed is False
    assert result.verdict == ReviewVerdict.REQUEST_CHANGES
