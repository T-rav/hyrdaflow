"""Stage precondition predicates for the pipeline state machine (#6423).

Each stage in HydraFlow's pipeline (READY, REVIEW, ...) has a contract:
the upstream phase must have left structured records in the issue cache
before the consumer phase will pick the issue up. Today the contract is
implicit and label-only; this module makes it explicit and machine-
checkable.

Predicates are pure functions of the issue cache. They never mutate
state and never call out to GitHub. They return ``PreconditionResult``
which is a small dataclass carrying the verdict and a human-readable
reason — ready for logging, route-back records, and HITL escalation
messages.

The actual gating is wired into ``IssueStore.get_*`` methods in a
follow-up; this module lands the predicates and a route-back primitive
so the rest of the stack (#6421 plan review, #6424 bug repro) can use
them as soon as the cache lands (#6422).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from issue_cache import IssueCache

__all__ = [
    "PreconditionPredicate",
    "PreconditionResult",
    "Stage",
    "STAGE_PRECONDITIONS",
    "check_preconditions",
    "has_clean_review",
    "has_plan",
    "has_reproduction_for_bug",
]


class Stage(StrEnum):
    """Pipeline stages with checkable preconditions."""

    READY = "ready"
    REVIEW = "review"


@dataclass(frozen=True)
class PreconditionResult:
    """Outcome of a precondition check.

    A failing result carries the reason so the route-back primitive can
    record it as the route-back ``reason`` field, and so HITL escalations
    after N route-backs have a clear cause message.
    """

    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


PreconditionPredicate = Callable[["IssueCache", int], PreconditionResult]


# ---------------------------------------------------------------------------
# Predicate primitives
# ---------------------------------------------------------------------------


def has_plan(cache: IssueCache, issue_id: int) -> PreconditionResult:
    """The issue must have at least one ``plan_stored`` record."""
    record = cache.latest_plan(issue_id)
    if record is None:
        return PreconditionResult(
            ok=False,
            reason=(
                f"issue #{issue_id}: no plan_stored record in cache — "
                "planner did not produce a structured plan"
            ),
        )
    return PreconditionResult(ok=True)


def has_clean_review(cache: IssueCache, issue_id: int) -> PreconditionResult:
    """The issue must have a ``review_stored`` record without critical findings.

    A clean review is the gate for the READY → IMPLEMENT transition. If
    the review record exists but flags critical findings, the issue is
    routed back to PLAN with the findings as feedback context.
    """
    record = cache.latest_review(issue_id)
    if record is None:
        return PreconditionResult(
            ok=False,
            reason=(
                f"issue #{issue_id}: no review_stored record in cache — "
                "adversarial plan review has not run yet"
            ),
        )
    # Read has_blocking from the payload — set by IssueCache
    # record_review_stored from PlanReview.has_blocking_findings.
    # Coerce to bool defensively in case a malformed cache record
    # stored a non-bool value (e.g. a string from a hand-edited file).
    has_blocking = bool(record.payload.get("has_blocking", False))
    if has_blocking:
        return PreconditionResult(
            ok=False,
            reason=(
                f"issue #{issue_id}: review v{record.version} has critical "
                "findings — route back to PLAN with feedback"
            ),
        )
    return PreconditionResult(ok=True)


def has_reproduction_for_bug(cache: IssueCache, issue_id: int) -> PreconditionResult:
    """If the issue is classified as a bug routed to plan, it must have a
    reproduction record.

    Non-bug issues pass this check unconditionally — reproduction is
    only required for bug-labeled work (#6424). Bugs without a successful
    reproduction get routed back to TRIAGE with the investigation as
    feedback so a human can either fix the issue body or escalate.

    Only classifications with ``routing_outcome == "plan"`` are
    considered — a bug issue that was parked, routed to discover,
    or closed as Sentry noise does NOT satisfy this gate. Without the
    routing check, a park-then-relabel cycle could let a never-planned
    classification satisfy the plan-stage precondition incorrectly.
    """
    classification = cache.latest_classification(issue_id)
    if classification is None:
        # No classification record yet — let the upstream classifier
        # do its job before checking this precondition.
        return PreconditionResult(ok=True)
    routing_outcome = str(classification.payload.get("routing_outcome", ""))
    if routing_outcome != "plan":
        # Classification exists but the issue wasn't routed to plan.
        # Defer to the upstream classifier on the next triage cycle.
        return PreconditionResult(ok=True)
    issue_type = classification.payload.get("issue_type", "")
    if issue_type != "bug":
        return PreconditionResult(ok=True)

    repro = cache.latest_reproduction(issue_id)
    if repro is None:
        return PreconditionResult(
            ok=False,
            reason=(
                f"issue #{issue_id}: bug-labeled but no reproduction_stored "
                "record — bug reproduction has not run"
            ),
        )
    # Normalize outcome to lowercase string. Pydantic StrEnum serializes
    # ReproductionOutcome.UNABLE as "unable" via model_dump_json, but a
    # hand-edited cache file or a caller passing the wrong case would
    # otherwise silently bypass the check. Defensive lowercase ensures
    # the gate fires regardless of casing.
    outcome = str(repro.payload.get("outcome", "")).lower()
    if outcome == "unable":
        return PreconditionResult(
            ok=False,
            reason=(
                f"issue #{issue_id}: bug reproduction outcome was 'unable' — "
                "needs human investigation, escalate to HITL"
            ),
        )
    return PreconditionResult(ok=True)


# ---------------------------------------------------------------------------
# Stage predicate registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StagePreconditionSet:
    """Frozen list of predicates a stage requires."""

    stage: Stage
    predicates: tuple[PreconditionPredicate, ...] = field(default_factory=tuple)


STAGE_PRECONDITIONS: dict[Stage, StagePreconditionSet] = {
    Stage.READY: StagePreconditionSet(
        stage=Stage.READY,
        predicates=(
            has_plan,
            has_clean_review,
            has_reproduction_for_bug,
        ),
    ),
    Stage.REVIEW: StagePreconditionSet(
        stage=Stage.REVIEW,
        # READY stage produced an implementation; REVIEW stage requires
        # the same plan + clean review the implementer started from.
        # Implementation-stored predicates can be added when #6422
        # writes implement_stored records from implement_phase.
        predicates=(
            has_plan,
            has_clean_review,
        ),
    ),
}


def check_preconditions(
    cache: IssueCache, issue_id: int, stage: Stage
) -> PreconditionResult:
    """Run every predicate for *stage* against *issue_id*.

    Returns the first failing result, or a passing result if every
    predicate passes. This short-circuit semantics keeps the route-back
    reason focused on a single problem rather than concatenating every
    failure into one message.
    """
    preset = STAGE_PRECONDITIONS.get(stage)
    if preset is None:
        return PreconditionResult(ok=True)
    for predicate in preset.predicates:
        result = predicate(cache, issue_id)
        if not result.ok:
            return result
    return PreconditionResult(ok=True)
