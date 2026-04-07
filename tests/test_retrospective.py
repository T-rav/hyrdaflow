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
        mock_prs.get_pr_diff_names.assert_awaited_once()


# ---------------------------------------------------------------------------
# Pattern detection tests
# ---------------------------------------------------------------------------


class TestPatternDetection:
    @pytest.mark.asyncio
    async def test_quality_fix_pattern_detected(self, config: HydraFlowConfig) -> None:
        """When >50% of entries need quality fixes, file_memory_suggestion is called."""
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

        mock_file_mem = AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        mock_file_mem.assert_awaited_once()
        transcript = mock_file_mem.call_args[0][0]
        assert "quality fix" in transcript.lower()
        mock_prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_quality_fix_pattern_not_detected_when_below_threshold(
        self, config: HydraFlowConfig
    ) -> None:
        """When <=50% of entries need quality fixes, no pattern filed."""
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

        mock_file_mem = AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        mock_file_mem.assert_not_awaited()
        mock_prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_plan_accuracy_pattern_detected(
        self, config: HydraFlowConfig
    ) -> None:
        """When average accuracy drops below 70%, file_memory_suggestion is called."""
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

        mock_file_mem = AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        mock_file_mem.assert_awaited_once()
        transcript = mock_file_mem.call_args[0][0]
        assert "plan accuracy" in transcript.lower()

    @pytest.mark.asyncio
    async def test_reviewer_fix_pattern_detected(self, config: HydraFlowConfig) -> None:
        """When >40% of entries have reviewer fixes, file_memory_suggestion is called."""
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

        mock_file_mem = AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        mock_file_mem.assert_awaited_once()
        transcript = mock_file_mem.call_args[0][0]
        assert "reviewer" in transcript.lower()

    @pytest.mark.asyncio
    async def test_unplanned_file_pattern_detected(
        self, config: HydraFlowConfig
    ) -> None:
        """When same file appears unplanned in >30% of entries, pattern is filed."""
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

        mock_file_mem = AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        mock_file_mem.assert_awaited_once()
        transcript = mock_file_mem.call_args[0][0]
        assert "src/common.py" in transcript

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

        mock_file_mem = AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        mock_file_mem.assert_not_awaited()
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

        mock_file_mem = AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        mock_file_mem.assert_not_awaited()
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

        mock_file_mem = AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        # Should not file again since quality_fix is already in filed patterns
        mock_file_mem.assert_not_awaited()
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

        mock_file_mem = AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        # Only 1 pattern filed despite multiple patterns matching
        mock_file_mem.assert_awaited_once()
        mock_prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_improvement_suggestion_contains_knowledge_type(
        self, config: HydraFlowConfig
    ) -> None:
        """Filed improvement suggestion should contain 'type: knowledge' in the transcript."""
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

        mock_file_mem = AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        transcript = mock_file_mem.call_args[0][0]
        assert "type: knowledge" in transcript
        assert "MEMORY_SUGGESTION_START" in transcript


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
        import logging

        collector, _, _ = _make_collector(config)
        with (
            patch.object(Path, "write_text", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="hydraflow.dedup_store"),
        ):
            collector._save_filed_patterns({"quality_fix"})  # should not raise

        assert "Could not write dedup set" in caplog.text


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
    """Tests for memory-routed suggestion filing in _file_improvement_issue."""

    @pytest.mark.asyncio
    async def test_file_improvement_issue_writes_to_jsonl(
        self, config: HydraFlowConfig
    ) -> None:
        """Filing an improvement issue writes to local JSONL via file_memory_suggestion."""
        from unittest.mock import AsyncMock as _AsyncMock

        collector, mock_prs, state = _make_collector(config)

        mock_file_mem = _AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._file_improvement_issue("Pattern: test", "Some body text")

        mock_file_mem.assert_awaited_once()
        transcript_arg = mock_file_mem.call_args[0][0]
        assert "Pattern: test" in transcript_arg
        assert "MEMORY_SUGGESTION_START" in transcript_arg
        # No GitHub issue created
        mock_prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_file_improvement_issue_strips_memory_prefix(
        self, config: HydraFlowConfig
    ) -> None:
        """[Memory] prefix is stripped before writing to JSONL."""
        from unittest.mock import AsyncMock as _AsyncMock

        collector, mock_prs, _ = _make_collector(config)

        mock_file_mem = _AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._file_improvement_issue("[Memory] Pattern: test", "body")

        transcript_arg = mock_file_mem.call_args[0][0]
        # Title should not double-prefix
        assert "[Memory] [Memory]" not in transcript_arg
        assert "Pattern: test" in transcript_arg

    @pytest.mark.asyncio
    async def test_pattern_detection_does_not_set_hitl_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """When pattern detection fires, it writes to JSONL and never sets HITL state."""
        from unittest.mock import AsyncMock as _AsyncMock

        collector, mock_prs, state = _make_collector(config)
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

        mock_file_mem = _AsyncMock()
        with patch("memory.file_memory_suggestion", mock_file_mem):
            await collector._detect_patterns(entries)

        mock_file_mem.assert_awaited_once()
        mock_prs.create_issue.assert_not_awaited()
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
            patch("file_util.open", side_effect=OSError("disk full")),
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


