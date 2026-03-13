"""Tests for the memory digest system."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from labels import Label
from memory import (
    MemorySyncWorker,
    _parse_memory_type,
    build_memory_issue_body,
    file_memory_suggestion,
    parse_memory_suggestion,
)
from models import MEMORY_TYPE_DISPLAY_ORDER, ManifestRefreshResult, MemoryType
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


class TestParseMemoryType:
    """Tests for _parse_memory_type normalisation."""

    def test_parse_memory_type__knowledge(self) -> None:
        assert _parse_memory_type("knowledge") == MemoryType.KNOWLEDGE

    def test_parse_memory_type__config(self) -> None:
        assert _parse_memory_type("config") == MemoryType.CONFIG

    def test_parse_memory_type__instruction(self) -> None:
        assert _parse_memory_type("instruction") == MemoryType.INSTRUCTION

    def test_parse_memory_type__code(self) -> None:
        assert _parse_memory_type("code") == MemoryType.CODE

    def test_parse_memory_type__case_insensitive(self) -> None:
        assert _parse_memory_type("CONFIG") == MemoryType.CONFIG
        assert _parse_memory_type("Knowledge") == MemoryType.KNOWLEDGE
        assert _parse_memory_type("CODE") == MemoryType.CODE

    def test_parse_memory_type__with_whitespace(self) -> None:
        assert _parse_memory_type("  config  ") == MemoryType.CONFIG

    def test_parse_memory_type__empty_defaults_to_knowledge(self) -> None:
        assert _parse_memory_type("") == MemoryType.KNOWLEDGE

    def test_parse_memory_type__unknown_defaults_to_knowledge(self) -> None:
        assert _parse_memory_type("banana") == MemoryType.KNOWLEDGE
        assert _parse_memory_type("foobar") == MemoryType.KNOWLEDGE


class TestParseMemorySuggestionType:
    """Tests for type field parsing in MEMORY_SUGGESTION blocks."""

    def test_parse_memory_suggestion__type_knowledge(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Test\n"
            "type: knowledge\n"
            "learning: A learning\n"
            "context: ctx\n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is not None
        assert result["type"] == "knowledge"

    def test_parse_memory_suggestion__type_config(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Test\n"
            "type: config\n"
            "learning: A config suggestion\n"
            "context: ctx\n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is not None
        assert result["type"] == "config"

    def test_parse_memory_suggestion__type_instruction(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Test\n"
            "type: instruction\n"
            "learning: An instruction\n"
            "context: ctx\n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is not None
        assert result["type"] == "instruction"

    def test_parse_memory_suggestion__type_code(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Test\n"
            "type: code\n"
            "learning: A code suggestion\n"
            "context: ctx\n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is not None
        assert result["type"] == "code"

    def test_parse_memory_suggestion__missing_type_defaults_to_knowledge(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Test\n"
            "learning: A learning\n"
            "context: ctx\n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is not None
        assert result["type"] == "knowledge"

    def test_parse_memory_suggestion__invalid_type_defaults_to_knowledge(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Test\n"
            "type: banana\n"
            "learning: A learning\n"
            "context: ctx\n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is not None
        assert result["type"] == "knowledge"

    def test_parse_memory_suggestion__empty_type_defaults_to_knowledge(self) -> None:
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Test\n"
            "type: \n"
            "learning: A learning\n"
            "context: ctx\n"
            "MEMORY_SUGGESTION_END\n"
        )
        result = parse_memory_suggestion(transcript)
        assert result is not None
        assert result["type"] == "knowledge"


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

        worker = MemorySyncWorker(config, state, bus, AsyncMock())
        stats = await worker.sync([])

        assert stats["item_count"] == 0
        state.update_memory_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_builds_digest_from_issues(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        worker = MemorySyncWorker(config, state, bus, AsyncMock())
        issues = [
            {
                "number": 10,
                "title": "[Memory] Test learning",
                "body": "## Memory Suggestion\n\n**Learning:** Always test first\n\n**Context:** Found in testing",
                "createdAt": "2024-06-01T00:00:00Z",
            },
            {
                "number": 20,
                "title": "[Memory] Another learning",
                "body": "## Memory Suggestion\n\n**Learning:** Use type hints\n\n**Context:** Code review",
                "createdAt": "2024-05-01T00:00:00Z",
            },
        ]
        stats = await worker.sync(issues)

        assert stats["item_count"] == 2
        assert stats["action"] == "synced"

    @pytest.mark.asyncio
    async def test_skips_compaction_when_no_change(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([10, 20], "somehash", "2024-06-01")
        bus = MagicMock()

        worker = MemorySyncWorker(config, state, bus, AsyncMock())
        issues = [
            {"number": 10, "title": "A", "body": "B", "createdAt": ""},
            {"number": 20, "title": "C", "body": "D", "createdAt": ""},
        ]
        stats = await worker.sync(issues)

        assert stats["compacted"] is False
        assert stats["item_count"] == 2

    @pytest.mark.asyncio
    async def test_detects_new_issues_and_rebuilds(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([10], "oldhash", "2024-05-01")
        bus = MagicMock()

        worker = MemorySyncWorker(config, state, bus, AsyncMock())
        issues = [
            {
                "number": 10,
                "title": "A",
                "body": "**Learning:** Old thing",
                "createdAt": "2024-05-01",
            },
            {
                "number": 30,
                "title": "B",
                "body": "**Learning:** New thing",
                "createdAt": "2024-06-01",
            },
        ]
        stats = await worker.sync(issues)

        assert stats["item_count"] == 2
        # State should be updated with new IDs
        state.update_memory_state.assert_called()
        call_args = state.update_memory_state.call_args
        assert 30 in call_args[0][0]

    @pytest.mark.asyncio
    async def test_updates_state(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        worker = MemorySyncWorker(config, state, bus, AsyncMock())
        issues = [
            {
                "number": 5,
                "title": "T",
                "body": "**Learning:** Something",
                "createdAt": "",
            },
        ]
        await worker.sync(issues)

        state.update_memory_state.assert_called()
        call_args = state.update_memory_state.call_args[0]
        assert call_args[0] == [5]  # issue IDs
        assert isinstance(call_args[1], str)  # digest hash

    @pytest.mark.asyncio
    async def test_sync_auto_closes_processed_memory_issues(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        prs = MagicMock()
        prs.close_issue = AsyncMock()
        prs.create_issue = AsyncMock(return_value=0)

        worker = MemorySyncWorker(config, state, bus, AsyncMock(), prs=prs)
        issues = [
            {
                "number": 5,
                "title": "[Memory] T",
                "body": "**Learning:** Something",
                "createdAt": "",
                "labels": ["hydraflow-memory"],
            },
            {
                "number": 6,
                "title": "[Memory] U",
                "body": "**Learning:** Else",
                "createdAt": "",
                "labels": ["hydraflow-memory"],
            },
        ]
        await worker.sync(issues)

        assert prs.close_issue.await_count == 2
        prs.close_issue.assert_any_await(5)
        prs.close_issue.assert_any_await(6)

    @pytest.mark.asyncio
    async def test_sync_close_issue_failure_does_not_fail_sync(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        prs = MagicMock()
        prs.close_issue = AsyncMock(side_effect=RuntimeError("close failed"))
        prs.create_issue = AsyncMock(return_value=0)

        worker = MemorySyncWorker(config, state, bus, AsyncMock(), prs=prs)
        issues = [
            {
                "number": 5,
                "title": "[Memory] T",
                "body": "**Learning:** Something",
                "createdAt": "",
                "labels": ["hydraflow-memory"],
            },
        ]
        stats = await worker.sync(issues)

        assert stats["item_count"] == 1
        prs.close_issue.assert_awaited_once_with(5)

    @pytest.mark.asyncio
    async def test_sync_does_not_close_non_memory_style_issues(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        prs = MagicMock()
        prs.close_issue = AsyncMock()
        prs.create_issue = AsyncMock(return_value=0)

        worker = MemorySyncWorker(config, state, bus, AsyncMock(), prs=prs)
        issues = [
            {
                "number": 5,
                "title": "Feature issue that mentions memory",
                "body": "**Learning:** Something",
                "createdAt": "",
                "labels": ["hydraflow-memory"],
            },
            {
                "number": 6,
                "title": "[Memory] Missing memory label",
                "body": "**Learning:** Else",
                "createdAt": "",
                "labels": ["hydraflow-plan"],
            },
        ]
        stats = await worker.sync(issues)

        assert stats["item_count"] == 2
        prs.close_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_routes_architecture_memory_to_adr_task(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        prs = MagicMock()
        prs.close_issue = AsyncMock()
        prs.create_issue = AsyncMock(return_value=101)

        worker = MemorySyncWorker(config, state, bus, AsyncMock(), prs=prs)
        issues = [
            {
                "number": 5,
                "title": "[Memory] Shift to event-driven architecture",
                "body": (
                    "## Memory Suggestion\n\n"
                    "**Type:** knowledge\n\n"
                    "**Learning:** We shifted service boundaries and queue topology.\n\n"
                    "**Context:** Runtime scaling bottleneck.\n"
                ),
                "createdAt": "",
                "labels": ["hydraflow-memory"],
            },
        ]
        await worker.sync(issues)

        prs.create_issue.assert_awaited_once()
        args = prs.create_issue.call_args[0]
        assert args[0].startswith("[ADR] Draft decision from memory #5:")
        assert "## Decision" in args[1]
        assert "<Chosen architecture/workflow shift>" not in args[1]
        assert args[2] == [Label.FIND]

    @pytest.mark.asyncio
    async def test_sync_rejects_invalid_adr_candidate_and_deduplicates(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        prs = MagicMock()
        prs.close_issue = AsyncMock()
        prs.create_issue = AsyncMock(return_value=101)

        worker = MemorySyncWorker(config, state, bus, AsyncMock(), prs=prs)
        worker._build_adr_task = MagicMock(  # type: ignore[method-assign]
            return_value=(
                "[ADR] Draft decision from memory #5: bad",
                "## ADR Draft Task\n\n## Context\nShort.\n\n## Decision\nNope.\n",
            )
        )
        issue = {
            "number": 5,
            "title": "[Memory] Architecture update",
            "body": (
                "## Memory Suggestion\n\n"
                "**Learning:** Architecture decision changed worker topology.\n"
            ),
            "createdAt": "",
            "labels": ["hydraflow-memory"],
        }

        await worker.sync([issue])
        await worker.sync([issue])

        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_adr_routing_deduplicates_by_source_issue(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        prs = MagicMock()
        prs.close_issue = AsyncMock()
        prs.create_issue = AsyncMock(return_value=101)

        worker = MemorySyncWorker(config, state, bus, AsyncMock(), prs=prs)
        issue = {
            "number": 5,
            "title": "[Memory] Architecture update",
            "body": (
                "## Memory Suggestion\n\n"
                "**Learning:** Architecture decision changed worker topology.\n"
            ),
            "createdAt": "",
            "labels": ["hydraflow-memory"],
        }
        await worker.sync([issue])
        await worker.sync([issue])

        assert prs.create_issue.await_count == 1

    @pytest.mark.asyncio
    async def test_sync_adr_deduplicates_by_topic_content(self, tmp_path: Path) -> None:
        """Two memory issues about the same topic should only create one ADR issue."""
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        prs = MagicMock()
        prs.close_issue = AsyncMock()
        prs.create_issue = AsyncMock(return_value=101)

        worker = MemorySyncWorker(config, state, bus, AsyncMock(), prs=prs)
        issues = [
            {
                "number": 10,
                "title": "[Memory] ADR test policy — only structural tests allowed",
                "body": (
                    "## Memory Suggestion\n\n"
                    "**Learning:** Architecture decision: ADR tests structural only.\n"
                ),
                "createdAt": "",
                "labels": ["hydraflow-memory"],
            },
            {
                "number": 11,
                "title": "[Memory] ADR test policy — only structural tests allowed",
                "body": (
                    "## Memory Suggestion\n\n"
                    "**Learning:** Architecture decision: ADR tests structural only.\n"
                ),
                "createdAt": "",
                "labels": ["hydraflow-memory"],
            },
        ]
        await worker.sync(issues)

        assert prs.create_issue.await_count == 1

    @pytest.mark.asyncio
    async def test_sync_adr_skips_topic_covered_by_existing_adr_file(
        self, tmp_path: Path
    ) -> None:
        """ADR candidate should be skipped if docs/adr/ already has that topic."""
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-worker-topology.md").write_text("# ADR\n")

        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        prs = MagicMock()
        prs.close_issue = AsyncMock()
        prs.create_issue = AsyncMock(return_value=101)

        worker = MemorySyncWorker(config, state, bus, AsyncMock(), prs=prs)
        issues = [
            {
                "number": 20,
                "title": "[Memory] Worker topology",
                "body": (
                    "## Memory Suggestion\n\n"
                    "**Learning:** Architecture decision about worker topology.\n"
                ),
                "createdAt": "",
                "labels": ["hydraflow-memory"],
            },
        ]
        await worker.sync(issues)

        prs.create_issue.assert_not_called()

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
    async def test_sync_auto_closes_transcript_summary_issues(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        prs = MagicMock()
        prs.close_issue = AsyncMock()

        worker = MemorySyncWorker(config, state, bus, AsyncMock(), prs=prs)
        issues = [
            {
                "number": 11,
                "title": "[Transcript Summary] Issue #42 — review phase",
                "body": "## Transcript Summary\n\n- Insight",
                "createdAt": "",
                "labels": ["hydraflow-transcript"],
            },
        ]
        await worker.sync(issues)

        prs.close_issue.assert_awaited_once_with(11)

    @pytest.mark.asyncio
    async def test_sync_refreshes_manifest_and_syncer(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        manifest_store = MagicMock()
        manifest_manager = MagicMock()
        manifest_manager.refresh.return_value = ManifestRefreshResult(
            "## Base", "abc123"
        )
        manifest_syncer = MagicMock()
        manifest_syncer.sync = AsyncMock()

        worker = MemorySyncWorker(
            config,
            state,
            bus,
            AsyncMock(),
            manifest_store=manifest_store,
            manifest_manager=manifest_manager,
            manifest_syncer=manifest_syncer,
        )
        issues = [
            {
                "number": 1,
                "title": "A",
                "body": "## Memory Suggestion\n\n**Learning:** Use make prep\n\n**Type:** knowledge",
                "createdAt": "2024-06-01T00:00:00Z",
            }
        ]

        await worker.sync(issues)

        manifest_store.update_from_learnings.assert_called_once()
        manifest_manager.refresh.assert_called_once()
        manifest_syncer.sync.assert_awaited_once_with(
            "## Base", "abc123", source="memory-sync"
        )
        state.update_manifest_state.assert_called_with("abc123")

    @pytest.mark.asyncio
    async def test_publish_sync_event(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        bus = MagicMock()
        bus.publish = AsyncMock()

        worker = MemorySyncWorker(config, state, bus, AsyncMock())
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
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()

        worker = MemorySyncWorker(config, state, bus, AsyncMock())

        issues_a = [
            {
                "number": 10,
                "title": "A",
                "body": "**Learning:** First learning",
                "createdAt": "2024-06-01",
            },
        ]
        issues_b = [
            {
                "number": 20,
                "title": "B",
                "body": "**Learning:** Second learning",
                "createdAt": "2024-06-02",
            },
        ]

        results = await asyncio.gather(
            worker.sync(issues_a),
            worker.sync(issues_b),
            return_exceptions=True,
        )

        # Both calls should complete without raising
        for r in results:
            assert not isinstance(r, Exception), f"sync() raised: {r}"

    @pytest.mark.asyncio
    async def test_sync_returns_issues_closed_count(self, tmp_path: Path) -> None:
        """Sync result should include issues_closed count."""
        config = ConfigFactory.create(repo_root=tmp_path)
        state = MagicMock()
        state.get_memory_state.return_value = ([], "", None)
        bus = MagicMock()
        prs = AsyncMock()
        prs.close_issue = AsyncMock()

        worker = MemorySyncWorker(config, state, bus, AsyncMock(), prs=prs)
        issues = [
            {
                "number": 10,
                "title": "[Memory] Test",
                "body": "## Memory Suggestion\n\n**Learning:** Test\n\n**Context:** Test",
                "createdAt": "",
                "labels": ["hydraflow-memory"],
            },
        ]
        stats = await worker.sync(issues)

        assert stats["issues_closed"] == 1
        prs.close_issue.assert_awaited_once_with(10)


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

    def test_memory_auto_approve_default_false(self) -> None:
        from config import HydraFlowConfig

        config = HydraFlowConfig(repo="test/repo")
        assert config.memory_auto_approve is False

    def test_memory_auto_approve_explicit_true(self) -> None:
        config = ConfigFactory.create(memory_auto_approve=True)
        assert config.memory_auto_approve is True

    def test_memory_auto_approve_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import HydraFlowConfig

        monkeypatch.setenv("HYDRAFLOW_MEMORY_AUTO_APPROVE", "true")
        config = HydraFlowConfig(repo="test/repo")
        assert config.memory_auto_approve is True

    def test_memory_auto_approve_env_override_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import HydraFlowConfig

        monkeypatch.setenv("HYDRAFLOW_MEMORY_AUTO_APPROVE", "false")
        config = HydraFlowConfig(repo="test/repo")
        assert config.memory_auto_approve is False


# --- Models tests ---


class TestMemoryModels:
    """Tests for memory-related model fields."""

    def test_state_data_memory_fields_default(self) -> None:
        from models import StateData

        data = StateData()
        assert data.memory_issue_ids == []
        assert data.memory_digest_hash == ""
        assert data.memory_last_synced is None

    def test_control_status_config_memory_label(self) -> None:
        from models import ControlStatusConfig

        cfg = ControlStatusConfig(memory_label=["hydraflow-memory"])
        assert cfg.memory_label == ["hydraflow-memory"]

    def test_control_status_config_memory_auto_approve_default(self) -> None:
        from models import ControlStatusConfig

        cfg = ControlStatusConfig()
        assert cfg.memory_auto_approve is False

    def test_control_status_config_memory_auto_approve_true(self) -> None:
        from models import ControlStatusConfig

        cfg = ControlStatusConfig(memory_auto_approve=True)
        assert cfg.memory_auto_approve is True

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
        from models import GitHubIssue

        issue = GitHubIssue(number=1, title="Test")
        assert issue.created_at == ""

    def test_github_issue_created_at_snake_case(self) -> None:
        from models import GitHubIssue

        issue = GitHubIssue(number=1, title="Test", created_at="2024-01-01")
        assert issue.created_at == "2024-01-01"


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


class TestFileSuggestionSetsOrigin:
    """Tests that file_memory_suggestion sets hitl_origin on created issues."""

    @pytest.mark.asyncio
    async def test_file_memory_suggestion_sets_hitl_origin(
        self, tmp_path: Path
    ) -> None:
        """When a knowledge memory suggestion is filed, no HITL state should be set."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=99)

        transcript = (
            "Some output\n"
            "MEMORY_SUGGESTION_START\n"
            "title: Test suggestion\n"
            "learning: Learned something useful\n"
            "context: During testing\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "implementer", "issue #42", config, mock_prs, state
        )

        # Knowledge type: improve label only, no HITL label
        mock_prs.create_issue.assert_awaited_once()
        call_labels = mock_prs.create_issue.call_args.args[2]
        assert Label.IMPROVE in call_labels
        assert Label.HITL not in call_labels

        # No HITL state set for knowledge type
        assert state.get_hitl_origin(99) is None
        assert state.get_hitl_cause(99) is None

    @pytest.mark.asyncio
    async def test_file_memory_suggestion_no_origin_on_failure(
        self, tmp_path: Path
    ) -> None:
        """When create_issue returns 0, no hitl_origin should be set."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=0)

        transcript = (
            "Some output\n"
            "MEMORY_SUGGESTION_START\n"
            "title: Test suggestion\n"
            "learning: Learned something\n"
            "context: During testing\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "implementer", "issue #42", config, mock_prs, state
        )

        # No hitl_origin should be set when create_issue fails
        assert state.get_hitl_origin(0) is None


class TestFileMemorySuggestionRouting:
    """Tests for memory type routing in file_memory_suggestion."""

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__knowledge_type_no_hitl(
        self, tmp_path: Path
    ) -> None:
        """Knowledge type should NOT set HITL state and should use improve label only."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=100)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Knowledge insight\n"
            "type: knowledge\n"
            "learning: A passive insight\n"
            "context: During review\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "reviewer", "PR #10", config, mock_prs, state
        )

        # Knowledge type: no HITL state
        assert state.get_hitl_cause(100) is None
        assert state.get_hitl_origin(100) is None
        # Body should include type
        call_body = mock_prs.create_issue.call_args.args[1]
        assert "**Type:** knowledge" in call_body
        # Labels should be improve only, no hitl
        call_labels = mock_prs.create_issue.call_args.args[2]
        assert Label.IMPROVE in call_labels
        assert Label.HITL not in call_labels

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__config_type_actionable_cause(
        self, tmp_path: Path
    ) -> None:
        """Config type should use actionable cause, HITL routing, and both labels."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=101)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Increase CI timeout\n"
            "type: config\n"
            "learning: CI timeout too low\n"
            "context: During implementation\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "implementer", "issue #5", config, mock_prs, state
        )

        assert state.get_hitl_cause(101) == "Actionable memory suggestion (config)"
        assert state.get_hitl_origin(101) == Label.IMPROVE
        call_body = mock_prs.create_issue.call_args.args[1]
        assert "**Type:** config" in call_body
        # Actionable: both improve and hitl labels
        call_labels = mock_prs.create_issue.call_args.args[2]
        assert Label.IMPROVE in call_labels
        assert Label.HITL in call_labels

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__instruction_type_actionable_cause(
        self, tmp_path: Path
    ) -> None:
        """Instruction type should use actionable cause and both labels."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=102)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Add lint step\n"
            "type: instruction\n"
            "learning: Always lint first\n"
            "context: During review\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "reviewer", "PR #20", config, mock_prs, state
        )

        assert state.get_hitl_cause(102) == "Actionable memory suggestion (instruction)"
        assert state.get_hitl_origin(102) == Label.IMPROVE
        call_labels = mock_prs.create_issue.call_args.args[2]
        assert Label.IMPROVE in call_labels
        assert Label.HITL in call_labels

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__code_type_actionable_cause(
        self, tmp_path: Path
    ) -> None:
        """Code type should use actionable cause and both labels."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=103)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Refactor helper\n"
            "type: code\n"
            "learning: Should refactor shared helper\n"
            "context: During implementation\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "implementer", "issue #30", config, mock_prs, state
        )

        assert state.get_hitl_cause(103) == "Actionable memory suggestion (code)"
        assert state.get_hitl_origin(103) == Label.IMPROVE
        call_labels = mock_prs.create_issue.call_args.args[2]
        assert Label.IMPROVE in call_labels
        assert Label.HITL in call_labels

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__missing_type_defaults_to_knowledge(
        self, tmp_path: Path
    ) -> None:
        """When type is missing, should default to knowledge (no HITL)."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=104)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Some insight\n"
            "learning: Discovered something\n"
            "context: During work\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "implementer", "issue #40", config, mock_prs, state
        )

        # Defaults to knowledge: no HITL state, improve label only
        assert state.get_hitl_cause(104) is None
        assert state.get_hitl_origin(104) is None
        call_labels = mock_prs.create_issue.call_args.args[2]
        assert Label.IMPROVE in call_labels
        assert Label.HITL not in call_labels


