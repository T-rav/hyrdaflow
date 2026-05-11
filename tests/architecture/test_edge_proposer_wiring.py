"""Architectural tests asserting EdgeProposerLoop is correctly wired."""

from __future__ import annotations

import inspect

from service_registry import ServiceRegistry, build_services


def test_edge_proposer_field_present_on_service_registry() -> None:
    fields = {f.name for f in ServiceRegistry.__dataclass_fields__.values()}
    assert "edge_proposer_loop" in fields


def test_edge_proposer_in_build_services_construction() -> None:
    source = inspect.getsource(build_services)
    assert "EdgeProposerLoop(" in source
    for kwarg in ("config=", "deps=", "pr_port=", "repo_root="):
        assert kwarg in source


def test_edge_proposer_orchestrator_registers_in_bg_loop_registry() -> None:
    from orchestrator import HydraFlowOrchestrator

    source = inspect.getsource(HydraFlowOrchestrator)
    assert '"edge_proposer"' in source or "'edge_proposer'" in source
