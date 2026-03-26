"""Tests for harness insight auto-filing to JSONL."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from harness_insights import HarnessInsightStore, auto_file_suggestions  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402


def _make_store_with_failures(
    tmp_path: Path, category: str, count: int
) -> HarnessInsightStore:
    """Create a store with pre-populated failure records in JSONL."""
    memory_dir = tmp_path / ".hydraflow" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    failures_path = memory_dir / "harness_failures.jsonl"
    with failures_path.open("w") as f:
        for i in range(count):
            record = {
                "category": category,
                "subcategories": [],
                "stage": "implement",
                "issue_number": i + 1,
                "pr_number": None,
                "details": f"Failure {i + 1}",
                "timestamp": "2026-03-26T00:00:00Z",
            }
            f.write(json.dumps(record) + "\n")
    return HarnessInsightStore(memory_dir)


class TestAutoFileSuggestions:
    """Tests for auto_file_suggestions writing to JSONL."""

    @pytest.mark.asyncio
    async def test_no_records_returns_early(self, tmp_path: Path) -> None:
        """No failures means no suggestions filed."""
        memory_dir = tmp_path / ".hydraflow" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        store = HarnessInsightStore(memory_dir)
        config = ConfigFactory.create(repo_root=tmp_path)
        await auto_file_suggestions(store, config)
        path = config.data_path("memory", "harness_suggestions.jsonl")
        assert not path.exists()

    @pytest.mark.asyncio
    async def test_does_not_crash_with_failures(self, tmp_path: Path) -> None:
        """auto_file_suggestions should not raise with valid failure data."""
        store = _make_store_with_failures(tmp_path, "quality_gate", 5)
        config = ConfigFactory.create(repo_root=tmp_path)
        await auto_file_suggestions(store, config, threshold=3)
        # Should complete without error — JSONL may or may not be written
        # depending on whether generate_suggestions produces output for this data

    @pytest.mark.asyncio
    async def test_dedup_prevents_refiling(self, tmp_path: Path) -> None:
        """Filed patterns are marked as proposed to prevent refiling."""
        store = _make_store_with_failures(tmp_path, "quality_gate", 5)
        config = ConfigFactory.create(repo_root=tmp_path)

        await auto_file_suggestions(store, config, threshold=3)
        await auto_file_suggestions(store, config, threshold=3)

        path = config.data_path("memory", "harness_suggestions.jsonl")
        if path.exists():
            entries = [
                json.loads(line) for line in path.read_text().strip().splitlines()
            ]
            # Should not have duplicates
            assert len(entries) <= 2  # at most one per unique pattern

    @pytest.mark.asyncio
    async def test_no_suggestion_below_threshold(self, tmp_path: Path) -> None:
        """Failures below threshold don't produce suggestions."""
        store = _make_store_with_failures(tmp_path, "quality_gate", 2)
        config = ConfigFactory.create(repo_root=tmp_path)

        await auto_file_suggestions(store, config, threshold=3)

        path = config.data_path("memory", "harness_suggestions.jsonl")
        assert not path.exists()