# ---------------------------------------------------------------------------
# Hindsight dual-write tests
# ---------------------------------------------------------------------------


class TestRetrospectiveHindsightDualWrite:
    """Tests for Hindsight dual-write in RetrospectiveCollector._append_entry()."""

    def test_dual_write_fires_via_create_task(self, config: HydraFlowConfig) -> None:
        """When hindsight is set, retain_safe is fire-and-forget via create_task."""
        from unittest.mock import MagicMock

        mock_hindsight = MagicMock()
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        collector = RetrospectiveCollector(
            config, state, mock_prs, hindsight=mock_hindsight
        )

        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=100,
            timestamp="2026-02-20T10:30:00Z",
            plan_accuracy_pct=85.0,
            quality_fix_rounds=2,
            review_verdict=ReviewVerdict.APPROVE,
        )

        mock_task = MagicMock()
        mock_loop = MagicMock()
        mock_loop.create_task = MagicMock(return_value=mock_task)

        with (
            patch("asyncio.get_running_loop", return_value=mock_loop),
            patch("hindsight.retain_safe") as mock_retain,
        ):
            collector._append_entry(entry)
            mock_loop.create_task.assert_called_once()
            # Verify retain_safe was called with correct Bank
            call_args = mock_retain.call_args
            assert call_args is not None
            assert "retrospective for issue #42" in call_args.kwargs["context"]

    def test_file_write_happens_without_hindsight(
        self, config: HydraFlowConfig
    ) -> None:
        """File write still happens when hindsight is None."""
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        collector = RetrospectiveCollector(config, state, mock_prs, hindsight=None)

        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=100,
            timestamp="2026-02-20T10:30:00Z",
        )
        collector._append_entry(entry)

        retro_path = config.data_path("memory", "retrospectives.jsonl")
        assert retro_path.exists()
        assert "42" in retro_path.read_text()

    def test_no_event_loop_skips_dual_write(self, config: HydraFlowConfig) -> None:
        """When no event loop is running, dual-write is silently skipped."""
        from unittest.mock import MagicMock

        mock_hindsight = MagicMock()
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        collector = RetrospectiveCollector(
            config, state, mock_prs, hindsight=mock_hindsight
        )

        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=100,
            timestamp="2026-02-20T10:30:00Z",
        )

        with patch(
            "asyncio.get_running_loop",
            side_effect=RuntimeError("no running event loop"),
        ):
            collector._append_entry(entry)  # should not raise

        # File write skipped because hindsight is set
        retro_path = config.data_path("memory", "retrospectives.jsonl")
        assert not retro_path.exists()

    def test_file_write_skipped_when_hindsight_configured(
        self, config: HydraFlowConfig
    ) -> None:
        """When hindsight client is set, JSONL file write is skipped."""
        from unittest.mock import MagicMock

        mock_hindsight = MagicMock()
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        collector = RetrospectiveCollector(
            config, state, mock_prs, hindsight=mock_hindsight
        )

        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=100,
            timestamp="2026-02-20T10:30:00Z",
        )

        mock_loop = MagicMock()
        mock_loop.create_task = MagicMock()

        with (
            patch("asyncio.get_running_loop", return_value=mock_loop),
            patch("hindsight.retain_safe") as mock_retain,
        ):
            collector._append_entry(entry)
            # Hindsight retain fires
            mock_loop.create_task.assert_called_once()
            mock_retain.assert_called_once()

        # File write does NOT happen
        retro_path = config.data_path("memory", "retrospectives.jsonl")
        assert not retro_path.exists()

    def test_falsy_mock_hindsight_still_retains(self, config: HydraFlowConfig) -> None:
        """A falsy-but-non-None hindsight mock must still trigger schedule_retain."""
        from unittest.mock import AsyncMock, MagicMock

        mock_hindsight = MagicMock()
        mock_hindsight.__bool__ = lambda _self: False  # falsy mock
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        collector = RetrospectiveCollector(
            config, state, mock_prs, hindsight=mock_hindsight
        )

        entry = RetrospectiveEntry(
            issue_number=42,
            pr_number=100,
            timestamp="2026-02-20T10:30:00Z",
        )

        with patch("hindsight.schedule_retain") as mock_retain:
            collector._append_entry(entry)
            # schedule_retain must be called even though mock is falsy
            mock_retain.assert_called_once()

        # File write must NOT happen when hindsight is set (even if falsy)
        retro_path = config.data_path("memory", "retrospectives.jsonl")
        assert not retro_path.exists()


