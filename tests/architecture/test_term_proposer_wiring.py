"""Architectural tests asserting TermProposerLoop is correctly wired."""

from __future__ import annotations

import inspect

from service_registry import ServiceRegistry, build_services


def test_term_proposer_field_present_on_service_registry() -> None:
    fields = {f.name for f in ServiceRegistry.__dataclass_fields__.values()}
    assert "term_proposer_loop" in fields, (
        "TermProposerLoop must be a field on ServiceRegistry "
        "(see ADR-0029 caretaker-loop wiring checklist)"
    )


def test_term_proposer_in_bg_loop_registry() -> None:
    """The orchestrator's bg_loop_registry must contain a 'term_proposer' key."""
    from orchestrator import HydraFlowOrchestrator  # noqa: PLC0415

    source = inspect.getsource(HydraFlowOrchestrator)
    assert '"term_proposer"' in source or "'term_proposer'" in source, (
        "orchestrator must wire the term_proposer loop into the bg_loop_registry"
    )


def test_term_proposer_construction_uses_correct_kwargs() -> None:
    """Construction site must use kwargs matching TermProposerLoop's __init__."""
    source = inspect.getsource(build_services)
    assert "TermProposerLoop(" in source
    # All required kwargs present
    for kwarg in (
        "config=",
        "deps=",
        "llm=",
        "pr_port=",
        "repo_root=",
        "dedup_path=",
    ):
        assert kwarg in source, (
            f"build_services missing TermProposerLoop kwarg: {kwarg}"
        )
