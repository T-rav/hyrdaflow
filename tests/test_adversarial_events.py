"""Tests for the 6 EventBus event types added for adversarial-stage observability.

Covers:
* Construction + required-field validation of the 6 payload TypedDicts.
* ``AdversarialRetryLoop`` emits ``AdversarialStageStarted`` at the start
  of each attempt iteration when wired with an ``EventBus``.
* ``AdversarialRetryLoop`` emits ``AdversarialStageConverged`` on
  convergence.
* ``AdversarialRetryLoop`` emits ``AdversarialStageExhausted`` on budget
  exhaustion.
* ``AdversarialRetryLoop`` emits ``ConcernForwarded`` for each unresolved
  concern that gets forwarded.

The event-class shape mirrors the existing repo pattern: a new
``EventType`` enum value plus a ``TypedDict`` payload in ``models.py``.
Emission is via ``HydraFlowEvent`` published on an ``EventBus``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from src.adversarial_retry_loop import AdversarialRetryLoop
from src.pending_concerns import Concern

from events import EventBus, EventType, HydraFlowEvent


@dataclass
class _FakeCtx:
    plan_text: str = "v0"


@dataclass
class _FakeFindings:
    findings: list[Concern] = field(default_factory=list)


def _make_concern(severity: str = "HIGH", concern: str = "X") -> Concern:
    return Concern(
        id=f"T-{concern}",
        raised_in_phase="plan",
        raised_in_stage="test_stage",
        severity=severity,
        concern=concern,
        raised_at=datetime.now(UTC),
        must_address_by="next",
    )


def _events_of_type(bus: EventBus, type_: EventType) -> list[HydraFlowEvent]:
    return [e for e in bus.get_history() if e.type == type_]


# ---------------------------------------------------------------------------
# Part A: payload-class construction tests
# ---------------------------------------------------------------------------


def test_adversarial_stage_started_payload_constructs():
    """Required fields populate the TypedDict + EventType enum value exists."""
    from models import AdversarialStageStartedPayload

    data: AdversarialStageStartedPayload = {
        "issue_id": 42,
        "phase": "plan",
        "stage": "plan_council",
        "retry_count": 0,
    }
    ev = HydraFlowEvent(type=EventType.ADVERSARIAL_STAGE_STARTED, data=data)
    assert ev.data["issue_id"] == 42
    assert ev.data["phase"] == "plan"
    assert ev.data["stage"] == "plan_council"
    assert ev.data["retry_count"] == 0


def test_adversarial_stage_converged_payload_constructs():
    from models import AdversarialStageConvergedPayload

    data: AdversarialStageConvergedPayload = {
        "issue_id": 7,
        "phase": "discover",
        "stage": "discovery_council",
        "retries": 2,
        "concerns_raised": 3,
        "concerns_forwarded": 0,
    }
    ev = HydraFlowEvent(type=EventType.ADVERSARIAL_STAGE_CONVERGED, data=data)
    assert ev.data["retries"] == 2
    assert ev.data["concerns_raised"] == 3
    assert ev.data["concerns_forwarded"] == 0


def test_adversarial_stage_exhausted_payload_constructs():
    from models import AdversarialStageExhaustedPayload

    data: AdversarialStageExhaustedPayload = {
        "issue_id": 9,
        "phase": "shape",
        "stage": "shape_expert_council",
        "retries": 3,
        "concerns_forwarded": 2,
    }
    ev = HydraFlowEvent(type=EventType.ADVERSARIAL_STAGE_EXHAUSTED, data=data)
    assert ev.data["retries"] == 3
    assert ev.data["concerns_forwarded"] == 2


def test_concern_forwarded_payload_constructs():
    from models import ConcernForwardedPayload

    data: ConcernForwardedPayload = {
        "issue_id": 11,
        "concern_id": "C-1",
        "from_stage": "plan_council",
        "to_stage": "implement",
        "severity": "HIGH",
    }
    ev = HydraFlowEvent(type=EventType.CONCERN_FORWARDED, data=data)
    assert ev.data["concern_id"] == "C-1"
    assert ev.data["severity"] == "HIGH"


def test_concern_addressed_payload_constructs():
    from models import ConcernAddressedPayload

    data: ConcernAddressedPayload = {
        "issue_id": 12,
        "concern_id": "C-2",
        "addressed_by_stage": "implement",
        "resolution_kind": "addressed-in-code",
    }
    ev = HydraFlowEvent(type=EventType.CONCERN_ADDRESSED, data=data)
    assert ev.data["concern_id"] == "C-2"
    assert ev.data["resolution_kind"] == "addressed-in-code"


def test_shipped_with_known_gap_payload_constructs():
    from models import ShippedWithKnownGapPayload

    concern = _make_concern(severity="HIGH", concern="known gap")
    data: ShippedWithKnownGapPayload = {
        "issue_id": 13,
        "pr_number": 100,
        "surviving_concerns": [concern.model_dump(mode="json")],
    }
    ev = HydraFlowEvent(type=EventType.SHIPPED_WITH_KNOWN_GAP, data=data)
    assert ev.data["pr_number"] == 100
    assert len(ev.data["surviving_concerns"]) == 1


# ---------------------------------------------------------------------------
# Part B: AdversarialRetryLoop emission tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_loop_emits_stage_started_on_each_attempt():
    bus = EventBus()
    calls = {"critic": 0}

    async def critic(ctx):
        calls["critic"] += 1
        # Distinct concern text per attempt -> oscillation detector
        # does not trip, full budget worth of attempts runs.
        return _FakeFindings(findings=[_make_concern("HIGH", ctx.plan_text)])

    async def retry(findings, ctx):
        return _FakeCtx(plan_text=ctx.plan_text + "+")

    loop = AdversarialRetryLoop(
        budget=2,
        event_bus=bus,
        issue_id=101,
        phase="plan",
        stage="plan_council",
    )
    await loop.run(_FakeCtx(plan_text="v"), critic, retry, is_converged=lambda f: False)

    started = _events_of_type(bus, EventType.ADVERSARIAL_STAGE_STARTED)
    # budget=2 -> 3 attempts (0..budget inclusive)
    assert len(started) == 3
    assert started[0].data == {
        "issue_id": 101,
        "phase": "plan",
        "stage": "plan_council",
        "retry_count": 0,
    }
    assert started[1].data["retry_count"] == 1
    assert started[2].data["retry_count"] == 2


@pytest.mark.asyncio
async def test_retry_loop_emits_converged_when_findings_clear():
    bus = EventBus()
    calls = {"critic": 0}

    async def critic(ctx):
        calls["critic"] += 1
        # First pass raises 1 concern, second pass is clean.
        if calls["critic"] == 1:
            return _FakeFindings(findings=[_make_concern("HIGH", "first")])
        return _FakeFindings(findings=[])

    async def retry(findings, ctx):
        return _FakeCtx(plan_text="fixed")

    loop = AdversarialRetryLoop(
        budget=3,
        event_bus=bus,
        issue_id=55,
        phase="discover",
        stage="discovery_council",
    )
    await loop.run(_FakeCtx(), critic, retry, is_converged=lambda f: not f.findings)

    converged = _events_of_type(bus, EventType.ADVERSARIAL_STAGE_CONVERGED)
    assert len(converged) == 1
    payload = converged[0].data
    assert payload["issue_id"] == 55
    assert payload["phase"] == "discover"
    assert payload["stage"] == "discovery_council"
    assert payload["retries"] == 1  # converged after one retry
    assert payload["concerns_forwarded"] == 0
    # exhausted should NOT be emitted on convergence
    assert _events_of_type(bus, EventType.ADVERSARIAL_STAGE_EXHAUSTED) == []


@pytest.mark.asyncio
async def test_retry_loop_emits_exhausted_on_budget_exhaustion():
    bus = EventBus()

    async def critic(ctx):
        # Yield a new distinct concern each time so oscillation detector
        # does NOT trip — we want true budget exhaustion.
        return _FakeFindings(findings=[_make_concern("HIGH", ctx.plan_text)])

    async def retry(findings, ctx):
        return _FakeCtx(plan_text=ctx.plan_text + "+")

    loop = AdversarialRetryLoop(
        budget=2,
        event_bus=bus,
        issue_id=77,
        phase="shape",
        stage="shape_expert_council",
    )
    final, unresolved = await loop.run(
        _FakeCtx(plan_text="v"),
        critic,
        retry,
        is_converged=lambda f: False,
    )

    exhausted = _events_of_type(bus, EventType.ADVERSARIAL_STAGE_EXHAUSTED)
    assert len(exhausted) == 1
    payload = exhausted[0].data
    assert payload["issue_id"] == 77
    assert payload["phase"] == "shape"
    assert payload["stage"] == "shape_expert_council"
    assert payload["retries"] == 2
    assert payload["concerns_forwarded"] == len(unresolved)
    # converged should NOT be emitted
    assert _events_of_type(bus, EventType.ADVERSARIAL_STAGE_CONVERGED) == []


@pytest.mark.asyncio
async def test_retry_loop_emits_concern_forwarded_for_each_unresolved():
    bus = EventBus()

    concerns = [
        _make_concern("HIGH", "first"),
        _make_concern("CRITICAL", "second"),
    ]

    async def critic(ctx):
        return _FakeFindings(findings=list(concerns))

    async def retry(findings, ctx):
        # Yield a distinct ctx each pass so oscillation detector does
        # not fire — we want a clean budget-exhaustion exit.
        return _FakeCtx(plan_text=ctx.plan_text + "+")

    # NOTE: with identical findings each call, oscillation detector
    # will trip after window=2 instead. Either path (exhausted OR
    # oscillation) should still forward the concerns, so the test is
    # robust to whichever path is taken — we only assert on the
    # ConcernForwarded events.

    loop = AdversarialRetryLoop(
        budget=3,
        oscillation_window=999,  # disable oscillation for this test
        event_bus=bus,
        issue_id=88,
        phase="plan",
        stage="plan_council",
    )
    _final, unresolved = await loop.run(
        _FakeCtx(),
        critic,
        retry,
        is_converged=lambda f: False,
    )

    forwarded = _events_of_type(bus, EventType.CONCERN_FORWARDED)
    assert len(forwarded) == len(unresolved) == len(concerns)
    forwarded_ids = {e.data["concern_id"] for e in forwarded}
    assert forwarded_ids == {c.id for c in concerns}
    for ev in forwarded:
        assert ev.data["issue_id"] == 88
        assert ev.data["from_stage"] == "plan_council"
        assert ev.data["severity"] in {"HIGH", "CRITICAL"}


@pytest.mark.asyncio
async def test_retry_loop_without_event_bus_is_silent_backward_compat():
    """No event_bus -> no crash, no emission, existing behaviour preserved."""

    async def critic(ctx):
        return _FakeFindings(findings=[])

    async def retry(findings, ctx):  # pragma: no cover -- never reached
        return ctx

    loop = AdversarialRetryLoop(budget=2)  # no event_bus
    final, unresolved = await loop.run(
        _FakeCtx(), critic, retry, is_converged=lambda f: True
    )
    assert unresolved == []
    assert final.plan_text == "v0"
