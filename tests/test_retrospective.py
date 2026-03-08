"""Tests for retrospective.py - RetrospectiveCollector class."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from models import ReviewVerdict
from retrospective import RetrospectiveCollector, RetrospectiveEntry
from tests.conftest import ReviewResultFactory
from tests.helpers import InMemoryState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collector(
    config: HydraFlowConfig,
    *,
    diff_names: list[str] | None = None,
    create_issue_return: int = 0,
) -> tuple[RetrospectiveCollector, AsyncMock, InMemoryState]:
    """Build a RetrospectiveCollector with an in-memory state."""
    state = InMemoryState()
    mock_prs = AsyncMock()
    mock_prs.get_pr_diff_names = AsyncMock(return_value=diff_names or [])
    mock_prs.create_issue = AsyncMock(return_value=create_issue_return)

    collector = RetrospectiveCollector(config, state, mock_prs)
    return collector, mock_prs, state


def _write_plan(config: HydraFlowConfig, issue_number: int, content: str) -> None:
    """Write a plan file for the given issue."""
    plan_dir = config.repo_root / ".hydraflow" / "plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / f"issue-{issue_number}.md").write_text(content)


def _write_retro_entries(
    state: InMemoryState, entries: list[RetrospectiveEntry]
) -> None:
    """Write retrospective entries to the in-memory state."""
    for entry in entries:
        state.append_retrospective(entry.model_dump())


# ---------------------------------------------------------------------------
# Plan parser tests
# ---------------------------------------------------------------------------


class TestParsePlannedFiles:
    def test_parses_backtick_paths(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        plan = (
            "## Files to Modify\n\n"
            "### 1. `src/foo.py`\n"
            "### 2. `tests/test_foo.py`\n"
            "\n## New Files\n\n"
            "### 1. `src/bar.py` (NEW)\n"
        )
        result = collector._parse_planned_files(plan)
        assert result == ["src/bar.py", "src/foo.py", "tests/test_foo.py"]

    def test_parses_bold_paths(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        plan = (
            "## Files to Modify\n\n"
            "- **src/foo.py** — update logic\n"
            "- **src/bar.py** — add feature\n"
        )
        result = collector._parse_planned_files(plan)
        assert result == ["src/bar.py", "src/foo.py"]

    def test_parses_bare_list_items(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        plan = "## Files to Modify\n\n- src/foo.py\n- src/bar.py\n"
        result = collector._parse_planned_files(plan)
        assert result == ["src/bar.py", "src/foo.py"]

    def test_stops_at_next_heading(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        plan = (
            "## Files to Modify\n\n"
            "- `src/foo.py`\n"
            "\n## Implementation Steps\n\n"
            "- `src/not_a_file.py`\n"
        )
        result = collector._parse_planned_files(plan)
        assert result == ["src/foo.py"]

    def test_returns_empty_for_no_plan(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        result = collector._parse_planned_files("")
        assert result == []

    def test_returns_empty_for_plan_without_file_sections(
        self, config: HydraFlowConfig
    ) -> None:
        collector, _, _ = _make_collector(config)
        plan = "## Summary\n\nThis is a plan.\n\n## Steps\n\n1. Do stuff\n"
        result = collector._parse_planned_files(plan)
        assert result == []

    def test_deduplicates_files(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        plan = (
            "## Files to Modify\n\n- `src/foo.py`\n\n## New Files\n\n- `src/foo.py`\n"
        )
        result = collector._parse_planned_files(plan)
        assert result == ["src/foo.py"]


# ---------------------------------------------------------------------------
# Accuracy computation tests
# ---------------------------------------------------------------------------


class TestComputeAccuracy:
    def test_perfect_match_returns_full_accuracy_with_no_gaps(self) -> None:
        accuracy, unplanned, missed = RetrospectiveCollector._compute_accuracy(
            ["src/foo.py", "src/bar.py"],
            ["src/foo.py", "src/bar.py"],
        )
        assert accuracy == 100.0
        assert unplanned == []
        assert missed == []

    def test_partial_overlap_returns_proportional_accuracy_and_file_lists(self) -> None:
        accuracy, unplanned, missed = RetrospectiveCollector._compute_accuracy(
            ["src/foo.py", "src/bar.py"],
            ["src/foo.py", "src/baz.py"],
        )
        assert accuracy == 50.0
        assert unplanned == ["src/baz.py"]
        assert missed == ["src/bar.py"]

    def test_no_overlap_returns_zero_accuracy(self) -> None:
        accuracy, unplanned, missed = RetrospectiveCollector._compute_accuracy(
            ["src/foo.py"],
            ["src/bar.py"],
        )
        assert accuracy == 0.0
        assert unplanned == ["src/bar.py"]
        assert missed == ["src/foo.py"]

    def test_empty_planned_list_treats_all_actual_as_unplanned(self) -> None:
        accuracy, unplanned, missed = RetrospectiveCollector._compute_accuracy(
            [],
            ["src/bar.py"],
        )
        assert accuracy == 0.0
        assert unplanned == ["src/bar.py"]
        assert missed == []

    def test_empty_actual_list_treats_all_planned_as_missed(self) -> None:
        accuracy, unplanned, missed = RetrospectiveCollector._compute_accuracy(
            ["src/foo.py"],
            [],
        )
        assert accuracy == 0.0
        assert unplanned == []
        assert missed == ["src/foo.py"]

    def test_both_empty_returns_zero_accuracy(self) -> None:
        accuracy, unplanned, missed = RetrospectiveCollector._compute_accuracy([], [])
        assert accuracy == 0.0
        assert unplanned == []
        assert missed == []


# ---------------------------------------------------------------------------
# JSONL storage tests
# ---------------------------------------------------------------------------


class TestDoltStorage:
    def test_append_stores_entry(self, config: HydraFlowConfig) -> None:
        collector, _, state = _make_collector(config)
        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=101,
            timestamp="2026-02-20T10:30:00Z",
        )
        collector._append_entry(entry)

        assert len(state._retrospectives) == 1

    def test_append_writes_valid_data(self, config: HydraFlowConfig) -> None:
        collector, _, state = _make_collector(config)
        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=101,
            timestamp="2026-02-20T10:30:00Z",
            plan_accuracy_pct=85.0,
        )
        collector._append_entry(entry)

        assert len(state._retrospectives) == 1
        data = state._retrospectives[0]
        assert data["issue_number"] == 42
        assert data["plan_accuracy_pct"] == 85.0

    def test_append_multiple_entries(self, config: HydraFlowConfig) -> None:
        collector, _, state = _make_collector(config)
        for i in range(3):
            entry = RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
            )
            collector._append_entry(entry)

        assert len(state._retrospectives) == 3

    def test_load_recent_returns_correct_count(self, config: HydraFlowConfig) -> None:
        collector, _, state = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
            )
            for i in range(5)
        ]
        _write_retro_entries(state, entries)

        result = collector._load_recent(3)
        assert len(result) == 3
        # Newest first from Dolt
        assert result[0].issue_number == 4

    def test_load_recent_with_fewer_entries(self, config: HydraFlowConfig) -> None:
        collector, _, state = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=1,
                pr_number=101,
                timestamp="2026-02-20T10:30:00Z",
            )
        ]
        _write_retro_entries(state, entries)

        result = collector._load_recent(10)
        assert len(result) == 1

    def test_load_recent_with_missing_file(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        result = collector._load_recent(10)
        assert result == []


# ---------------------------------------------------------------------------
# Record integration tests
# ---------------------------------------------------------------------------


class TestRecord:
    @pytest.mark.asyncio
    async def test_full_record_flow(self, config: HydraFlowConfig) -> None:
        """Full record flow: plan exists, diff available, metadata in state."""
        collector, mock_prs, state = _make_collector(
            config, diff_names=["src/foo.py", "tests/test_foo.py", "src/bar.py"]
        )

        _write_plan(
            config,
            42,
            "## Files to Modify\n\n- `src/foo.py`\n- `tests/test_foo.py`\n",
        )
        state.set_worker_result_meta(
            42,
            {
                "quality_fix_attempts": 1,
                "duration_seconds": 120.5,
                "error": None,
            },
        )

        review = ReviewResultFactory.create(
            merged=True, fixes_made=False, ci_fix_attempts=0
        )
        await collector.record(42, 101, review)

        assert len(state._retrospectives) == 1
        data = state._retrospectives[0]
        assert data["issue_number"] == 42
        assert data["pr_number"] == 101
        assert data["planned_files"] == ["src/foo.py", "tests/test_foo.py"]
        assert sorted(data["actual_files"]) == [
            "src/bar.py",
            "src/foo.py",
            "tests/test_foo.py",
        ]
        assert data["unplanned_files"] == ["src/bar.py"]
        assert data["missed_files"] == []
        assert data["plan_accuracy_pct"] == 100.0
        assert data["quality_fix_rounds"] == 1
        assert data["review_verdict"] == "approve"
        assert data["reviewer_fixes_made"] is False

    @pytest.mark.asyncio
    async def test_record_when_plan_missing(self, config: HydraFlowConfig) -> None:
        """When plan file doesn't exist, should still record with empty planned_files."""
        collector, _, state = _make_collector(config, diff_names=["src/foo.py"])

        review = ReviewResultFactory.create(merged=True)
        await collector.record(42, 101, review)

        assert len(state._retrospectives) == 1
        data = state._retrospectives[0]
        assert data["planned_files"] == []
        assert data["plan_accuracy_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_record_when_diff_fails(self, config: HydraFlowConfig) -> None:
        """When gh pr diff fails, should record with empty actual_files."""
        collector, _, state = _make_collector(config, diff_names=[])

        _write_plan(config, 42, "## Files to Modify\n\n- `src/foo.py`\n")
        review = ReviewResultFactory.create(merged=True)
        await collector.record(42, 101, review)

        assert len(state._retrospectives) == 1
        data = state._retrospectives[0]
        assert data["actual_files"] == []
        assert data["missed_files"] == ["src/foo.py"]

    @pytest.mark.asyncio
    async def test_record_when_worker_metadata_missing(
        self, config: HydraFlowConfig
    ) -> None:
        """When worker metadata not in state, should use defaults."""
        collector, _, state = _make_collector(config, diff_names=["src/foo.py"])

        review = ReviewResultFactory.create(merged=True)
        await collector.record(42, 101, review)

        assert len(state._retrospectives) == 1
        data = state._retrospectives[0]
        assert data["quality_fix_rounds"] == 0
        assert data["duration_seconds"] == 0.0

    @pytest.mark.asyncio
    async def test_record_failure_is_non_blocking(
        self, config: HydraFlowConfig
    ) -> None:
        """If retrospective fails, it should not raise."""
        collector, mock_prs, _ = _make_collector(config)
        mock_prs.get_pr_diff_names = AsyncMock(
            side_effect=RuntimeError("network error")
        )

        review = ReviewResultFactory.create(merged=True)
        # Should not raise
        await collector.record(42, 101, review)




# ---------------------------------------------------------------------------
# RetrospectiveEntry model tests
# ---------------------------------------------------------------------------


class TestRetrospectiveEntry:
    def test_entry_initializes_with_zero_accuracy_and_empty_file_lists(self) -> None:
        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=101,
            timestamp="2026-02-20T10:30:00Z",
        )
        assert entry.plan_accuracy_pct == 0.0
        assert entry.planned_files == []
        assert entry.actual_files == []
        assert entry.unplanned_files == []
        assert entry.missed_files == []
        assert entry.quality_fix_rounds == 0
        assert entry.ci_fix_rounds == 0
        assert entry.duration_seconds == 0.0

    def test_json_round_trip(self) -> None:
        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=101,
            timestamp="2026-02-20T10:30:00Z",
            plan_accuracy_pct=85.0,
            planned_files=["src/foo.py"],
            actual_files=["src/foo.py", "src/bar.py"],
            unplanned_files=["src/bar.py"],
            missed_files=[],
            quality_fix_rounds=1,
            review_verdict=ReviewVerdict.APPROVE,
            reviewer_fixes_made=False,
            ci_fix_rounds=0,
            duration_seconds=340.5,
        )
        json_str = entry.model_dump_json()
        restored = RetrospectiveEntry.model_validate_json(json_str)
        assert restored == entry



