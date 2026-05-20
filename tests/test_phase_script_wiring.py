"""Tests that production runners consume FakeLLM phase scripts via the sentinel.

The sentinel pattern: scenarios attach ``_mockworld_fake_llm`` (a ``FakeLLM``
instance carrying ``_is_fake_adapter=True``) to the runner instance; the
production method checks the sentinel and synthesizes a result from the
scripted payload, skipping the subprocess dispatch entirely.

Without the sentinel attached, the runners must behave exactly as production
(no FakeLLM coupling leaks into the non-scripted path).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# DiscoverRunner._evaluate_brief
# ---------------------------------------------------------------------------


class _FakeTask:
    def __init__(self, task_id: int = 1, title: str = "t", body: str = "") -> None:
        self.id = task_id
        self.title = title
        self.body = body


async def test_discover_evaluate_brief_consumes_script(monkeypatch) -> None:
    """DiscoverRunner._evaluate_brief returns the scripted outcome via sentinel."""
    from discover_runner import DiscoverRunner
    from mockworld.fakes.fake_llm import FakeLLM

    # Build a minimal DiscoverRunner. We bypass __init__ by setting attrs
    # directly — _evaluate_brief only touches _mockworld_fake_llm + the
    # builtin skill registry; both are intercepted by the sentinel branch.
    runner = DiscoverRunner.__new__(DiscoverRunner)
    fake = FakeLLM()
    fake.script_discover(
        7, coherent=False, queries_required=["new q"], summary="rejected"
    )
    runner._mockworld_fake_llm = fake

    task = _FakeTask(task_id=7, title="x", body="y")
    passed, summary, findings = await runner._evaluate_brief(task, "brief")
    assert passed is False
    assert "rejected" in summary
    assert findings == []

    # Next call has nothing scripted → returns None and falls through to
    # the skill-registry path. We don't exercise that here (would require
    # a real config + subprocess); just confirm the sentinel branch is
    # idempotent across exhausted queues.
    from discover_runner import _consume_mockworld_discover_script

    assert _consume_mockworld_discover_script(runner, 7) is None


async def test_discover_dispatch_expander_returns_scripted_queries() -> None:
    """_dispatch_expander reads the scripted queries stashed by _evaluate_brief."""
    from discover_runner import (
        DiscoverRunner,
        _consume_mockworld_discover_script,
    )
    from mockworld.fakes.fake_llm import FakeLLM

    runner = DiscoverRunner.__new__(DiscoverRunner)
    fake = FakeLLM()
    fake.script_discover(8, coherent=False, queries_required=["q-a", "q-b"])
    runner._mockworld_fake_llm = fake

    # Drive the evaluator path so queries land in the pending-queries buffer.
    task = _FakeTask(task_id=8)
    _consume_mockworld_discover_script(runner, 8)

    queries = await runner._dispatch_expander(
        task=task,
        original_brief="b",
        coherence_failure_reason="r",
        failure_findings=[],
    )
    assert queries == ["q-a", "q-b"]


async def test_discover_without_sentinel_is_unaffected() -> None:
    """Runners without the sentinel must behave as production (no FakeLLM coupling)."""
    from discover_runner import _consume_mockworld_discover_script

    class _DummyRunner:
        pass

    assert _consume_mockworld_discover_script(_DummyRunner(), 1) is None


# ---------------------------------------------------------------------------
# PlanReviewer.review
# ---------------------------------------------------------------------------


@dataclass
class _StubPlanResult:
    success: bool = True
    plan: str = "plan body"


async def test_plan_reviewer_consumes_scripted_reject() -> None:
    """PlanReviewer.review returns blocking findings when verdict=reject."""
    from mockworld.fakes.fake_llm import FakeLLM
    from models import PlanFindingSeverity
    from plan_reviewer import PlanReviewer

    reviewer = PlanReviewer.__new__(PlanReviewer)
    fake = FakeLLM()
    fake.script_plan_review(
        9, verdict="reject", gaps=["missing tests", "no rollback plan"]
    )
    reviewer._mockworld_fake_llm = fake

    task = _FakeTask(task_id=9)
    plan = _StubPlanResult()
    review = await reviewer.review(task, plan, plan_version=1)
    assert review.success is True
    assert len(review.findings) == 2
    # All scripted gaps land as blocking HIGH findings so route-back fires.
    assert all(f.severity == PlanFindingSeverity.HIGH for f in review.findings)
    assert review.has_blocking_findings


async def test_plan_reviewer_consumes_scripted_accept() -> None:
    """PlanReviewer.review returns a clean review when verdict=accept."""
    from mockworld.fakes.fake_llm import FakeLLM
    from plan_reviewer import PlanReviewer

    reviewer = PlanReviewer.__new__(PlanReviewer)
    fake = FakeLLM()
    fake.script_plan_review(10, verdict="accept")
    reviewer._mockworld_fake_llm = fake

    task = _FakeTask(task_id=10)
    plan = _StubPlanResult()
    review = await reviewer.review(task, plan, plan_version=1)
    assert review.success is True
    assert review.findings == []
    assert not review.has_blocking_findings


async def test_plan_reviewer_without_sentinel_no_op() -> None:
    """_consume_mockworld_plan_review_script returns None without the sentinel."""
    from plan_reviewer import _consume_mockworld_plan_review_script

    class _DummyReviewer:
        pass

    assert _consume_mockworld_plan_review_script(_DummyReviewer(), 1) is None


# ---------------------------------------------------------------------------
# ExpertCouncil.vote / vote_diversified
# ---------------------------------------------------------------------------


async def test_expert_council_vote_synthesizes_consensus() -> None:
    """vote() returns a CouncilResult with has_consensus=True for consensus scripts."""
    from expert_council import ExpertCouncil
    from mockworld.fakes.fake_llm import FakeLLM

    council = ExpertCouncil.__new__(ExpertCouncil)
    fake = FakeLLM()
    fake.script_shape_council(11, {1: "consensus"})
    council._mockworld_fake_llm = fake

    task = _FakeTask(task_id=11)
    result = await council.vote(task, "directions")
    assert result.has_consensus is True
    assert result.winning_direction == "A"


async def test_expert_council_vote_synthesizes_split() -> None:
    """vote() returns a split CouncilResult for split scripts."""
    from expert_council import ExpertCouncil
    from mockworld.fakes.fake_llm import FakeLLM

    council = ExpertCouncil.__new__(ExpertCouncil)
    fake = FakeLLM()
    fake.script_shape_council(12, {1: "split"})
    council._mockworld_fake_llm = fake

    task = _FakeTask(task_id=12)
    result = await council.vote(task, "directions")
    assert result.has_consensus is False
    assert result.winning_direction is None


async def test_expert_council_round_counter_advances() -> None:
    """Successive vote() calls advance the per-issue round counter.

    Scenario: {1: "split", 2: "split", 3: "consensus"} exercises W4
    diversified round-3.
    """
    from expert_council import ExpertCouncil
    from mockworld.fakes.fake_llm import FakeLLM

    council = ExpertCouncil.__new__(ExpertCouncil)
    fake = FakeLLM()
    fake.script_shape_council(13, {1: "split", 2: "split", 3: "consensus"})
    council._mockworld_fake_llm = fake

    task = _FakeTask(task_id=13)
    r1 = await council.vote(task, "directions")
    r2 = await council.vote(task, "directions")
    r3 = await council.vote_diversified(task, "directions")
    assert r1.has_consensus is False
    assert r2.has_consensus is False
    assert r3.has_consensus is True


async def test_expert_council_mediate_short_circuits_under_sentinel() -> None:
    """mediate() returns a fixed string under MockWorld (no subprocess)."""
    from expert_council import CouncilResult, ExpertCouncil
    from mockworld.fakes.fake_llm import FakeLLM

    council = ExpertCouncil.__new__(ExpertCouncil)
    council._mockworld_fake_llm = FakeLLM()
    task = _FakeTask(task_id=14)
    result = await council.mediate(task, CouncilResult([]), "directions")
    assert "Scripted mediation" in result


# ---------------------------------------------------------------------------
# DefaultSpecComplianceReviewer.review
# ---------------------------------------------------------------------------


async def test_spec_reviewer_consumes_scripted_noncompliant() -> None:
    """spec reviewer returns a non-compliant SpecReviewResult with gaps."""
    from implement_spec_reviewer import (
        DefaultSpecComplianceReviewer,
        SpecReviewInput,
    )
    from mockworld.fakes.fake_llm import FakeLLM

    class _StubRunner:
        async def run(self, *, model: str, subagent_type: str, prompt: str) -> str:  # noqa: ARG002
            raise AssertionError("scripted path should not dispatch the runner")

    reviewer = DefaultSpecComplianceReviewer(_StubRunner())
    fake = FakeLLM()
    fake.script_implement_spec_review(
        15, compliant=False, gaps=["missing acceptance test"], reasoning="r"
    )
    reviewer._mockworld_fake_llm = fake  # type: ignore[attr-defined]

    inp = SpecReviewInput(
        issue_number=15,
        issue_title="t",
        issue_body="b",
        plan="p",
        diff="",
        commits=0,
        error="",
    )
    result = await reviewer.review(inp)
    assert result.compliant is False
    assert result.gaps == ["missing acceptance test"]
    assert result.reasoning == "r"


async def test_spec_reviewer_consumes_scripted_compliant() -> None:
    """spec reviewer returns a compliant SpecReviewResult when scripted."""
    from implement_spec_reviewer import (
        DefaultSpecComplianceReviewer,
        SpecReviewInput,
    )
    from mockworld.fakes.fake_llm import FakeLLM

    class _StubRunner:
        async def run(self, *, model: str, subagent_type: str, prompt: str) -> str:  # noqa: ARG002
            raise AssertionError("scripted path should not dispatch the runner")

    reviewer = DefaultSpecComplianceReviewer(_StubRunner())
    fake = FakeLLM()
    fake.script_implement_spec_review(16, compliant=True)
    reviewer._mockworld_fake_llm = fake  # type: ignore[attr-defined]

    inp = SpecReviewInput(
        issue_number=16,
        issue_title="t",
        issue_body="b",
        plan="p",
        diff="--- diff ---",
        commits=1,
        error="",
    )
    result = await reviewer.review(inp)
    assert result.compliant is True
    assert result.gaps == []
