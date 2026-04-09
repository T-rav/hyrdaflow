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
        from tests.scenarios.fakes.fake_llm import FakeLLM

        llm = FakeLLM()
        scripted = TriageResultFactory.create(issue_number=1, ready=False)
        llm.script_triage(1, [scripted])

        task = TaskFactory.create(id=1)
        result = await llm.triage_runner.evaluate(task)
        assert result.ready is False

    async def test_triage_default_when_no_script(self):
        from tests.scenarios.fakes.fake_llm import FakeLLM

        llm = FakeLLM()
        task = TaskFactory.create(id=1)
        result = await llm.triage_runner.evaluate(task)
        assert result.ready is True

    async def test_plan_pops_sequence(self):
        from tests.scenarios.fakes.fake_llm import FakeLLM

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
        from tests.scenarios.fakes.fake_llm import FakeLLM

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
        from models import ReviewVerdict
        from tests.conftest import PRInfoFactory
        from tests.scenarios.fakes.fake_llm import FakeLLM

        llm = FakeLLM()
        reject = ReviewResultFactory.create(
            issue_number=1, verdict=ReviewVerdict.REQUEST_CHANGES
        )
        llm.script_review(1, [reject])

        pr = PRInfoFactory.create(issue_number=1)
        task = TaskFactory.create(id=1)
        result = await llm.reviewers.review(pr, task, Path("/tmp"), "diff")
        assert result.verdict == ReviewVerdict.REQUEST_CHANGES

    async def test_tracing_context_methods_are_noops(self):
        from tests.scenarios.fakes.fake_llm import FakeLLM

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