class TestFileMemorySuggestionLabelRouting:
    """Tests confirming knowledge types get different labels than actionable types."""

    @staticmethod
    def _make_transcript(memory_type: str) -> str:
        return (
            "MEMORY_SUGGESTION_START\n"
            f"title: Test {memory_type}\n"
            f"type: {memory_type}\n"
            f"learning: A {memory_type} learning\n"
            "context: During testing\n"
            "MEMORY_SUGGESTION_END\n"
        )

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__knowledge_gets_improve_label_only(
        self, tmp_path: Path
    ) -> None:
        """Knowledge type issues receive improve label but NOT hitl label."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=200)

        await file_memory_suggestion(
            self._make_transcript("knowledge"),
            "planner",
            "issue #50",
            config,
            mock_prs,
            state,
        )

        call_labels = mock_prs.create_issue.call_args.args[2]
        assert call_labels == [Label.IMPROVE]
        assert Label.HITL not in call_labels

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__actionable_gets_both_labels(
        self, tmp_path: Path
    ) -> None:
        """Actionable type issues receive both improve and hitl labels."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=201)

        await file_memory_suggestion(
            self._make_transcript("config"),
            "implementer",
            "issue #51",
            config,
            mock_prs,
            state,
        )

        call_labels = mock_prs.create_issue.call_args.args[2]
        expected = [Label.IMPROVE] + [Label.HITL]
        assert call_labels == expected

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__knowledge_vs_actionable_labels_differ(
        self, tmp_path: Path
    ) -> None:
        """Knowledge and actionable types must produce different label sets."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )

        # File a knowledge suggestion
        state_k = StateTracker(tmp_path / "state_k.json")
        mock_prs_k = AsyncMock()
        mock_prs_k.create_issue = AsyncMock(return_value=300)
        await file_memory_suggestion(
            self._make_transcript("knowledge"),
            "planner",
            "issue #60",
            config,
            mock_prs_k,
            state_k,
        )
        knowledge_labels = mock_prs_k.create_issue.call_args.args[2]

        # File an actionable (instruction) suggestion
        state_a = StateTracker(tmp_path / "state_a.json")
        mock_prs_a = AsyncMock()
        mock_prs_a.create_issue = AsyncMock(return_value=301)
        await file_memory_suggestion(
            self._make_transcript("instruction"),
            "implementer",
            "issue #61",
            config,
            mock_prs_a,
            state_a,
        )
        actionable_labels = mock_prs_a.create_issue.call_args.args[2]

        # Labels must differ
        assert knowledge_labels != actionable_labels
        # Knowledge: improve only; actionable: improve + hitl
        assert len(knowledge_labels) < len(actionable_labels)

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__knowledge_no_hitl_state_set(
        self, tmp_path: Path
    ) -> None:
        """Knowledge type must not call set_hitl_origin or set_hitl_cause."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=400)

        await file_memory_suggestion(
            self._make_transcript("knowledge"),
            "reviewer",
            "PR #70",
            config,
            mock_prs,
            state,
        )

        # No HITL state should exist for this issue
        assert state.get_hitl_origin(400) is None
        assert state.get_hitl_cause(400) is None

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__actionable_sets_hitl_state(
        self, tmp_path: Path
    ) -> None:
        """Actionable type must set both hitl_origin and hitl_cause."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=401)

        await file_memory_suggestion(
            self._make_transcript("code"),
            "implementer",
            "issue #71",
            config,
            mock_prs,
            state,
        )

        assert state.get_hitl_origin(401) == Label.IMPROVE
        assert state.get_hitl_cause(401) == "Actionable memory suggestion (code)"


# --- Auto-approve tests ---


class TestFileMemorySuggestionAutoApprove:
    """Tests for file_memory_suggestion with memory_auto_approve enabled."""

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__auto_approve__uses_memory_label(
        self, tmp_path: Path
    ) -> None:
        """When memory_auto_approve is True, issue is created with memory_label only."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            memory_auto_approve=True,
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=77)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Auto-approved learning\n"
            "learning: Tests should run before commits\n"
            "context: During implementation\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "implementer", "issue #10", config, mock_prs, state
        )

        mock_prs.create_issue.assert_awaited_once()
        call_labels = mock_prs.create_issue.call_args.args[2]
        assert Label.MEMORY in call_labels
        assert Label.IMPROVE not in call_labels
        assert Label.HITL not in call_labels

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__auto_approve__skips_hitl_state(
        self, tmp_path: Path
    ) -> None:
        """When memory_auto_approve is True, no hitl_origin or hitl_cause is set."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            memory_auto_approve=True,
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=77)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Auto-approved learning\n"
            "learning: Tests should run before commits\n"
            "context: During implementation\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "implementer", "issue #10", config, mock_prs, state
        )

        # No HITL state should be set for auto-approved suggestions
        assert state.get_hitl_origin(77) is None
        assert state.get_hitl_cause(77) is None

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__auto_approve_false__knowledge_improve_only(
        self, tmp_path: Path
    ) -> None:
        """When auto_approve=False and type is knowledge (default), improve-only flow."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            memory_auto_approve=False,
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=88)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Manual approval learning\n"
            "learning: Review before merge\n"
            "context: During review\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "reviewer", "PR #5", config, mock_prs, state
        )

        call_labels = mock_prs.create_issue.call_args.args[2]
        assert Label.IMPROVE in call_labels
        assert Label.HITL not in call_labels
        assert Label.MEMORY not in call_labels

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__auto_approve__no_suggestion_is_noop(
        self, tmp_path: Path
    ) -> None:
        """When transcript has no suggestion, auto-approve mode is a no-op."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            memory_auto_approve=True,
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=0)

        transcript = "Just regular agent output, no memory block."

        await file_memory_suggestion(
            transcript, "implementer", "issue #10", config, mock_prs, state
        )

        mock_prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__auto_approve__create_issue_failure(
        self, tmp_path: Path
    ) -> None:
        """When auto-approve is on but create_issue returns 0, nothing crashes."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            memory_auto_approve=True,
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=0)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Learning\n"
            "learning: Something\n"
            "context: Somewhere\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "implementer", "issue #10", config, mock_prs, state
        )

        mock_prs.create_issue.assert_awaited_once()
        # No state should be set when issue creation fails
        assert state.get_hitl_origin(0) is None

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__auto_approve__actionable_uses_memory_label(
        self, tmp_path: Path
    ) -> None:
        """Actionable type (config) with auto_approve=True gets memory_label only."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            memory_auto_approve=True,
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=90)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Increase CI timeout\n"
            "type: config\n"
            "learning: CI timeout too low\n"
            "context: During implementation\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "implementer", "issue #5", config, mock_prs, state
        )

        call_labels = mock_prs.create_issue.call_args.args[2]
        assert Label.MEMORY in call_labels
        assert Label.IMPROVE not in call_labels
        assert Label.HITL not in call_labels

    @pytest.mark.asyncio
    async def test_file_memory_suggestion__auto_approve__actionable_skips_hitl_state(
        self, tmp_path: Path
    ) -> None:
        """Instruction type with auto_approve=True sets no HITL state."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            memory_auto_approve=True,
        )
        state = StateTracker(config.state_file)
        mock_prs = AsyncMock()
        mock_prs.create_issue = AsyncMock(return_value=91)

        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Always run lint before push\n"
            "type: instruction\n"
            "learning: Lint catches issues early\n"
            "context: During review\n"
            "MEMORY_SUGGESTION_END\n"
        )

        await file_memory_suggestion(
            transcript, "reviewer", "PR #8", config, mock_prs, state
        )

        assert state.get_hitl_origin(91) is None
        assert state.get_hitl_cause(91) is None


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
