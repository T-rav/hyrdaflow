"""PreflightPlaybook + registry tests (ADR-0063 W1).

Each phase-failure sub-label routes to a specialist-aware playbook bundle.
The registry maps sub-label -> Playbook; unknown sub-labels fall back to a
generic lead-engineer playbook (the pre-W1 behavior).
"""

from __future__ import annotations

import pytest

from preflight.playbooks import (
    DEFAULT_PERSONA,
    PreflightPlaybook,
    get_playbook,
    iter_playbooks,
)


def test_default_playbook_returned_for_unknown_sublabel() -> None:
    pb = get_playbook("totally-made-up")
    assert isinstance(pb, PreflightPlaybook)
    assert pb.name == "_default"
    # `None` template -> runner falls back to `<sub_label>.md` then
    # `_default.md`, preserving pre-W1 lookup behavior.
    assert pb.prompt_template is None
    # Default persona is the generic lead-engineer text from config (pre-W1
    # behavior). Tests assert the marker substring so a copy edit on the full
    # text doesn't churn tests.
    assert "lead engineer" in pb.persona


def test_plan_stuck_playbook_specialises() -> None:
    pb = get_playbook("plan-stuck")
    assert pb.name == "plan-stuck"
    # Persona-specific: PlanReviewer failures need writing-plans discipline.
    assert pb.persona != DEFAULT_PERSONA
    assert "plan" in pb.persona.lower()
    # ADR-0063 W1 calls this out as the touchpoint-expander prompt anchor.
    assert "touchpoint" in pb.persona.lower() or "adr" in pb.persona.lower()


def test_implement_stuck_playbook_specialises() -> None:
    pb = get_playbook("implement-stuck")
    assert pb.name == "implement-stuck"
    assert pb.persona != DEFAULT_PERSONA
    assert "implement" in pb.persona.lower() or "code" in pb.persona.lower()


def test_review_stuck_playbook_specialises() -> None:
    pb = get_playbook("review-stuck")
    assert pb.name == "review-stuck"
    assert pb.persona != DEFAULT_PERSONA
    # Review failures want test-transcript + recent-diff context per ADR-0063.
    assert "review" in pb.persona.lower() or "test" in pb.persona.lower()


def test_triage_stuck_playbook_specialises() -> None:
    pb = get_playbook("triage-stuck")
    assert pb.name == "triage-stuck"
    assert pb.persona != DEFAULT_PERSONA
    assert "triage" in pb.persona.lower() or "classif" in pb.persona.lower()


def test_discover_stuck_playbook_specialises() -> None:
    """`discover-stuck` is the only phase-stuck label currently in production.

    The playbook exists so when the discover-runner escalates a coherence-
    evaluator failure, preflight already routes to a discover-shaped retry.
    """
    pb = get_playbook("discover-stuck")
    assert pb.name == "discover-stuck"
    assert pb.persona != DEFAULT_PERSONA
    assert "discover" in pb.persona.lower() or "research" in pb.persona.lower()


def test_existing_sublabel_falls_back_to_default_when_unspecialised() -> None:
    """Backwards-compat: sub-labels with no specialist entry still resolve.

    `flaky-test-stuck` already ships with a prompt file but no phase-specialist
    persona; the registry should return the default playbook (so the existing
    prompt file is used by the runner, and the generic persona applies).
    """
    pb = get_playbook("flaky-test-stuck")
    assert pb.name == "_default"
    assert pb.prompt_template is None


def test_iter_playbooks_returns_all_specialists_in_registry() -> None:
    """`iter_playbooks()` exposes the W1 specialist set for diagnostics."""
    names = {pb.name for pb in iter_playbooks()}
    # Per ADR-0063 W1: specialists for the four most common phase failures plus
    # discover (the only label currently in prod). _default is excluded — it's
    # the fallback, not a specialist.
    assert {
        "plan-stuck",
        "implement-stuck",
        "review-stuck",
        "triage-stuck",
        "discover-stuck",
    }.issubset(names)
    assert "_default" not in names


def test_playbook_prompt_template_resolves_when_file_exists() -> None:
    """A playbook's `prompt_template` is the filename stem under prompts/auto_agent/.

    For every specialist that ships a custom prompt file, the file must exist
    so the runner doesn't silently fall back to _default at render time.
    """
    from pathlib import Path

    prompt_dir = Path(__file__).parent.parent / "prompts" / "auto_agent"
    for pb in iter_playbooks():
        if pb.prompt_template in (None, "_default"):
            continue
        prompt_path = prompt_dir / f"{pb.prompt_template}.md"
        assert prompt_path.exists(), (
            f"playbook {pb.name} references prompt_template "
            f"{pb.prompt_template!r} but {prompt_path} is missing"
        )


def test_playbook_is_immutable_dataclass() -> None:
    """Frozen so callers can't mutate the registry entries by accident."""
    pb = get_playbook("plan-stuck")
    with pytest.raises((AttributeError, TypeError)):
        pb.persona = "mutated"  # type: ignore[misc]
