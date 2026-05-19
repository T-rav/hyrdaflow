"""Specialist-aware preflight playbooks (ADR-0063 W1).

Each `PreflightPlaybook` bundles a phase-specific persona, a prompt-template
selector, and optional context-gathering hints. The registry maps
sub-labels (e.g. ``plan-stuck``) to playbooks; unknown sub-labels fall back
to ``_default`` so behavior is backwards-compatible with pre-W1 preflight.

Why a per-phase bundle (not a generic lead-engineer prompt):

- ADR-0063 §Context: ``hitl-escalation`` for five phases is a model-competence
  failure, not a raging fire. The current generic preflight retries against
  the same prompt; the matrix shows that doesn't shift the resolution rate.
  Specialist routing changes the *content* of the retry — persona, context,
  prompt anchor — so the next attempt has a chance to do something the first
  couldn't.

- Why frozen dataclasses: the registry is loaded once at import and consulted
  by every preflight tick. Frozen entries make accidental mutation in a hot
  path a TypeError instead of a silent bug.

- Why bundle the prompt template + persona together (not just a persona): the
  prompt file owns the "order of operations" the specialist follows. Pairing
  them keeps the persona claim ("plan-touchpoint specialist") consistent with
  the actions the prompt asks for. Splitting them invites drift.

- Why no behavior coupling to ``PreflightAgent``: the registry returns data,
  not callables. ``PreflightAgent`` reads ``playbook.persona`` and passes
  ``playbook.prompt_template`` to the runner. This keeps the playbook layer
  testable in isolation and lets W2-W5 add specialists without touching
  ``PreflightAgent`` itself.
"""

from __future__ import annotations

from dataclasses import dataclass

# The generic lead-engineer persona used by ``_default`` and any sub-label
# the registry doesn't specialise. Mirrors the pre-W1 ``auto_agent_persona``
# config default so existing deployments see no behavior change for
# unspecialised sub-labels.
DEFAULT_PERSONA = (
    "the lead engineer for this project — pragmatic, prefers small fixes, "
    "leaves regression tests, doesn't over-engineer. When in doubt about "
    "scope, do less."
)


@dataclass(frozen=True)
class PreflightPlaybook:
    """Per-sub-label specialist bundle.

    Attributes:
        name: Sub-label this playbook handles (e.g. ``plan-stuck``).
            ``_default`` is reserved for the fallback.
        persona: Persona string substituted into the shared prompt envelope
            ``{persona}`` slot. Overrides ``config.auto_agent_persona`` for
            this sub-label when not equal to ``DEFAULT_PERSONA``.
        prompt_template: Filename stem under ``prompts/auto_agent/`` (e.g.
            ``plan-stuck`` resolves to ``prompts/auto_agent/plan-stuck.md``).
            Use ``"_default"`` to force the generic playbook prompt; ``None``
            means "use the runner's sub-label-derived lookup" (preserves the
            pre-W1 behavior where sub-label X loads ``X.md`` when present).
    """

    name: str
    persona: str
    prompt_template: str | None


_DEFAULT_PLAYBOOK = PreflightPlaybook(
    name="_default",
    persona=DEFAULT_PERSONA,
    # `None` preserves the pre-W1 lookup: render_prompt falls back from
    # `<sub_label>.md` to `_default.md` based on file existence. This keeps
    # the existing prompt files (flaky-test-stuck.md, wiki-rot-stuck.md, ...)
    # active for sub-labels without a specialist registry entry.
    prompt_template=None,
)


# Specialist personas — each is tied to the per-phase remediation pattern in
# ADR-0063 §Decision. Keep these in sync with the prompt files in
# prompts/auto_agent/<name>.md and with ADR-0063 W1's specialist list.
_PLAN_STUCK = PreflightPlaybook(
    name="plan-stuck",
    persona=(
        "a planning specialist for this project. Plans escalated to you have "
        "already failed PlanReviewer at least once. Your job is to pull the "
        "touchpoint set the original planner missed (cross-referenced ADRs, "
        "recent PR conflicts on touched files, current wiki entries for "
        "affected modules) and re-plan with explicit success criteria "
        "(superpowers:writing-plans discipline). Do not re-run the same plan "
        "shape — the planner already tried that."
    ),
    prompt_template="plan-stuck",
)

