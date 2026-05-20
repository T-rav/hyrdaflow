"""Unit tests for FakeLLM phase-level scripting hooks (ADR-0063 W3a/W3b/W4/W5).

The four ``script_*`` hooks added in ``FakeLLM`` let sandbox scenarios drive
the ADR-0063 recovery-path branches:

- ``script_discover`` — DiscoverRunner coherence verdict + expander queries
- ``script_plan_review`` — PlanReviewer verdict + gaps
- ``script_shape_council`` — ExpertCouncil per-round consensus/split
- ``script_implement_spec_review`` — SpecComplianceReviewer compliant + gaps

Each is consumed FIFO via a dedicated ``pop_*`` (or ``*_for_round``) method
that production runners consult under the ``_mockworld_fake_llm`` sentinel.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_script_discover_pops_in_fifo_order() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_discover(1, coherent=False, queries_required=["q1", "q2"])
    llm.script_discover(1, coherent=True, summary="ok")

    first = llm.pop_discover_script(1)
    assert first is not None
    assert first.coherent is False
    assert first.queries_required == ["q1", "q2"]

    second = llm.pop_discover_script(1)
    assert second is not None
    assert second.coherent is True
    assert second.summary == "ok"


def test_script_discover_returns_none_when_exhausted() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_discover(1, coherent=False)
    assert llm.pop_discover_script(1) is not None
    # Queue exhausted — None signals fall-through to production behavior.
    assert llm.pop_discover_script(1) is None


def test_script_discover_returns_none_when_unset() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    assert llm.pop_discover_script(42) is None


def test_script_plan_review_pops_in_fifo_order() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_plan_review(1, verdict="reject", gaps=["missing tests"])
    llm.script_plan_review(1, verdict="accept")

    first = llm.pop_plan_review_script(1)
    assert first is not None
    assert first.verdict == "reject"
    assert first.gaps == ["missing tests"]

    second = llm.pop_plan_review_script(1)
    assert second is not None
    assert second.verdict == "accept"
    assert second.gaps == []


def test_script_plan_review_returns_none_when_exhausted() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_plan_review(1, verdict="accept")
    assert llm.pop_plan_review_script(1) is not None
    assert llm.pop_plan_review_script(1) is None


def test_script_shape_council_is_idempotent_per_round() -> None:
    """The council verdict map is queried multiple times per round.

    A scenario that scripts ``{1: "split", 2: "consensus"}`` may need to
    answer "what's the verdict for round 1?" more than once if the phase
    code re-runs a predicate. The map is read-only — production code
    advances rounds explicitly via :meth:`ExpertCouncil.vote` /
    ``vote_diversified``.
    """
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_shape_council(3, {1: "split", 2: "split", 3: "consensus"})

    # Idempotent reads.
    assert llm.shape_council_verdict_for_round(3, 1) == "split"
    assert llm.shape_council_verdict_for_round(3, 1) == "split"
    assert llm.shape_council_verdict_for_round(3, 2) == "split"
    assert llm.shape_council_verdict_for_round(3, 3) == "consensus"


def test_script_shape_council_returns_none_for_unknown_round() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_shape_council(1, {1: "consensus"})
    # Round 2 not scripted — None signals fall-through.
    assert llm.shape_council_verdict_for_round(1, 2) is None


def test_script_shape_council_returns_none_for_unknown_issue() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    assert llm.shape_council_verdict_for_round(999, 1) is None


def test_script_implement_spec_review_pops_in_fifo_order() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_implement_spec_review(
        1, compliant=False, gaps=["missing X"], reasoning="X is load-bearing"
    )
    llm.script_implement_spec_review(1, compliant=True)

    first = llm.pop_implement_spec_review_script(1)
    assert first is not None
    assert first.compliant is False
    assert first.gaps == ["missing X"]
    assert first.reasoning == "X is load-bearing"

    second = llm.pop_implement_spec_review_script(1)
    assert second is not None
    assert second.compliant is True
    assert second.gaps == []


def test_script_implement_spec_review_returns_none_when_exhausted() -> None:
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    llm.script_implement_spec_review(1, compliant=True)
    assert llm.pop_implement_spec_review_script(1) is not None
    assert llm.pop_implement_spec_review_script(1) is None


def test_phase_scripts_do_not_break_legacy_script_methods() -> None:
    """Adding the new hooks must not break the four legacy script methods.

    Conformance with the existing FakeLLM port surface: every test in
    ``tests/scenarios/fakes/test_fake_llm.py`` exercises a legacy method
    and would fail if the new dataclasses leaked into the legacy queues.
    """
    from mockworld.fakes.fake_llm import FakeLLM
    from tests.conftest import PlanResultFactory, TaskFactory

    llm = FakeLLM()
    llm.script_discover(1, coherent=False)
    llm.script_plan(1, [PlanResultFactory.create(issue_number=1, success=True)])

    # Legacy ``planners.plan`` still returns the scripted PlanResult — the
    # new phase-level state lives in a separate dict.
    task = TaskFactory.create(id=1)
    import asyncio

    result = asyncio.run(llm.planners.plan(task))
    assert result.success is True


def test_fake_llm_is_fake_adapter_marker_preserved() -> None:
    """Sentinel-check sites read ``_is_fake_adapter`` to disambiguate from mocks."""
    from mockworld.fakes.fake_llm import FakeLLM

    llm = FakeLLM()
    assert llm._is_fake_adapter is True
