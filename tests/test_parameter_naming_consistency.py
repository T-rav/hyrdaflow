"""Tests verifying consistent parameter naming (issue_number) across modules.

Addresses issue #2393: standardize issue_num/task_id → issue_number.
"""

from __future__ import annotations

import inspect

import pytest

from issue_store import IssueStore
from ports import PRPort
from task_source import TaskTransitioner


class TestIssueStoreParameterNaming:
    """Verify IssueStore public methods use 'issue_number', not 'task_id'."""

    def test_mark_active_uses_issue_number_param(self):
        sig = inspect.signature(IssueStore.mark_active)
        params = list(sig.parameters.keys())
        assert "issue_number" in params
        assert "task_id" not in params

    def test_mark_complete_uses_issue_number_param(self):
        sig = inspect.signature(IssueStore.mark_complete)
        params = list(sig.parameters.keys())
        assert "issue_number" in params
        assert "task_id" not in params

    def test_is_active_uses_issue_number_param(self):
        sig = inspect.signature(IssueStore.is_active)
        params = list(sig.parameters.keys())
        assert "issue_number" in params
        assert "task_id" not in params

    def test_release_in_flight_uses_issue_numbers_param(self):
        sig = inspect.signature(IssueStore.release_in_flight)
        params = list(sig.parameters.keys())
        assert "issue_numbers" in params
        assert "task_ids" not in params


class TestPRPortParameterNaming:
    """Verify PRPort protocol uses 'issue_number', not 'task_id'."""

    def test_post_comment_uses_issue_number_param(self):
        sig = inspect.signature(PRPort.post_comment)
        params = list(sig.parameters.keys())
        assert "issue_number" in params
        assert "task_id" not in params


class TestTaskTransitionerParameterNaming:
    """Verify TaskTransitioner protocol uses 'issue_number', not 'task_id'."""

    def test_transition_uses_issue_number_param(self):
        sig = inspect.signature(TaskTransitioner.transition)
        params = list(sig.parameters.keys())
        assert "issue_number" in params
        assert "task_id" not in params

    def test_post_comment_uses_issue_number_param(self):
        sig = inspect.signature(TaskTransitioner.post_comment)
        params = list(sig.parameters.keys())
        assert "issue_number" in params
        assert "task_id" not in params

    def test_close_task_uses_issue_number_param(self):
        sig = inspect.signature(TaskTransitioner.close_task)
        params = list(sig.parameters.keys())
        assert "issue_number" in params
        assert "task_id" not in params


class TestPRManagerParameterNaming:
    """Verify PRManager concrete implementations use 'issue_number'."""

    def test_post_comment_uses_issue_number_param(self):
        from pr_manager import PRManager

        sig = inspect.signature(PRManager.post_comment)
        params = list(sig.parameters.keys())
        assert "issue_number" in params
        assert "task_id" not in params

    def test_transition_uses_issue_number_param(self):
        from pr_manager import PRManager

        sig = inspect.signature(PRManager.transition)
        params = list(sig.parameters.keys())
        assert "issue_number" in params
        assert "task_id" not in params

    def test_close_task_uses_issue_number_param(self):
        from pr_manager import PRManager

        sig = inspect.signature(PRManager.close_task)
        params = list(sig.parameters.keys())
        assert "issue_number" in params
        assert "task_id" not in params


class TestNoIssueNumVariables:
    """Verify that source files no longer use 'issue_num' as a variable name."""

    @pytest.mark.parametrize(
        "module_name",
        [
            "pr_manager",
            "memory",
            "transcript_summarizer",
            "harness_insights",
            "epic",
            "changelog",
            "epic_sweeper_loop",
            "orchestrator",
            "workspace_gc_loop",
            "timeline",
            "dashboard_routes",
        ],
    )
    def test_no_issue_num_in_source(self, module_name: str):
        """Ensure no module uses the old 'issue_num' variable name."""
        import importlib
        from pathlib import Path

        mod = importlib.import_module(module_name)
        source_path = Path(inspect.getfile(mod))
        source = source_path.read_text()

        # Check that 'issue_num' (word-boundary) doesn't appear
        import re

        matches = re.findall(r"\bissue_num\b", source)
        assert not matches, (
            f"{module_name} still contains 'issue_num' ({len(matches)} occurrences)"
        )