_IMPLEMENT_STUCK = PreflightPlaybook(
    name="implement-stuck",
    persona=(
        "an implementation specialist for this project. Implementations "
        "escalated to you have hit the attempt cap or produced a zero-diff "
        "branch. The original spec is in the issue body / escalation context. "
        "Your job is to apply the superpowers:subagent-driven-development "
        "two-stage review (spec compliance, then code quality) and either "
        "produce a diff that satisfies the spec-compliance check or return "
        "needs_human with the specific spec-vs-code gap you found."
    ),
    prompt_template="implement-stuck",
)

_REVIEW_STUCK = PreflightPlaybook(
    name="review-stuck",
    persona=(
        "a review-recovery specialist for this project. Reviews escalated to "
        "you failed the sandbox/CI tier. Your job is to read the test "
        "transcript and the last 3 commits' diffs (not just the failure log) "
        "and either fix the regression or return needs_human with a precise "
        "diagnosis of which commit introduced the failure. Visual-validation "
        "and merge-conflict failures are HITL-by-design — escalate cleanly."
    ),
    prompt_template="review-stuck",
)

_TRIAGE_STUCK = PreflightPlaybook(
    name="triage-stuck",
    persona=(
        "a triage specialist for this project. Issues escalated to you were "
        "parked by the triage runner with a parking_reason (visible in the "
        "escalation context). Your job is to re-classify the issue with the "
        "parking_reason as additional context — most parked issues are "
        "under-specified, not impossible; ask the smallest clarifying "
        "question or assign the smallest reasonable label set and unblock."
    ),
    prompt_template="triage-stuck",
)

_DISCOVER_STUCK = PreflightPlaybook(
    name="discover-stuck",
    persona=(
        "a discovery / research specialist for this project. Discover-phase "
        "escalations land here when the coherence evaluator rejected the "
        "research brief. Your job is to ask 'what would 30% more confidence "
        "require?' — propose at least three additional research queries that "
        "would close the coherence gap, expand the brief, and re-run the "
        "evaluator. If the gap is structural (missing source, dead ADR "
        "reference), return needs_human with the specific blocker."
    ),
    prompt_template="discover-stuck",
)


# Registry. Sub-labels mapped to their specialist. Anything not in this dict
# resolves to ``_DEFAULT_PLAYBOOK`` via ``get_playbook``. Adding a specialist
# is a single-line append plus a matching prompt file.
_REGISTRY: dict[str, PreflightPlaybook] = {
    pb.name: pb
    for pb in (
        _PLAN_STUCK,
        _IMPLEMENT_STUCK,
        _REVIEW_STUCK,
        _TRIAGE_STUCK,
        _DISCOVER_STUCK,
    )
}


def get_playbook(sub_label: str) -> PreflightPlaybook:
    """Return the playbook for ``sub_label`` (falls back to ``_default``).

    Backwards-compatible: any sub-label the registry doesn't specialise gets
    the generic lead-engineer playbook, which renders the existing
    ``prompts/auto_agent/_default.md`` (or a sub-label-specific prompt file
    if one exists, via the runner's existing lookup) with the default persona.
    """
    return _REGISTRY.get(sub_label, _DEFAULT_PLAYBOOK)


def iter_playbooks() -> tuple[PreflightPlaybook, ...]:
    """Return the specialist registry (excluding the ``_default`` fallback).

    Useful for diagnostics, dashboards, and tests that need to verify every
    specialist ships a prompt file.
    """
    return tuple(_REGISTRY.values())


__all__ = [
    "DEFAULT_PERSONA",
    "PreflightPlaybook",
    "get_playbook",
    "iter_playbooks",
]
