"""Tests for scripts/check_layer_imports.py — static layer import checker."""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_layer_imports.py"
_spec = importlib.util.spec_from_file_location("check_layer_imports", _SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["check_layer_imports"] = _mod
_spec.loader.exec_module(_mod)

from check_layer_imports import (  # noqa: E402
    ALLOWLIST,
    COMPOSITION_ROOT,
    CROSS_CUTTING,
    ImportInfo,
    Violation,
    check_violations,
    extract_imports,
    format_violations,
    module_name_from_path,
    resolve_layer,
    run_check,
)

# ---------------------------------------------------------------------------
# resolve_layer
# ---------------------------------------------------------------------------


class TestResolveLayer:
    def test_explicit_domain(self):
        assert resolve_layer("models") == 1
        assert resolve_layer("config") == 1

    def test_explicit_application(self):
        assert resolve_layer("orchestrator") == 2
        assert resolve_layer("plan_phase") == 2

    def test_explicit_runner(self):
        assert resolve_layer("base_runner") == 3
        assert resolve_layer("agent") == 3
        assert resolve_layer("reviewer") == 3

    def test_explicit_infrastructure(self):
        assert resolve_layer("pr_manager") == 4
        assert resolve_layer("worktree") == 4
        assert resolve_layer("dashboard") == 4

    def test_cross_cutting(self):
        assert resolve_layer("events") == "cross-cutting"
        assert resolve_layer("state") == "cross-cutting"

    def test_composition_root(self):
        assert resolve_layer("service_registry") == "composition-root"

    def test_service_registry_not_in_cross_cutting(self):
        assert "service_registry" not in CROSS_CUTTING

    def test_service_registry_in_composition_root(self):
        assert "service_registry" in COMPOSITION_ROOT

    def test_allowlist_contains_all_composition_root_members(self):
        assert COMPOSITION_ROOT <= ALLOWLIST

    def test_pattern_loop(self):
        assert resolve_layer("memory_sync_loop") == 2
        assert resolve_layer("sentry_loop") == 2

    def test_pattern_runner(self):
        assert resolve_layer("some_new_runner") == 3

    def test_pattern_scaffold(self):
        assert resolve_layer("some_new_scaffold") == 4

    def test_pattern_phase(self):
        assert resolve_layer("some_new_phase") == 2

    def test_unknown_module(self):
        assert resolve_layer("unknown_thing") is None

    def test_dir_layer_map(self):
        assert resolve_layer("dashboard_routes") == 4


# ---------------------------------------------------------------------------
# extract_imports
# ---------------------------------------------------------------------------


class TestExtractImports:
    def test_from_import(self):
        source = "from models import Task\n"
        result = extract_imports(source)
        assert len(result) == 1
        assert result[0].module == "models"
        assert result[0].line == 1
        assert "from models import Task" in result[0].raw

    def test_plain_import(self):
        source = "import config\n"
        result = extract_imports(source)
        assert len(result) == 1
        assert result[0].module == "config"

    def test_dotted_import(self):
        source = "from state._issue import IssueState\n"
        result = extract_imports(source)
        assert len(result) == 1
        assert result[0].module == "state"

    def test_skips_type_checking_block(self):
        source = textwrap.dedent("""\
            from __future__ import annotations
            from typing import TYPE_CHECKING

            from models import Task

            if TYPE_CHECKING:
                from pr_manager import PRManager
        """)
        result = extract_imports(source)
        modules = [r.module for r in result]
        assert "models" in modules
        assert "pr_manager" not in modules

    def test_skips_typing_dot_type_checking(self):
        source = textwrap.dedent("""\
            import typing

            if typing.TYPE_CHECKING:
                from pr_manager import PRManager
        """)
        result = extract_imports(source)
        assert all(r.module != "pr_manager" for r in result)

    def test_syntax_error_returns_empty(self):
        result = extract_imports("def broken(:\n")
        assert result == []

    def test_multiple_imports(self):
        source = textwrap.dedent("""\
            from models import Task
            from config import HydraFlowConfig
            import events
        """)
        result = extract_imports(source)
        assert len(result) == 3

    def test_empty_source(self):
        assert extract_imports("") == []


# ---------------------------------------------------------------------------
# check_violations
# ---------------------------------------------------------------------------


class TestCheckViolations:
    def test_no_violation_same_layer(self):
        imports = [
            ImportInfo(module="plan_phase", line=1, raw="from plan_phase import X")
        ]
        result = check_violations("review_phase.py", 2, imports)
        assert result == []

    def test_no_violation_downward(self):
        imports = [ImportInfo(module="models", line=1, raw="from models import Task")]
        result = check_violations("plan_phase.py", 2, imports)
        assert result == []

    def test_upward_violation(self):
        imports = [
            ImportInfo(
                module="pr_manager", line=10, raw="from pr_manager import PRManager"
            )
        ]
        result = check_violations("plan_phase.py", 2, imports)
        assert len(result) == 1
        assert result[0].kind == "upward"
        assert result[0].source_layer == 2
        assert result[0].target_layer == 4
        assert result[0].line == 10

    def test_cross_cutting_allowed_from_any_layer(self):
        imports = [
            ImportInfo(module="events", line=1, raw="from events import EventBus")
        ]
        result = check_violations("agent.py", 3, imports)
        assert result == []

    def test_cross_cutting_pollution(self):
        imports = [
            ImportInfo(module="orchestrator", line=5, raw="from orchestrator import X")
        ]
        result = check_violations("events.py", "cross-cutting", imports)
        assert len(result) == 1
        assert result[0].kind == "cross-cutting-pollution"

    def test_cross_cutting_importing_domain_ok(self):
        imports = [ImportInfo(module="models", line=1, raw="from models import Task")]
        result = check_violations("events.py", "cross-cutting", imports)
        assert result == []

    def test_unknown_target_skipped(self):
        imports = [ImportInfo(module="unknown_lib", line=1, raw="import unknown_lib")]
        result = check_violations("models.py", 1, imports)
        assert result == []

    def test_l3_importing_l1_ok(self):
        imports = [ImportInfo(module="models", line=1, raw="from models import Task")]
        result = check_violations("agent.py", 3, imports)
        assert result == []

    def test_l4_importing_l3_ok(self):
        imports = [
            ImportInfo(
                module="base_runner", line=1, raw="from base_runner import BaseRunner"
            )
        ]
        result = check_violations("pr_manager.py", 4, imports)
        assert result == []

    def test_l1_importing_l2_violation(self):
        imports = [
            ImportInfo(
                module="orchestrator", line=3, raw="from orchestrator import Orch"
            )
        ]
        result = check_violations("models.py", 1, imports)
        assert len(result) == 1
        assert result[0].kind == "upward"

    def test_allowlist_skips_target(self):
        imports = [
            ImportInfo(module="agent", line=1, raw="from agent import AgentRunner")
        ]
        result = check_violations(
            "implement_phase.py", 2, imports, allowed_targets={"agent"}
        )
        assert result == []

    def test_allowlist_does_not_skip_unlisted(self):
        imports = [
            ImportInfo(
                module="pr_manager", line=1, raw="from pr_manager import PRManager"
            )
        ]
        result = check_violations(
            "implement_phase.py", 2, imports, allowed_targets={"agent"}
        )
        assert len(result) == 1

    def test_cross_cutting_importing_cross_cutting_ok(self):
        imports = [
            ImportInfo(module="events", line=1, raw="from events import EventBus")
        ]
        result = check_violations("state/__init__.py", "cross-cutting", imports)
        assert result == []


# ---------------------------------------------------------------------------
# module_name_from_path
# ---------------------------------------------------------------------------


class TestModuleNameFromPath:
    def test_simple_file(self):
        src = Path("/project/src")
        assert module_name_from_path(src / "models.py", src) == "models"

    def test_init_file(self):
        src = Path("/project/src")
        assert module_name_from_path(src / "state" / "__init__.py", src) == "state"

    def test_subpackage_file(self):
        src = Path("/project/src")
        assert module_name_from_path(src / "state" / "_issue.py", src) == "state"

    def test_dashboard_routes(self):
        src = Path("/project/src")
        assert (
            module_name_from_path(src / "dashboard_routes" / "_routes.py", src)
            == "dashboard_routes"
        )


# ---------------------------------------------------------------------------
# format_violations
# ---------------------------------------------------------------------------


class TestFormatViolations:
    def test_upward_format(self):
        v = Violation(
            file="plan_phase.py",
            line=10,
            import_name="from pr_manager import PRManager",
            source_layer=2,
            target_layer=4,
            kind="upward",
        )
        output = format_violations([v])
        assert "plan_phase.py:10" in output
        assert "L2-Application" in output
        assert "L4-Infrastructure" in output
        assert "imports upward" in output

    def test_cross_cutting_format(self):
        v = Violation(
            file="events.py",
            line=5,
            import_name="from orchestrator import X",
            source_layer="cross-cutting",
            target_layer=2,
            kind="cross-cutting-pollution",
        )
        output = format_violations([v])
        assert "cross-cutting imports from" in output
        assert "L2-Application" in output

    def test_empty_violations(self):
        assert format_violations([]) == ""


# ---------------------------------------------------------------------------
# run_check (integration with temp directory)
# ---------------------------------------------------------------------------


class TestRunCheck:
    def test_clean_codebase(self, tmp_path: Path):
        """A codebase with only downward imports has no violations."""
        (tmp_path / "models.py").write_text("x = 1\n")
        (tmp_path / "plan_phase.py").write_text("from models import x\n")
        result = run_check(tmp_path)
        assert result == []

    def test_detects_upward_violation(self, tmp_path: Path):
        """L1 importing L2 is caught."""
        (tmp_path / "orchestrator.py").write_text("x = 1\n")
        (tmp_path / "models.py").write_text("from orchestrator import x\n")
        result = run_check(tmp_path)
        assert len(result) == 1
        assert result[0].kind == "upward"

    def test_service_registry_exempt(self, tmp_path: Path):
        """service_registry.py is allowlisted and never checked."""
        (tmp_path / "service_registry.py").write_text(
            "from orchestrator import x\nfrom agent import y\nfrom pr_manager import z\n"
        )
        result = run_check(tmp_path)
        assert result == []

    def test_type_checking_not_flagged(self, tmp_path: Path):
        """Imports inside TYPE_CHECKING blocks are skipped."""
        source = textwrap.dedent("""\
            from __future__ import annotations
            from typing import TYPE_CHECKING
            from models import Task
            if TYPE_CHECKING:
                from pr_manager import PRManager
        """)
        (tmp_path / "plan_phase.py").write_text(source)
        (tmp_path / "models.py").write_text("Task = int\n")
        (tmp_path / "pr_manager.py").write_text("PRManager = int\n")
        result = run_check(tmp_path)
        assert result == []

    def test_cross_cutting_pollution_detected(self, tmp_path: Path):
        """Cross-cutting module importing from L2 is caught."""
        (tmp_path / "events.py").write_text("from orchestrator import x\n")
        (tmp_path / "orchestrator.py").write_text("x = 1\n")
        result = run_check(tmp_path)
        assert len(result) == 1
        assert result[0].kind == "cross-cutting-pollution"

    def test_unclassified_modules_skipped(self, tmp_path: Path):
        """Modules with no known layer are silently skipped."""
        (tmp_path / "utils.py").write_text("from pr_manager import x\n")
        (tmp_path / "pr_manager.py").write_text("x = 1\n")
        result = run_check(tmp_path)
        assert result == []

    def test_file_allowlist_applied(self, tmp_path: Path):
        """FILE_ALLOWLIST entries suppress known violations."""
        (tmp_path / "implement_phase.py").write_text("from agent import AgentRunner\n")
        (tmp_path / "agent.py").write_text("AgentRunner = int\n")
        result = run_check(tmp_path)
        assert result == []

    def test_excludes_ui_directory(self, tmp_path: Path):
        """Files under ui/ are excluded from scanning."""
        ui = tmp_path / "ui"
        ui.mkdir()
        (ui / "bad.py").write_text("from pr_manager import x\n")
        (tmp_path / "models.py").write_text("x = 1\n")
        result = run_check(tmp_path)
        assert result == []

    def test_excludes_venv_directory(self, tmp_path: Path):
        """Files under .venv/ or venv/ are excluded from scanning."""
        for venv_dir in (".venv", "venv"):
            venv = tmp_path / venv_dir
            venv.mkdir()
            # A classified module name inside venv must not be scanned
            (venv / "models.py").write_text("from orchestrator import x\n")
        (tmp_path / "orchestrator.py").write_text("x = 1\n")
        result = run_check(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# main() smoke test
# ---------------------------------------------------------------------------


class TestMain:
    def test_returns_zero_on_clean(self, tmp_path: Path):
        from check_layer_imports import main

        (tmp_path / "models.py").write_text("x = 1\n")
        assert main(tmp_path) == 0

    def test_returns_one_on_violations(self, tmp_path: Path):
        from check_layer_imports import main

        (tmp_path / "orchestrator.py").write_text("x = 1\n")
        (tmp_path / "models.py").write_text("from orchestrator import x\n")
        assert main(tmp_path) == 1

    def test_returns_one_on_missing_dir(self, tmp_path: Path):
        from check_layer_imports import main

        assert main(tmp_path / "nonexistent") == 1


# ---------------------------------------------------------------------------
# Passes on real codebase
# ---------------------------------------------------------------------------


class TestRealCodebase:
    """Ensure the checker passes on the actual HydraFlow src/ directory."""

    def test_no_violations_on_current_codebase(self):
        src_dir = Path(__file__).resolve().parent.parent / "src"
        if not src_dir.is_dir():
            pytest.skip("src/ directory not found")
        violations = run_check(src_dir)
        assert violations == [], (
            "Layer violations in current codebase:\n" + format_violations(violations)
        )
