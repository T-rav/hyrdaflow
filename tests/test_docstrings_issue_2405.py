"""Tests for docstring additions required by issue #2405.

Verifies that all targeted functions have non-empty docstrings.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"


def _get_function_docstrings(filepath: Path) -> dict[str, str | None]:
    """Parse a Python file and return {function_name: docstring} for all defs."""
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    result: dict[str, str | None] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[node.name] = ast.get_docstring(node)
    return result


class TestDashboardRoutesDocstrings:
    """Verify docstrings on dashboard_routes.py helper and route functions."""

    @pytest.fixture(autouse=True)
    def _load_docstrings(self) -> None:
        self.docstrings = _get_function_docstrings(SRC / "dashboard_routes.py")

    @pytest.mark.parametrize(
        "func_name",
        [
            "_parse_iso_or_none",
            "_event_issue_number",
            "_normalise_event_status",
            "_status_rank",
            "_coerce_int",
            "_is_timestamp_in_range",
            "_status_sort_key",
            "_list_repo_records",
            "_new_issue_history_entry",
            "_touch_issue_timestamps",
            "_build_hitl_context",
            "_normalise_summary_lines",
            "_hitl_summary_retry_due",
        ],
    )
    def test_helper_has_docstring(self, func_name: str) -> None:
        assert func_name in self.docstrings, f"{func_name} not found in file"
        assert self.docstrings[func_name], f"{func_name} has no docstring"

    @pytest.mark.parametrize(
        "func_name",
        [
            "index",
            "get_state",
            "get_stats",
            "get_events",
            "get_human_input_requests",
            "provide_human_input",
            "start_orchestrator",
            "stop_orchestrator",
            "get_control_status",
            "get_timeline",
            "get_timeline_issue",
            "list_supervised_repos",
            "ensure_repo",
            "remove_repo",
            "websocket_endpoint",
            "spa_catchall",
            "_call_supervisor",
        ],
    )
    def test_route_handler_has_docstring(self, func_name: str) -> None:
        assert func_name in self.docstrings, f"{func_name} not found in file"
        assert self.docstrings[func_name], f"{func_name} has no docstring"


class TestReviewPhaseDocstrings:
    """Verify docstring on the _review_one inner function in review_phase.py."""

    def test_review_one_has_docstring(self) -> None:
        docstrings = _get_function_docstrings(SRC / "review_phase.py")
        assert "_review_one" in docstrings
        assert docstrings["_review_one"], "_review_one has no docstring"


class TestPhaseUtilsStoreLifecycleDocstring:
    """Verify store_lifecycle has Args section in its docstring."""

    def test_store_lifecycle_has_args(self) -> None:
        docstrings = _get_function_docstrings(SRC / "phase_utils.py")
        assert "store_lifecycle" in docstrings
        doc = docstrings["store_lifecycle"]
        assert doc is not None
        assert "Args:" in doc
        assert "store:" in doc
        assert "issue_number:" in doc
        assert "stage:" in doc
