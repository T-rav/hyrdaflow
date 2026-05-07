"""Architectural tests asserting TermPrunerLoop is correctly wired."""

from __future__ import annotations

import inspect

from service_registry import ServiceRegistry, build_services


def test_term_pruner_field_present_on_service_registry() -> None:
    fields = {f.name for f in ServiceRegistry.__dataclass_fields__.values()}
    assert "term_pruner_loop" in fields


def test_term_pruner_in_build_services_construction() -> None:
    source = inspect.getsource(build_services)
    assert "TermPrunerLoop(" in source
    for kwarg in ("config=", "deps=", "pr_port=", "repo_root="):
        assert kwarg in source


def test_term_pruner_orchestrator_registers_in_bg_loop_registry() -> None:
    from orchestrator import HydraFlowOrchestrator

    source = inspect.getsource(HydraFlowOrchestrator)
    assert '"term_pruner"' in source or "'term_pruner'" in source