# ---------------------------------------------------------------------------
# Dolt backend integration
# ---------------------------------------------------------------------------


class TestRetrospectiveCollectorDolt:
    """Tests for RetrospectiveCollector with Dolt backend."""

    def test_load_filed_patterns_uses_dolt(self, config: HydraFlowConfig) -> None:
        from unittest.mock import MagicMock

        dolt = MagicMock()
        dolt.get_dedup_set.return_value = {"quality_fix", "plan_accuracy"}
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        collector = RetrospectiveCollector(config, state, mock_prs, dolt=dolt)
        result = collector._load_filed_patterns()
        assert result == {"quality_fix", "plan_accuracy"}
        dolt.get_dedup_set.assert_called_once_with("filed_patterns")

    def test_save_filed_patterns_uses_dolt(self, config: HydraFlowConfig) -> None:
        from unittest.mock import MagicMock

        dolt = MagicMock()
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        collector = RetrospectiveCollector(config, state, mock_prs, dolt=dolt)
        collector._save_filed_patterns({"quality_fix", "reviewer_fixes"})
        dolt.set_dedup_set.assert_called_once_with(
            "filed_patterns", {"quality_fix", "reviewer_fixes"}
        )
        # File should NOT be written
        filed_path = config.data_path("memory", "filed_patterns.json")
        assert not filed_path.exists()

    def test_file_fallback_when_dolt_is_none(self, config: HydraFlowConfig) -> None:
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        collector = RetrospectiveCollector(config, state, mock_prs, dolt=None)
        assert collector._load_filed_patterns() == set()
        collector._save_filed_patterns({"quality_fix"})
        assert collector._load_filed_patterns() == {"quality_fix"}
        # File SHOULD be written
        filed_path = config.data_path("memory", "filed_patterns.json")
        assert filed_path.exists()


# ---------------------------------------------------------------------------
# Sentry breadcrumb tests
# ---------------------------------------------------------------------------


class TestRetrospectiveSentryBreadcrumbs:
    """Sentry breadcrumb emitted when a retrospective is stored."""

    @pytest.mark.asyncio()
    async def test_record_adds_sentry_breadcrumb(self, config: HydraFlowConfig) -> None:
        from unittest.mock import MagicMock

        collector, mock_prs, state = _make_collector(config, diff_names=["src/foo.py"])
        review = ReviewResultFactory.create()

        sentry_mock = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": sentry_mock}):
            await collector.record(42, 101, review)
            assert sentry_mock.add_breadcrumb.called
            kw = sentry_mock.add_breadcrumb.call_args[1]
            assert kw["category"] == "retrospective.stored"
            assert kw["data"]["issue_number"] == 42


class TestRetrospectiveQueueEnqueue:
    """Verify record() enqueues RETRO_PATTERNS when queue is wired."""

    @pytest.mark.asyncio
    async def test_record_enqueues_retro_patterns(
        self, config: HydraFlowConfig
    ) -> None:
        from unittest.mock import MagicMock

        from retrospective_queue import QueueKind

        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.get_pr_diff_names = AsyncMock(return_value=["src/foo.py"])
        mock_queue = MagicMock()

        collector = RetrospectiveCollector(config, state, mock_prs, queue=mock_queue)
        _write_plan(config, 42, "## Files\n- src/foo.py\n")
        review = ReviewResultFactory.create()

        await collector.record(42, 101, review)

        mock_queue.append.assert_called_once()
        item = mock_queue.append.call_args[0][0]
        assert item.kind == QueueKind.RETRO_PATTERNS
        assert item.issue_number == 42

    @pytest.mark.asyncio
    async def test_record_falls_back_to_inline_when_no_queue(
        self, config: HydraFlowConfig
    ) -> None:
        """Without a queue, record() calls _detect_patterns inline."""
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.get_pr_diff_names = AsyncMock(return_value=["src/foo.py"])

        collector = RetrospectiveCollector(config, state, mock_prs)
        _write_plan(config, 42, "## Files\n- src/foo.py\n")
        review = ReviewResultFactory.create()

        # Should not raise — falls back to inline _detect_patterns
        await collector.record(42, 101, review)
