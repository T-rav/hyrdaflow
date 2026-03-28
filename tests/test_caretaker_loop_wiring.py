"""Integration tests: caretaker loop wiring into ServiceRegistry and orchestrator."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ci_monitor_loop import CIMonitorLoop
from code_grooming_loop import CodeGroomingLoop
from security_patch_loop import SecurityPatchLoop
from service_registry import ServiceRegistry
from stale_issue_gc_loop import StaleIssueGCLoop

if TYPE_CHECKING:
    from config import HydraFlowConfig


# ---------------------------------------------------------------------------
# Task 1a: ServiceRegistry has the four caretaker loop fields with correct types
# ---------------------------------------------------------------------------


class TestServiceRegistryFields:
    """ServiceRegistry dataclass declares a field for each caretaker loop."""

    _CARETAKER_FIELDS = [
        ("stale_issue_gc_loop", StaleIssueGCLoop),
        ("ci_monitor_loop", CIMonitorLoop),
        ("security_patch_loop", SecurityPatchLoop),
        ("code_grooming_loop", CodeGroomingLoop),
    ]

    @pytest.mark.parametrize(
        "field_name,expected_type",
        _CARETAKER_FIELDS,
        ids=[name for name, _ in _CARETAKER_FIELDS],
    )
    def test_field_exists_with_correct_type_annotation(
        self, field_name: str, expected_type: type
    ) -> None:
        """ServiceRegistry has a dataclass field whose annotation matches the loop class."""
        fields_by_name = {f.name: f for f in dataclasses.fields(ServiceRegistry)}
        assert field_name in fields_by_name, (
            f"ServiceRegistry is missing field {field_name!r}"
        )
        # The annotation is stored as a string (from __future__ annotations) or type.
        annotation = fields_by_name[field_name].type
        # Resolve string annotations against the module globals.
        if isinstance(annotation, str):
            import service_registry as sr_mod

            resolved = eval(annotation, vars(sr_mod))  # noqa: S307
        else:
            resolved = annotation
        assert resolved is expected_type


# ---------------------------------------------------------------------------
# Task 1b: Each loop is instantiated with the correct class by build_services
# ---------------------------------------------------------------------------


class TestServiceRegistryInstantiation:
    """build_services creates loop instances of the correct type."""

    _CARETAKER_FIELDS = [
        ("stale_issue_gc_loop", StaleIssueGCLoop),
        ("ci_monitor_loop", CIMonitorLoop),
        ("security_patch_loop", SecurityPatchLoop),
        ("code_grooming_loop", CodeGroomingLoop),
    ]

    @pytest.mark.parametrize(
        "field_name,expected_type",
        _CARETAKER_FIELDS,
        ids=[name for name, _ in _CARETAKER_FIELDS],
    )
    def test_svc_field_is_correct_type(
        self,
        config: HydraFlowConfig,
        field_name: str,
        expected_type: type,
    ) -> None:
        """HydraFlowOrchestrator._svc.<field> is an instance of the correct class."""
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        svc_obj = getattr(orch._svc, field_name)
        assert isinstance(svc_obj, expected_type)


# ---------------------------------------------------------------------------
# Task 1c: bg_loop_registry in the orchestrator contains the correct keys
# ---------------------------------------------------------------------------


class TestBGLoopRegistryKeys:
    """The orchestrator's bg_loop_registry dict has entries for all four caretaker loops."""

    _EXPECTED_KEYS = [
        ("stale_issue_gc", "stale_issue_gc_loop"),
        ("ci_monitor", "ci_monitor_loop"),
        ("security_patch", "security_patch_loop"),
        ("code_grooming", "code_grooming_loop"),
    ]

    @pytest.mark.parametrize(
        "registry_key,svc_field",
        _EXPECTED_KEYS,
        ids=[k for k, _ in _EXPECTED_KEYS],
    )
    def test_registry_contains_key_mapped_to_svc_field(
        self,
        config: HydraFlowConfig,
        registry_key: str,
        svc_field: str,
    ) -> None:
        """bg_loop_registry[key] is the same object as svc.<field>."""
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        registry = orch._bg_workers._bg_loop_registry
        assert registry_key in registry, (
            f"bg_loop_registry missing key {registry_key!r}"
        )
        expected_obj = getattr(orch._svc, svc_field)
        assert registry[registry_key] is expected_obj


# ---------------------------------------------------------------------------
# Task 1d: _get_default_interval returns the config value
# ---------------------------------------------------------------------------


class TestDefaultIntervals:
    """Each caretaker loop's _get_default_interval returns its config value."""

    _INTERVAL_MAP = [
        ("stale_issue_gc_loop", "stale_issue_gc_interval"),
        ("ci_monitor_loop", "ci_monitor_interval"),
        ("security_patch_loop", "security_patch_interval"),
        ("code_grooming_loop", "code_grooming_interval"),
    ]

    @pytest.mark.parametrize(
        "svc_field,config_attr",
        _INTERVAL_MAP,
        ids=[f for f, _ in _INTERVAL_MAP],
    )
    def test_default_interval_matches_config(
        self,
        config: HydraFlowConfig,
        svc_field: str,
        config_attr: str,
    ) -> None:
        """loop._get_default_interval() == config.<interval_attr>."""
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        loop_obj = getattr(orch._svc, svc_field)
        expected = getattr(config, config_attr)
        assert loop_obj._get_default_interval() == expected