# ---------------------------------------------------------------------------
# _append_entry OSError handling (issue #1038)
# ---------------------------------------------------------------------------


class TestAppendEntryErrorHandling:
    """Verify RetrospectiveCollector._append_entry catches state errors gracefully."""

    def test_append_entry_logs_warning_on_state_error(
        self, config: HydraFlowConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When the state write fails, log warning and don't raise."""
        import logging
        from unittest.mock import MagicMock

        state = MagicMock()
        state.append_retrospective.side_effect = RuntimeError("db error")
        mock_prs = AsyncMock()
        mock_prs.get_pr_diff_names = AsyncMock(return_value=[])
        mock_prs.create_issue = AsyncMock(return_value=0)
        collector = RetrospectiveCollector(config, state, mock_prs)

        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=100,
            timestamp="2026-02-20T10:30:00Z",
        )

        with caplog.at_level(logging.WARNING, logger="hydraflow.retrospective"):
            collector._append_entry(entry)  # should not raise

        assert "Dolt retrospective write failed" in caplog.text

    def test_append_entry_without_state_method_is_noop(
        self, config: HydraFlowConfig
    ) -> None:
        """When state lacks append_retrospective, append_entry is a no-op."""
        mock_prs = AsyncMock()
        mock_prs.get_pr_diff_names = AsyncMock(return_value=[])
        mock_prs.create_issue = AsyncMock(return_value=0)
        state = object()  # state without append_retrospective
        collector = RetrospectiveCollector(config, state, mock_prs)
        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=100,
            timestamp="2026-02-20T10:30:00Z",
        )
        collector._append_entry(entry)  # should not raise
