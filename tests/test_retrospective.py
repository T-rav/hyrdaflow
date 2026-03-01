"""Tests for retrospective.py - RetrospectiveCollector class."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from models import ReviewVerdict
from retrospective import RetrospectiveCollector, RetrospectiveEntry
from state import StateTracker
from tests.conftest import ReviewResultFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collector(
    config: HydraFlowConfig,
    *,
    diff_names: list[str] | None = None,
    create_issue_return: int = 0,
) -> tuple[RetrospectiveCollector, AsyncMock, StateTracker]:
    """Build a RetrospectiveCollector with mocked PRManager."""
    state = StateTracker(config.state_file)
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
    config: HydraFlowConfig, entries: list[RetrospectiveEntry]
) -> None:
    """Write retrospective entries to the JSONL file."""
    retro_path = config.repo_root / ".hydraflow" / "memory" / "retrospectives.jsonl"
    retro_path.parent.mkdir(parents=True, exist_ok=True)
    with retro_path.open("w") as f:
        for entry in entries:
            f.write(entry.model_dump_json() + "\n")


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


class TestJSONLStorage:
    def test_append_creates_directory_and_file(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=101,
            timestamp="2026-02-20T10:30:00Z",
        )
        collector._append_entry(entry)

        retro_path = config.repo_root / ".hydraflow" / "memory" / "retrospectives.jsonl"
        assert retro_path.exists()

    def test_append_writes_valid_jsonl(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=101,
            timestamp="2026-02-20T10:30:00Z",
            plan_accuracy_pct=85.0,
        )
        collector._append_entry(entry)

        retro_path = config.repo_root / ".hydraflow" / "memory" / "retrospectives.jsonl"
        lines = retro_path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["issue_number"] == 42
        assert data["plan_accuracy_pct"] == 85.0

    def test_append_to_existing_file(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        for i in range(3):
            entry = RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
            )
            collector._append_entry(entry)

        retro_path = config.repo_root / ".hydraflow" / "memory" / "retrospectives.jsonl"
        lines = retro_path.read_text().strip().splitlines()
        assert len(lines) == 3

    def test_load_recent_returns_correct_count(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
            )
            for i in range(5)
        ]
        _write_retro_entries(config, entries)

        result = collector._load_recent(3)
        assert len(result) == 3
        assert result[0].issue_number == 2  # last 3 entries

    def test_load_recent_with_fewer_entries(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=1,
                pr_number=101,
                timestamp="2026-02-20T10:30:00Z",
            )
        ]
        _write_retro_entries(config, entries)

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

        retro_path = config.repo_root / ".hydraflow" / "memory" / "retrospectives.jsonl"
        assert retro_path.exists()
        lines = retro_path.read_text().strip().splitlines()
        assert len(lines) == 1

        data = json.loads(lines[0])
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
        collector, _, _ = _make_collector(config, diff_names=["src/foo.py"])

        review = ReviewResultFactory.create(merged=True)
        await collector.record(42, 101, review)

        retro_path = config.repo_root / ".hydraflow" / "memory" / "retrospectives.jsonl"
        lines = retro_path.read_text().strip().splitlines()
        data = json.loads(lines[0])
        assert data["planned_files"] == []
        assert data["plan_accuracy_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_record_when_diff_fails(self, config: HydraFlowConfig) -> None:
        """When gh pr diff fails, should record with empty actual_files."""
        collector, _, _ = _make_collector(config, diff_names=[])

        _write_plan(config, 42, "## Files to Modify\n\n- `src/foo.py`\n")
        review = ReviewResultFactory.create(merged=True)
        await collector.record(42, 101, review)

        retro_path = config.repo_root / ".hydraflow" / "memory" / "retrospectives.jsonl"
        lines = retro_path.read_text().strip().splitlines()
        data = json.loads(lines[0])
        assert data["actual_files"] == []
        assert data["missed_files"] == ["src/foo.py"]

    @pytest.mark.asyncio
    async def test_record_when_worker_metadata_missing(
        self, config: HydraFlowConfig
    ) -> None:
        """When worker metadata not in state, should use defaults."""
        collector, _, _ = _make_collector(config, diff_names=["src/foo.py"])

        review = ReviewResultFactory.create(merged=True)
        await collector.record(42, 101, review)

        retro_path = config.repo_root / ".hydraflow" / "memory" / "retrospectives.jsonl"
        lines = retro_path.read_text().strip().splitlines()
        data = json.loads(lines[0])
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
# Pattern detection tests
# ---------------------------------------------------------------------------


class TestPatternDetection:
    @pytest.mark.asyncio
    async def test_quality_fix_pattern_detected(self, config: HydraFlowConfig) -> None:
        """When >50% of entries need quality fixes, pattern should be detected."""
        collector, mock_prs, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
                quality_fix_rounds=1 if i < 6 else 0,  # 6/10 = 60%
                plan_accuracy_pct=90,
            )
            for i in range(10)
        ]

        await collector._detect_patterns(entries)

        mock_prs.create_issue.assert_awaited_once()
        title = mock_prs.create_issue.call_args[0][0]
        assert "quality fix" in title.lower()

    @pytest.mark.asyncio
    async def test_quality_fix_pattern_not_detected_when_below_threshold(
        self, config: HydraFlowConfig
    ) -> None:
        """When <=50% of entries need quality fixes, no pattern."""
        collector, mock_prs, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
                quality_fix_rounds=1 if i < 4 else 0,  # 4/10 = 40%
                plan_accuracy_pct=90,
            )
            for i in range(10)
        ]

        await collector._detect_patterns(entries)

        mock_prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_plan_accuracy_pattern_detected(
        self, config: HydraFlowConfig
    ) -> None:
        """When average accuracy drops below 70%, pattern should be detected."""
        collector, mock_prs, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
                plan_accuracy_pct=60,
            )
            for i in range(10)
        ]

        await collector._detect_patterns(entries)

        mock_prs.create_issue.assert_awaited_once()
        title = mock_prs.create_issue.call_args[0][0]
        assert "plan accuracy" in title.lower()

    @pytest.mark.asyncio
    async def test_reviewer_fix_pattern_detected(self, config: HydraFlowConfig) -> None:
        """When >40% of entries have reviewer fixes, pattern should be detected."""
        collector, mock_prs, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
                reviewer_fixes_made=i < 5,  # 5/10 = 50%
                plan_accuracy_pct=90,
            )
            for i in range(10)
        ]

        await collector._detect_patterns(entries)

        mock_prs.create_issue.assert_awaited_once()
        title = mock_prs.create_issue.call_args[0][0]
        assert "reviewer" in title.lower()

    @pytest.mark.asyncio
    async def test_unplanned_file_pattern_detected(
        self, config: HydraFlowConfig
    ) -> None:
        """When same file appears unplanned in >30% of entries."""
        collector, mock_prs, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
                unplanned_files=["src/common.py"] if i < 4 else [],  # 4/10 = 40%
                plan_accuracy_pct=90,
            )
            for i in range(10)
        ]

        await collector._detect_patterns(entries)

        mock_prs.create_issue.assert_awaited_once()
        title = mock_prs.create_issue.call_args[0][0]
        assert "src/common.py" in title

    @pytest.mark.asyncio
    async def test_no_patterns_on_healthy_data(self, config: HydraFlowConfig) -> None:
        """No patterns should be detected on healthy data."""
        collector, mock_prs, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
                plan_accuracy_pct=90,
                quality_fix_rounds=0,
                reviewer_fixes_made=False,
                unplanned_files=[],
            )
            for i in range(10)
        ]

        await collector._detect_patterns(entries)

        mock_prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pattern_detection_skips_with_few_entries(
        self, config: HydraFlowConfig
    ) -> None:
        """Pattern detection should skip when fewer than 3 entries."""
        collector, mock_prs, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=1,
                pr_number=101,
                timestamp="2026-02-20T10:30:00Z",
                quality_fix_rounds=1,
                plan_accuracy_pct=10,
            )
        ]

        await collector._detect_patterns(entries)

        mock_prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_pattern_not_filed(self, config: HydraFlowConfig) -> None:
        """Same pattern should not be filed twice."""
        collector, mock_prs, _ = _make_collector(config)

        # Pre-populate filed patterns
        filed_path = config.repo_root / ".hydraflow" / "memory" / "filed_patterns.json"
        filed_path.parent.mkdir(parents=True, exist_ok=True)
        filed_path.write_text(json.dumps(["quality_fix"]))

        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
                quality_fix_rounds=1,  # 100% need quality fixes
                plan_accuracy_pct=90,
            )
            for i in range(10)
        ]

        await collector._detect_patterns(entries)

        # Should not file again since quality_fix is already in filed patterns
        mock_prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_caps_at_one_proposal_per_run(self, config: HydraFlowConfig) -> None:
        """At most 1 pattern proposal per retrospective run."""
        collector, mock_prs, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
                quality_fix_rounds=1,  # >50% quality fixes
                plan_accuracy_pct=50,  # <70% accuracy
                reviewer_fixes_made=True,  # >40% reviewer fixes
            )
            for i in range(10)
        ]

        await collector._detect_patterns(entries)

        # Only 1 issue filed despite multiple patterns matching
        mock_prs.create_issue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_improvement_issue_has_correct_labels(
        self, config: HydraFlowConfig
    ) -> None:
        """Filed improvement issue should have hydraflow-improve + hydraflow-memory labels."""
        collector, mock_prs, _ = _make_collector(config)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
                quality_fix_rounds=1,
                plan_accuracy_pct=90,
            )
            for i in range(10)
        ]

        await collector._detect_patterns(entries)

        labels = mock_prs.create_issue.call_args[0][2]
        assert "hydraflow-improve" in labels
        assert "hydraflow-memory" in labels


# ---------------------------------------------------------------------------
# Filed patterns persistence
# ---------------------------------------------------------------------------


class TestFiledPatterns:
    def test_load_empty_when_no_file(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        result = collector._load_filed_patterns()
        assert result == set()

    def test_save_and_load_round_trip(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        patterns = {"quality_fix", "plan_accuracy"}
        collector._save_filed_patterns(patterns)
        result = collector._load_filed_patterns()
        assert result == patterns

    def test_load_handles_corrupt_file(self, config: HydraFlowConfig) -> None:
        collector, _, _ = _make_collector(config)
        filed_path = config.repo_root / ".hydraflow" / "memory" / "filed_patterns.json"
        filed_path.parent.mkdir(parents=True, exist_ok=True)
        filed_path.write_text("not valid json")
        result = collector._load_filed_patterns()
        assert result == set()

    def test_save_filed_patterns_handles_oserror(
        self, config: HydraFlowConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        collector, _, _ = _make_collector(config)
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            collector._save_filed_patterns({"quality_fix"})  # should not raise

        assert "Could not save filed patterns" in caplog.text


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
# _file_improvement_issue memory routing
# ---------------------------------------------------------------------------


class TestFileImprovementIssueSetsOrigin:
    """Tests for memory-routed issue creation in _file_improvement_issue."""

    @pytest.mark.asyncio
    async def test_file_improvement_issue_uses_memory_labels_and_prefix(
        self, config: HydraFlowConfig
    ) -> None:
        """Filing an improvement issue should route to improve+memory with [Memory] title."""
        collector, mock_prs, state = _make_collector(config, create_issue_return=99)

        await collector._file_improvement_issue("Pattern: test", "Some body text")

        mock_prs.create_issue.assert_awaited_once()
        args = mock_prs.create_issue.call_args[0]
        assert args[0].startswith("[Memory] ")
        assert args[2] == [config.improve_label[0], config.memory_label[0]]
        assert state.get_hitl_origin(99) is None
        assert state.get_hitl_cause(99) is None

    @pytest.mark.asyncio
    async def test_file_improvement_issue_no_state_change_on_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """When create_issue returns 0, no HITL state should be set."""
        collector, mock_prs, state = _make_collector(config, create_issue_return=0)

        await collector._file_improvement_issue("Pattern: test", "Some body text")

        mock_prs.create_issue.assert_awaited_once()
        assert state.get_hitl_origin(0) is None

    @pytest.mark.asyncio
    async def test_pattern_detection_does_not_set_hitl_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """When pattern detection files an issue, it should not mark HITL state."""
        collector, mock_prs, state = _make_collector(config, create_issue_return=77)
        entries = [
            RetrospectiveEntry(
                issue_number=i,
                pr_number=100 + i,
                timestamp="2026-02-20T10:30:00Z",
                quality_fix_rounds=1,  # >50% → triggers pattern
                plan_accuracy_pct=90,
            )
            for i in range(10)
        ]

        await collector._detect_patterns(entries)

        mock_prs.create_issue.assert_awaited_once()
        assert state.get_hitl_origin(77) is None
        assert state.get_hitl_cause(77) is None


# ---------------------------------------------------------------------------
# _append_entry OSError handling (issue #1038)
# ---------------------------------------------------------------------------


class TestAppendEntryOSError:
    """Verify RetrospectiveCollector._append_entry catches OSError gracefully."""

    def test_append_entry_logs_warning_on_oserror(
        self, config: HydraFlowConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When the retro log can't be written, log warning and don't raise."""
        import logging

        collector, _, _ = _make_collector(config)
        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=100,
            timestamp="2026-02-20T10:30:00Z",
        )

        with (
            patch.object(Path, "open", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="hydraflow.retrospective"),
        ):
            collector._append_entry(entry)  # should not raise

        assert "Could not append to retrospective log" in caplog.text

    def test_append_entry_handles_mkdir_failure(
        self, config: HydraFlowConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When mkdir fails with PermissionError, log warning and don't raise."""
        import logging

        collector, _, _ = _make_collector(config)
        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=100,
            timestamp="2026-02-20T10:30:00Z",
        )

        with (
            patch.object(Path, "mkdir", side_effect=PermissionError("not allowed")),
            caplog.at_level(logging.WARNING, logger="hydraflow.retrospective"),
        ):
            collector._append_entry(entry)  # should not raise

        assert "Could not append to retrospective log" in caplog.text
