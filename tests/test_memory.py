"""Tests for the memory digest system."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory import (
    MemorySyncWorker,
    _parse_memory_type,
    build_memory_issue_body,
    file_memory_suggestion,
    parse_memory_suggestion,
)
from models import MEMORY_TYPE_DISPLAY_ORDER, MemoryType
from state import StateTracker
from tests.helpers import ConfigFactory

# --- parse_memory_suggestion tests ---


class TestParseMemorySuggestion:
    """Tests for parsing MEMORY_SUGGESTION blocks from transcripts."""

    def test_valid_block_extracts_title_and_learning(self) -> None:
        transcript = (
            "Some output here\n"
            "MEMORY_SUGGESTION_START\n"
            "title: Always run make lint before make test\n"
            "learning: Running make lint first catches formatting issues.\n"
            "context: Discovered during implementation of issue #42.\n"
            "MEMORY_SUGGESTION_END\n"
            "More output"
        )
        result = parse_memory_suggestion(transcript)
        assert result is not None
        assert result["title"] == "Always run make lint before make test"
        assert (
            result["learning"] == "Running make lint first catches formatting issues."
        )
        assert result["context"] == "Discovered during implementation of issue #42."
        # Default type when missing
        assert result["type"] == "knowledge"

    def test_no_block_returns_none(self) -> None:
        transcript = "Just regular output with no suggestion"
        result = parse_memory_suggestion(transcript)
        assert result is None

    def test_multiple_blocks_returns_first(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: First suggestion\n"
            "learning: First learning\n"
            "context: First context\n"
            "MEMORY_SUGGESTION_END\n"
            "MEMORY_SUGGESTION_START\n"
            "title: Second suggestion\n"
            "learning: Second learning\n"
            "context: Second context\n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is not None
        assert result["title"] == "First suggestion"

    def test_missing_title_returns_none(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "learning: Some learning\n"
            "context: Some context\n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is None

    def test_missing_learning_returns_none(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Some title\n"
            "context: Some context\n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is None

    def test_empty_fields_returns_none(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: \n"
            "learning: \n"
            "context: \n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is None

    def test_empty_context_still_valid(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Some title\n"
            "learning: Some learning\n"
            "context: \n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is not None
        assert result["context"] == ""


# --- Memory type parsing tests ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("knowledge", MemoryType.KNOWLEDGE),
        ("config", MemoryType.CONFIG),
        ("instruction", MemoryType.INSTRUCTION),
        ("code", MemoryType.CODE),
        ("CONFIG", MemoryType.CONFIG),
        ("Knowledge", MemoryType.KNOWLEDGE),
        ("CODE", MemoryType.CODE),
        ("  config  ", MemoryType.CONFIG),
        ("", MemoryType.KNOWLEDGE),
        ("banana", MemoryType.KNOWLEDGE),
        ("foobar", MemoryType.KNOWLEDGE),
    ],
)
def test_parse_memory_type(raw: str, expected: MemoryType) -> None:
    """_parse_memory_type normalises raw strings to the correct MemoryType."""
    assert _parse_memory_type(raw) == expected


def _make_suggestion_transcript(type_line: str | None) -> str:
    lines = ["MEMORY_SUGGESTION_START", "title: Test"]
    if type_line is not None:
        lines.append(type_line)
    lines += ["learning: A learning", "context: ctx", "MEMORY_SUGGESTION_END", ""]
    return "\n".join(lines)


@pytest.mark.parametrize(
    ("type_line", "expected_type"),
    [
        ("type: knowledge", "knowledge"),
        ("type: config", "config"),
        ("type: instruction", "instruction"),
        ("type: code", "code"),
        (None, "knowledge"),
        ("type: banana", "knowledge"),
        ("type: ", "knowledge"),
    ],
)
def test_parse_memory_suggestion_type(
    type_line: str | None, expected_type: str
) -> None:
    """parse_memory_suggestion resolves the type field to the expected value."""
    transcript = _make_suggestion_transcript(type_line)
    result = parse_memory_suggestion(transcript)
    assert result is not None
    assert result["type"] == expected_type


class TestMemoryTypeEnum:
    """Tests for the MemoryType enum and its is_actionable classmethod."""

    def test_memory_type__values(self) -> None:
        assert MemoryType.KNOWLEDGE.value == "knowledge"
        assert MemoryType.CONFIG.value == "config"
        assert MemoryType.INSTRUCTION.value == "instruction"
        assert MemoryType.CODE.value == "code"

    def test_memory_type__is_actionable_knowledge(self) -> None:
        assert MemoryType.is_actionable(MemoryType.KNOWLEDGE) is False

    def test_memory_type__is_actionable_config(self) -> None:
        assert MemoryType.is_actionable(MemoryType.CONFIG) is True

    def test_memory_type__is_actionable_instruction(self) -> None:
        assert MemoryType.is_actionable(MemoryType.INSTRUCTION) is True

    def test_memory_type__is_actionable_code(self) -> None:
        assert MemoryType.is_actionable(MemoryType.CODE) is True

    def test_memory_type_display_order__contains_all_types(self) -> None:
        assert set(MEMORY_TYPE_DISPLAY_ORDER) == set(MemoryType)

    def test_memory_type_display_order__actionable_first(self) -> None:
        """Actionable types should come before knowledge in display order."""
        knowledge_idx = MEMORY_TYPE_DISPLAY_ORDER.index(MemoryType.KNOWLEDGE)
        for mtype in [MemoryType.CONFIG, MemoryType.INSTRUCTION, MemoryType.CODE]:
            assert MEMORY_TYPE_DISPLAY_ORDER.index(mtype) < knowledge_idx


# --- build_memory_issue_body tests ---


class TestBuildMemoryIssueBody:
    """Tests for building GitHub issue bodies for memory suggestions."""

    def test_structured_output(self) -> None:
        body = build_memory_issue_body(
            learning="Always run lint first",
            context="Found during issue #42",
            source="planner",
            reference="issue #42",
        )
        assert "## Memory Suggestion" in body
        assert "**Learning:** Always run lint first" in body
        assert "**Context:** Found during issue #42" in body
        assert "**Source:** planner during issue #42" in body
        # Default type
        assert "**Type:** knowledge" in body

    def test_includes_source_and_reference(self) -> None:
        body = build_memory_issue_body(
            learning="Test learning",
            context="Test context",
            source="reviewer",
            reference="PR #99",
        )
        assert "reviewer during PR #99" in body

    def test_build_memory_issue_body__includes_type(self) -> None:
        body = build_memory_issue_body(
            learning="Increase timeout",
            context="CI failures",
            source="reviewer",
            reference="PR #10",
            memory_type="config",
        )
        assert "**Type:** config" in body

    def test_build_memory_issue_body__default_type_is_knowledge(self) -> None:
        body = build_memory_issue_body(
            learning="Something",
            context="Somewhere",
            source="agent",
            reference="issue #1",
        )
        assert "**Type:** knowledge" in body


# --- MemorySyncWorker tests ---


class TestMemorySyncWorkerExtractLearning:
    """Tests for learning extraction from issue bodies."""

    def test_structured_body(self) -> None:
        body = (
            "## Memory Suggestion\n\n"
            "**Learning:** Always use atomic writes for state files\n\n"
            "**Context:** Found during testing\n"
        )
        result = MemorySyncWorker._extract_learning(body)
        assert result == "Always use atomic writes for state files"

    def test_unstructured_fallback(self) -> None:
        body = "This is just a plain issue body with some text about a learning."
        result = MemorySyncWorker._extract_learning(body)
        assert result == body.strip()

    def test_empty_body(self) -> None:
        result = MemorySyncWorker._extract_learning("")
        assert result == ""

    def test_whitespace_body(self) -> None:
        result = MemorySyncWorker._extract_learning("   \n  ")
        assert result == ""


class TestMemorySyncWorkerSync:
    """Tests for the full sync method."""

    @pytest.mark.asyncio
    async def test_no_issues_returns_zero_count(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        worker = MemorySyncWorker(config, state, bus)
        # No items.jsonl — empty sync
        stats = await worker.sync()

        assert stats["item_count"] == 0
        state.update_memory_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_syncs_local_items(self, tmp_path: Path) -> None:
        """sync() reads from items.jsonl, processes items, and reports counts."""
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        # Write items directly to JSONL (the write-ahead queue)
        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        items = [
            {
                "id": "mem-aaa",
                "title": "Test learning",
                "learning": "Always test first",
                "context": "Found in testing",
                "memory_type": "knowledge",
                "source": "implementer",
                "reference": "#10",
                "created_at": "2024-06-01T00:00:00Z",
            },
            {
                "id": "mem-bbb",
                "title": "Another learning",
                "learning": "Use type hints",
                "context": "Code review",
                "memory_type": "knowledge",
                "source": "reviewer",
                "reference": "#20",
                "created_at": "2024-05-01T00:00:00Z",
            },
        ]
        with items_path.open("w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        stats = await worker.sync()

        assert stats["item_count"] == 2
        assert stats["action"] == "synced"
        # digest.md should NOT exist — memory is Hindsight-only
        digest_path = config.data_path("memory", "digest.md")
        assert not digest_path.exists()

    @pytest.mark.asyncio
    async def test_skips_compaction_when_no_change(self, tmp_path: Path) -> None:
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        items = [
            {
                "id": "mem-aaa",
                "title": "Item A",
                "learning": "First learning",
                "context": "",
                "memory_type": "knowledge",
                "source": "implementer",
                "reference": "#10",
                "created_at": "2024-06-01T00:00:00Z",
            },
            {
                "id": "mem-bbb",
                "title": "Item B",
                "learning": "Second learning",
                "context": "",
                "memory_type": "knowledge",
                "source": "implementer",
                "reference": "#20",
                "created_at": "2024-05-01T00:00:00Z",
            },
        ]
        with items_path.open("w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        stats = await worker.sync()

        assert stats["compacted"] is False
        assert stats["item_count"] == 2

    @pytest.mark.asyncio
    async def test_detects_new_issues_and_rebuilds(self, tmp_path: Path) -> None:
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)

        item_a = {
            "id": "mem-aaa",
            "title": "Old item",
            "learning": "Old thing",
            "context": "",
            "memory_type": "knowledge",
            "source": "implementer",
            "reference": "#10",
            "created_at": "2024-05-01T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write(json.dumps(item_a) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        stats1 = await worker.sync()
        assert stats1["item_count"] == 1

        # Add a second item and sync again
        item_b = {
            "id": "mem-bbb",
            "title": "New item",
            "learning": "New thing",
            "context": "",
            "memory_type": "knowledge",
            "source": "implementer",
            "reference": "#30",
            "created_at": "2024-06-01T00:00:00Z",
        }
        with items_path.open("a") as f:
            f.write(json.dumps(item_b) + "\n")

        state.get_memory_state.return_value = ([], "oldhash", "2024-05-01")
        stats2 = await worker.sync()
        assert stats2["item_count"] == 2
        state.update_memory_state.assert_called()

    @pytest.mark.asyncio
    async def test_updates_state(self, tmp_path: Path) -> None:
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "id": "mem-abc12345",
            "title": "T",
            "learning": "Something",
            "context": "",
            "memory_type": "knowledge",
            "source": "implementer",
            "reference": "#5",
            "created_at": "2024-06-01T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write(json.dumps(item) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        await worker.sync()

        state.update_memory_state.assert_called()
        call_args = state.update_memory_state.call_args[0]
        assert len(call_args[0]) == 1  # one item ID
        assert isinstance(call_args[1], str)  # digest hash

    @pytest.mark.asyncio
    async def test_sync_routes_architecture_memory_to_adr_task(
        self, tmp_path: Path
    ) -> None:
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "id": "mem-arch01",
            "title": "Shift to event-driven architecture",
            "learning": "We shifted service boundaries and queue topology.",
            "context": "Runtime scaling bottleneck.",
            "memory_type": "knowledge",
            "source": "implementer",
            "reference": "#5",
            "created_at": "2024-06-01T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write(json.dumps(item) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        await worker.sync()

        adr_decisions_path = config.data_path("memory", "adr_decisions.jsonl")
        assert adr_decisions_path.exists()
        entries = []
        for line in adr_decisions_path.read_text().splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                entries.append(json.loads(line))
        assert len(entries) == 1
        assert "[ADR] Draft decision from memory #" in entries[0]["title"]
        assert "## Decision" in entries[0]["body"]
        assert "<Chosen architecture/workflow shift>" not in entries[0]["body"]

    @pytest.mark.asyncio
    async def test_sync_rejects_invalid_adr_candidate_and_deduplicates(
        self, tmp_path: Path
    ) -> None:
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "id": "mem-arch05",
            "title": "Architecture update",
            "learning": "Architecture decision changed worker topology.",
            "context": "",
            "memory_type": "knowledge",
            "source": "implementer",
            "reference": "#5",
            "created_at": "2024-06-01T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write(json.dumps(item) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        worker._build_adr_task = MagicMock(  # type: ignore[method-assign]
            return_value=(
                "[ADR] Draft decision from memory #bad",
                "## ADR Draft Task\n\n## Context\nShort.\n\n## Decision\nNope.\n",
            )
        )

        await worker.sync()
        await worker.sync()

        # Invalid candidate should not produce any JSONL entries
        adr_decisions_path = config.data_path("memory", "adr_decisions.jsonl")
        entries = []
        if adr_decisions_path.exists():
            for line in adr_decisions_path.read_text().splitlines():
                with contextlib.suppress(json.JSONDecodeError):
                    entries.append(json.loads(line))
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_sync_adr_routing_deduplicates_by_source_issue(
        self, tmp_path: Path
    ) -> None:
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "id": "mem-arch06",
            "title": "Architecture update",
            "learning": "Architecture decision changed worker topology.",
            "context": "",
            "memory_type": "knowledge",
            "source": "implementer",
            "reference": "#5",
            "created_at": "2024-06-01T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write(json.dumps(item) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        # Sync twice with the same items — ADR should only be written once
        await worker.sync()
        await worker.sync()

        adr_decisions_path = config.data_path("memory", "adr_decisions.jsonl")
        entries = []
        if adr_decisions_path.exists():
            for line in adr_decisions_path.read_text().splitlines():
                with contextlib.suppress(json.JSONDecodeError):
                    entries.append(json.loads(line))
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_sync_adr_deduplicates_by_topic_content(self, tmp_path: Path) -> None:
        """Two memory items about the same topic should only write one JSONL entry."""
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        items = [
            {
                "id": "mem-adr10",
                "title": "ADR test policy — only structural tests allowed",
                "learning": "Architecture decision: ADR tests structural only.",
                "context": "",
                "memory_type": "knowledge",
                "source": "implementer",
                "reference": "#10",
                "created_at": "2024-06-01T00:00:00Z",
            },
            {
                "id": "mem-adr11",
                "title": "ADR test policy — only structural tests allowed",
                "learning": "Architecture decision: ADR tests structural only.",
                "context": "",
                "memory_type": "knowledge",
                "source": "implementer",
                "reference": "#11",
                "created_at": "2024-06-02T00:00:00Z",
            },
        ]
        with items_path.open("w") as f:
            for it in items:
                f.write(json.dumps(it) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        await worker.sync()

        adr_decisions_path = config.data_path("memory", "adr_decisions.jsonl")
        entries = []
        if adr_decisions_path.exists():
            for line in adr_decisions_path.read_text().splitlines():
                with contextlib.suppress(json.JSONDecodeError):
                    entries.append(json.loads(line))
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_sync_adr_skips_topic_covered_by_existing_adr_file(
        self, tmp_path: Path
    ) -> None:
        """ADR candidate should be skipped if docs/adr/ already has that topic."""
        import json

        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-worker-topology.md").write_text("# ADR\n")

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "id": "mem-wt20",
            "title": "Worker topology",
            "learning": "Architecture decision about worker topology.",
            "context": "",
            "memory_type": "knowledge",
            "source": "implementer",
            "reference": "#20",
            "created_at": "2024-06-01T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write(json.dumps(item) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        await worker.sync()

        adr_decisions_path = config.data_path("memory", "adr_decisions.jsonl")
        assert (
            not adr_decisions_path.exists()
            or adr_decisions_path.read_text().strip() == ""
        )

    def test_normalize_adr_topic_strips_prefixes(self) -> None:
        from phase_utils import normalize_adr_topic

        assert (
            normalize_adr_topic("[Memory] ADR test policy — only structural tests")
            == "adr test policy only structural tests"
        )
        assert (
            normalize_adr_topic(
                "[ADR] Draft decision from memory #123: Worker topology shift"
            )
            == "worker topology shift"
        )

    def test_load_existing_adr_topics_reads_docs_adr(self, tmp_path: Path) -> None:
        from phase_utils import load_existing_adr_topics

        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-five-concurrent-loops.md").write_text("# ADR\n")
        (adr_dir / "0002-labels-state-machine.md").write_text("# ADR\n")
        (adr_dir / "README.md").write_text("# Index\n")

        topics = load_existing_adr_topics(tmp_path)
        assert "five concurrent loops" in topics
        assert "labels state machine" in topics
        assert len(topics) == 2  # README excluded

    @pytest.mark.asyncio
    async def test_publish_sync_event(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        bus = MagicMock()
        bus.publish = AsyncMock()

        worker = MemorySyncWorker(config, state, bus)
        stats = {
            "action": "synced",
            "item_count": 3,
            "compacted": False,
            "digest_chars": 100,
        }
        await worker.publish_sync_event(stats)

        bus.publish.assert_called_once()
        event = bus.publish.call_args[0][0]
        assert event.type.value == "memory_sync"
        assert event.data["item_count"] == 3

    @pytest.mark.asyncio
    async def test_sync_concurrent_calls_complete_without_error(
        self, tmp_path: Path
    ) -> None:
        """Two concurrent sync() calls should both complete without corruption."""
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        items = [
            {
                "id": "mem-con01",
                "title": "First",
                "learning": "First learning",
                "context": "",
                "memory_type": "knowledge",
                "source": "implementer",
                "reference": "#10",
                "created_at": "2024-06-01T00:00:00Z",
            },
            {
                "id": "mem-con02",
                "title": "Second",
                "learning": "Second learning",
                "context": "",
                "memory_type": "knowledge",
                "source": "implementer",
                "reference": "#20",
                "created_at": "2024-06-02T00:00:00Z",
            },
        ]
        with items_path.open("w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

        worker = MemorySyncWorker(config, state, bus)

        results = await asyncio.gather(
            worker.sync(),
            worker.sync(),
            return_exceptions=True,
        )

        # Both calls should complete without raising
        for r in results:
            assert not isinstance(r, Exception), f"sync() raised: {r}"


# --- State tracking tests ---


class TestMemoryState:
    """Tests for memory state persistence in StateTracker."""

    def test_update_and_get_memory_state(self, tmp_path: Path) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)

        tracker.update_memory_state([1, 2, 3], "abc123")

        ids, hash_val, last_synced = tracker.get_memory_state()
        assert ids == [1, 2, 3]
        assert hash_val == "abc123"
        assert last_synced is not None

    def test_get_memory_state_defaults(self, tmp_path: Path) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)

        ids, hash_val, last_synced = tracker.get_memory_state()
        assert ids == []
        assert hash_val == ""
        assert last_synced is None

    def test_memory_state_persists_to_disk(self, tmp_path: Path) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.update_memory_state([10, 20], "hash1")

        # Reload from disk
        tracker2 = StateTracker(state_file)
        ids, hash_val, last_synced = tracker2.get_memory_state()
        assert ids == [10, 20]
        assert hash_val == "hash1"
        assert last_synced is not None


# --- Config tests ---


class TestMemoryConfig:
    """Tests for memory-related config fields."""

    def test_memory_sync_interval_default(self) -> None:
        from config import HydraFlowConfig

        config = HydraFlowConfig(repo="test/repo")
        assert config.memory_sync_interval == 3600

    def test_max_memory_chars_default(self) -> None:
        from config import HydraFlowConfig

        config = HydraFlowConfig(repo="test/repo")
        assert config.max_memory_chars == 4000

    def test_max_memory_prompt_chars_default(self) -> None:
        from config import HydraFlowConfig

        config = HydraFlowConfig(repo="test/repo")
        assert config.max_memory_prompt_chars == 4000

    def test_memory_sync_interval_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import HydraFlowConfig

        monkeypatch.setenv("HYDRAFLOW_MEMORY_SYNC_INTERVAL", "60")
        config = HydraFlowConfig(repo="test/repo")
        assert config.memory_sync_interval == 60


# --- Models tests ---


class TestMemoryModels:
    """Tests for memory-related model fields."""

    def test_state_data_memory_fields_default(self) -> None:
        from models import StateData

        data = StateData()
        assert data.memory_issue_ids == []
        assert data.memory_digest_hash == ""
        assert data.memory_last_synced is None

    def test_github_issue_created_at_from_camel_case(self) -> None:
        from models import GitHubIssue

        issue = GitHubIssue.model_validate(
            {
                "number": 42,
                "title": "Test",
                "createdAt": "2024-06-15T12:00:00Z",
            }
        )
        assert issue.created_at == "2024-06-15T12:00:00Z"

    def test_github_issue_created_at_default_empty(self) -> None:
        from tests.conftest import IssueFactory

        issue = IssueFactory.create(number=1, title="Test")
        assert issue.created_at == ""

    def test_github_issue_created_at_snake_case(self) -> None:
        from tests.conftest import IssueFactory

        issue = IssueFactory.create(number=1, title="Test", created_at="2024-01-01")
        assert issue.created_at == "2024-01-01"


# --- Config: memory_compaction_model tests ---


class TestMemoryCompactionModelConfig:
    """Tests for the memory_compaction_model config field."""

    def test_default_is_haiku(self) -> None:
        from config import HydraFlowConfig

        config = HydraFlowConfig(repo="test/repo")
        assert config.memory_compaction_model == "haiku"

    def test_custom_model(self) -> None:
        config = ConfigFactory.create(memory_compaction_model="sonnet")
        assert config.memory_compaction_model == "sonnet"


# --- PR Manager tests ---


# --- Orchestrator tests ---


class TestExtractMemoryType:
    """Tests for _extract_memory_type from issue bodies."""

    def test_extract_memory_type__knowledge(self) -> None:
        body = "## Memory Suggestion\n\n**Type:** knowledge\n\n**Learning:** Foo\n"
        assert MemorySyncWorker._extract_memory_type(body) == MemoryType.KNOWLEDGE

    def test_extract_memory_type__config(self) -> None:
        body = "## Memory Suggestion\n\n**Type:** config\n\n**Learning:** Foo\n"
        assert MemorySyncWorker._extract_memory_type(body) == MemoryType.CONFIG

    def test_extract_memory_type__instruction(self) -> None:
        body = "## Memory Suggestion\n\n**Type:** instruction\n\n**Learning:** Foo\n"
        assert MemorySyncWorker._extract_memory_type(body) == MemoryType.INSTRUCTION

    def test_extract_memory_type__code(self) -> None:
        body = "## Memory Suggestion\n\n**Type:** code\n\n**Learning:** Foo\n"
        assert MemorySyncWorker._extract_memory_type(body) == MemoryType.CODE

    def test_extract_memory_type__missing_defaults_to_knowledge(self) -> None:
        body = "## Memory Suggestion\n\n**Learning:** Foo\n"
        assert MemorySyncWorker._extract_memory_type(body) == MemoryType.KNOWLEDGE

    def test_extract_memory_type__empty_body(self) -> None:
        assert MemorySyncWorker._extract_memory_type("") == MemoryType.KNOWLEDGE

    def test_extract_memory_type__unrecognised_defaults_to_knowledge(self) -> None:
        body = "**Type:** banana\n\n**Learning:** Foo\n"
        assert MemorySyncWorker._extract_memory_type(body) == MemoryType.KNOWLEDGE


class TestFileMemorySuggestionLocal:
    """Tests for the local JSONL-based memory suggestion filing."""

    @pytest.mark.asyncio
    async def test_writes_item_to_jsonl(self, tmp_path: Path) -> None:
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Test\n"
            "type: knowledge\n"
            "learning: Always test\n"
            "context: Testing\n"
            "MEMORY_SUGGESTION_END"
        )
        await file_memory_suggestion(transcript, "implementer", "#42", config)
        items_path = config.data_path("memory", "items.jsonl")
        assert items_path.exists()
        items = [
            json.loads(line) for line in items_path.read_text().strip().splitlines()
        ]
        assert len(items) == 1
        assert items[0]["learning"] == "Always test"
        assert items[0]["memory_type"] == "knowledge"

    @pytest.mark.asyncio
    async def test_no_suggestion_no_write(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        await file_memory_suggestion("no suggestion here", "implementer", "#42", config)
        items_path = config.data_path("memory", "items.jsonl")
        assert not items_path.exists()

    @pytest.mark.asyncio
    async def test_appends_multiple_items(self, tmp_path: Path) -> None:
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        for i in range(3):
            transcript = (
                f"MEMORY_SUGGESTION_START\n"
                f"title: Item {i}\n"
                f"type: knowledge\n"
                f"learning: Learn {i}\n"
                f"context: ctx\n"
                f"MEMORY_SUGGESTION_END"
            )
            await file_memory_suggestion(transcript, "implementer", f"#{i}", config)
        items_path = config.data_path("memory", "items.jsonl")
        items = [
            json.loads(line) for line in items_path.read_text().strip().splitlines()
        ]
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_item_contains_expected_fields(self, tmp_path: Path) -> None:
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Field check\n"
            "type: config\n"
            "learning: Check all fields\n"
            "context: During testing\n"
            "MEMORY_SUGGESTION_END"
        )
        await file_memory_suggestion(transcript, "reviewer", "#99", config)
        items_path = config.data_path("memory", "items.jsonl")
        item = json.loads(items_path.read_text().strip())
        assert item["title"] == "Field check"
        assert item["memory_type"] == "config"
        assert item["source"] == "reviewer"
        assert item["reference"] == "#99"
        assert "id" in item
        assert "created_at" in item


class TestSyncWithTypedIssues:
    """Tests for MemorySyncWorker.sync with typed JSONL items."""

    @pytest.mark.asyncio
    async def test_sync__typed_items_reports_correct_count(
        self, tmp_path: Path
    ) -> None:
        """Sync with typed JSONL items processes items of mixed types."""
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        items = [
            {
                "id": "mem-cfg10",
                "title": "Config change",
                "learning": "Increase timeout",
                "context": "CI failures",
                "memory_type": "config",
                "source": "implementer",
                "reference": "#10",
                "created_at": "2024-06-01T00:00:00Z",
            },
            {
                "id": "mem-kno20",
                "title": "Knowledge item",
                "learning": "Use type hints",
                "context": "Code review",
                "memory_type": "knowledge",
                "source": "reviewer",
                "reference": "#20",
                "created_at": "2024-05-01T00:00:00Z",
            },
        ]
        with items_path.open("w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        stats = await worker.sync()

        assert stats["item_count"] == 2
        # digest.md should NOT exist — Hindsight is the memory store
        assert not config.data_path("memory", "digest.md").exists()

    @pytest.mark.asyncio
    async def test_sync__untyped_items_default_to_knowledge(
        self, tmp_path: Path
    ) -> None:
        """Items without a memory_type field should be treated as knowledge type."""
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "id": "mem-leg10",
            "title": "Legacy item",
            "learning": "Old learning without type",
            "context": "Before types existed",
            # no memory_type field — should default to knowledge
            "source": "implementer",
            "reference": "#10",
            "created_at": "2024-01-01T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write(json.dumps(item) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        stats = await worker.sync()

        assert stats["item_count"] == 1
        # digest.md should NOT exist
        assert not config.data_path("memory", "digest.md").exists()


# --- Orchestrator tests ---


class TestMemorySyncLoop:
    """Tests for memory sync loop registration in orchestrator."""

    def test_memory_sync_in_loop_factories(self) -> None:
        """Verify memory_sync loop is registered in _supervise_loops."""
        # Read the source to check the loop is registered
        import inspect

        from orchestrator import HydraFlowOrchestrator

        source = inspect.getsource(HydraFlowOrchestrator._supervise_loops)
        assert "memory_sync" in source
        assert "_memory_sync_loop" in source


# --- Per-item isolation tests ---


class TestSyncPerItemIsolation:
    """Per-item try/except in sync() prevents one bad JSONL item from aborting the batch."""

    @pytest.mark.asyncio
    async def test_bad_issue_skipped_good_issue_still_synced(
        self, tmp_path: Path
    ) -> None:
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        # Write one malformed JSONL line (invalid JSON) followed by one valid item
        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        good_item = {
            "id": "mem-good01",
            "title": "Good issue",
            "learning": "Always test first",
            "context": "",
            "memory_type": "knowledge",
            "source": "implementer",
            "reference": "#20",
            "created_at": "2024-05-01T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write("{bad json line\n")  # malformed — should be skipped
            f.write(json.dumps(good_item) + "\n")

        worker = MemorySyncWorker(config, state, bus)
        stats = await worker.sync()

        # The malformed line was skipped; the good item was synced
        assert stats["item_count"] == 1
        # digest.md should NOT exist — Hindsight is the memory store
        assert not config.data_path("memory", "digest.md").exists()


class TestRouteAdrCandidatesPerItemIsolation:
    """Per-item try/except in _route_adr_candidates prevents one failure from aborting routing."""

    @pytest.mark.asyncio
    async def test_exception_in_item_processing_skips_and_continues_to_next(
        self, tmp_path: Path
    ) -> None:
        """An exception during per-item processing should not abort the loop."""

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        worker = MemorySyncWorker(config, state, bus)

        call_count = 0
        original_validate = worker._validate_adr_task

        def fail_then_succeed(body: str) -> list[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Unexpected processing error")
            return original_validate(body)

        worker._validate_adr_task = fail_then_succeed  # type: ignore[method-assign]

        # Both issues are architecture candidates (contain "architecture" keyword)
        issues = [
            {
                "number": 10,
                "title": "[Memory] Architecture shift alpha",
                "body": "**Type:** knowledge\n\n**Learning:** Major architecture change alpha",
                "labels": ["hydraflow-find"],
                "createdAt": "2024-06-01",
            },
            {
                "number": 20,
                "title": "[Memory] Architecture shift beta",
                "body": "**Type:** knowledge\n\n**Learning:** Major architecture change beta",
                "labels": ["hydraflow-find"],
                "createdAt": "2024-06-02",
            },
        ]

        # Ensure no existing ADR sources
        adr_sources_path = config.data_path("memory", "adr_sources.json")
        adr_sources_path.parent.mkdir(parents=True, exist_ok=True)

        with (
            patch("phase_utils.load_existing_adr_topics", return_value=set()),
            patch("phase_utils.normalize_adr_topic", side_effect=lambda t: t.lower()),
        ):
            await worker._route_adr_candidates(issues)

        # First call raised, second was processed — validate was called twice
        assert call_count == 2


# ---------------------------------------------------------------------------
# Hindsight dual-write tests
# ---------------------------------------------------------------------------


class TestMemorySyncHindsightDualWrite:
    """Tests for Hindsight dual-write in MemorySyncWorker.sync()."""

    @pytest.mark.asyncio
    async def test_dual_write_fires_for_each_learning(self, tmp_path: Path) -> None:
        """When hindsight client is set, retain_safe is called for each learning."""
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = StateTracker(config.state_file)
        bus = MagicMock()
        bus.publish = AsyncMock()
        mock_hindsight = MagicMock()
        worker = MemorySyncWorker(config, state, bus, hindsight=mock_hindsight)

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        items = [
            {
                "id": "mem-hw01",
                "title": "Learn A",
                "learning": "First insight",
                "context": "",
                "memory_type": "knowledge",
                "source": "implementer",
                "reference": "#1",
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": "mem-hw02",
                "title": "Learn B",
                "learning": "Second insight",
                "context": "",
                "memory_type": "config",
                "source": "implementer",
                "reference": "#2",
                "created_at": "2024-01-02T00:00:00Z",
            },
        ]
        with items_path.open("w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

        with patch("hindsight.retain_safe", new_callable=AsyncMock) as mock_retain:
            await worker.sync()
            assert mock_retain.await_count == 2
            # Verify first call args include the hindsight client
            call_args_list = mock_retain.call_args_list
            assert call_args_list[0].args[0] is mock_hindsight

    @pytest.mark.asyncio
    async def test_no_file_write_without_hindsight(self, tmp_path: Path) -> None:
        """digest.md is never written, even when hindsight is None."""
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = StateTracker(config.state_file)
        bus = MagicMock()
        bus.publish = AsyncMock()
        worker = MemorySyncWorker(config, state, bus, hindsight=None)

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "id": "mem-fw01",
            "title": "Test",
            "learning": "Something",
            "context": "",
            "memory_type": "knowledge",
            "source": "implementer",
            "reference": "#1",
            "created_at": "2024-01-01T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write(json.dumps(item) + "\n")

        await worker.sync()

        # digest.md should NEVER be written — Hindsight is the exclusive memory store
        digest_path = config.data_path("memory", "digest.md")
        assert not digest_path.exists()

    @pytest.mark.asyncio
    async def test_dual_write_passes_correct_bank_and_metadata(
        self, tmp_path: Path
    ) -> None:
        """Verify retain_safe is called with the LEARNINGS bank and correct metadata."""
        import json

        from hindsight import Bank

        config = ConfigFactory.create(repo_root=tmp_path)
        state = StateTracker(config.state_file)
        bus = MagicMock()
        bus.publish = AsyncMock()
        mock_hindsight = MagicMock()
        worker = MemorySyncWorker(config, state, bus, hindsight=mock_hindsight)

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "id": "mem-dw07",
            "title": "Config tip",
            "learning": "Use env vars",
            "context": "",
            "memory_type": "config",
            "source": "implementer",
            "reference": "#7",
            "created_at": "2024-03-15T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write(json.dumps(item) + "\n")

        with patch("hindsight.retain_safe", new_callable=AsyncMock) as mock_retain:
            await worker.sync()
            mock_retain.assert_called_once()
            call_kw = mock_retain.call_args
            assert call_kw.args[1] == Bank.LEARNINGS
            assert call_kw.args[2] == "Use env vars"
            assert call_kw.kwargs["metadata"]["item_id"] is not None
            assert call_kw.kwargs["metadata"]["memory_type"] == "config"

    @pytest.mark.asyncio
    async def test_no_digest_file_when_hindsight_configured(
        self, tmp_path: Path
    ) -> None:
        """digest.md is never written regardless of whether hindsight is configured."""
        import json

        config = ConfigFactory.create(repo_root=tmp_path)
        state = StateTracker(config.state_file)
        bus = MagicMock()
        bus.publish = AsyncMock()
        mock_hindsight = MagicMock()
        worker = MemorySyncWorker(config, state, bus, hindsight=mock_hindsight)

        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "id": "mem-sk01",
            "title": "Learn A",
            "learning": "First insight",
            "context": "",
            "memory_type": "knowledge",
            "source": "implementer",
            "reference": "#1",
            "created_at": "2024-01-01T00:00:00Z",
        }
        with items_path.open("w") as f:
            f.write(json.dumps(item) + "\n")

        with patch("hindsight.retain_safe", new_callable=AsyncMock):
            await worker.sync()

        # Digest file should NOT exist — Hindsight is the exclusive memory store
        digest_path = config.data_path("memory", "digest.md")
        assert not digest_path.exists()


# ---------------------------------------------------------------------------
# Dolt backend integration
# ---------------------------------------------------------------------------


class TestMemorySyncWorkerDolt:
    """Tests for MemorySyncWorker ADR source tracking with Dolt backend."""

    def test_load_adr_source_ids_uses_dolt(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        dolt = MagicMock()
        dolt.get_dedup_set.return_value = {"10", "20", "30"}
        worker = MemorySyncWorker(config, MagicMock(), MagicMock(), dolt=dolt)
        result = worker._load_adr_source_ids()
        assert result == {10, 20, 30}
        dolt.get_dedup_set.assert_called_once_with("adr_sources")

    def test_save_adr_source_ids_uses_dolt(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        dolt = MagicMock()
        worker = MemorySyncWorker(config, MagicMock(), MagicMock(), dolt=dolt)
        worker._save_adr_source_ids({10, 20})
        dolt.set_dedup_set.assert_called_once_with("adr_sources", {"10", "20"})
        # File should NOT be written
        path = config.data_path("memory", "adr_sources.json")
        assert not path.exists()

    def test_file_fallback_when_dolt_is_none(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        worker = MemorySyncWorker(config, MagicMock(), MagicMock(), dolt=None)
        assert worker._load_adr_source_ids() == set()
        worker._save_adr_source_ids({5, 15})
        assert worker._load_adr_source_ids() == {5, 15}
        # File SHOULD be written
        path = config.data_path("memory", "adr_sources.json")
        assert path.exists()
