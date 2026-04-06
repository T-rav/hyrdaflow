"""End-to-end memory lifecycle integration tests.

Covers four categories from issue #6043:
1. Retain → recall → inject cycle
2. Cross-phase memory threading
3. Degradation when Hindsight is unavailable
4. Memory quality (dedup, contradictions)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import ConfigFactory, MemoryHarness  # noqa: I001, E402


# ---------------------------------------------------------------------------
# 1. Retain → Recall → Inject cycle
# ---------------------------------------------------------------------------


class TestRetainRecallInjectCycle:
    """Full lifecycle: retain a memory → recall it → verify it in prompt."""

    @pytest.mark.asyncio
    async def test_retained_memory_appears_in_injected_prompt(
        self, tmp_path: Path
    ) -> None:
        """Retain a learning, mock recall to return it, verify it appears in prompt."""
        from hindsight_types import Bank, HindsightMemory

        harness = MemoryHarness(tmp_path)
        harness.set_bank_responses(
            {
                str(Bank.LEARNINGS): [
                    HindsightMemory(text="Always run lint before committing")
                ],
            }
        )

        runner = harness.make_runner()

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=harness.recall_side_effect,
        ):
            memory_sec = await runner._inject_memory(
                query_context="Fix linting issue in config.py"
            )

        assert "## Accumulated Learnings" in memory_sec
        assert "Always run lint before committing" in memory_sec

    @pytest.mark.asyncio
    async def test_context_stats_populated_after_injection(
        self, tmp_path: Path
    ) -> None:
        """After injection, _last_context_stats reflects memory was injected."""
        from hindsight_types import Bank, HindsightMemory

        harness = MemoryHarness(tmp_path)
        harness.set_bank_responses(
            {
                str(Bank.LEARNINGS): [
                    HindsightMemory(text="Use async patterns for I/O")
                ],
            }
        )

        runner = harness.make_runner()

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=harness.recall_side_effect,
        ):
            await runner._inject_memory(query_context="Async issue")

        stats = runner._last_context_stats
        assert stats["context_chars_after"] > 0
        assert stats["context_chars_before"] > 0

    @pytest.mark.asyncio
    async def test_retain_safe_buffers_to_wal_on_failure(self, tmp_path: Path) -> None:
        """When retain fails, WAL captures the entry for later replay."""
        from hindsight import retain_safe
        from hindsight_types import Bank
        from hindsight_wal import HindsightWAL

        mock_client = MagicMock()
        mock_client.retain = AsyncMock(side_effect=RuntimeError("network down"))
        wal = HindsightWAL(tmp_path / "wal" / "test.jsonl")

        await retain_safe(
            mock_client,
            Bank.LEARNINGS,
            "Important learning",
            context="test context",
            wal=wal,
        )

        assert wal.count == 1
        entries = wal.load()
        assert entries[0].content == "Important learning"
        assert entries[0].bank == str(Bank.LEARNINGS)

    @pytest.mark.asyncio
    async def test_multi_bank_recall_assembles_all_sections(
        self, tmp_path: Path
    ) -> None:
        """All five banks are recalled and appear in priority order."""
        from hindsight_types import Bank, HindsightMemory

        harness = MemoryHarness(tmp_path)
        harness.set_bank_responses(
            {
                str(Bank.LEARNINGS): [HindsightMemory(text="LEARN_A")],
                str(Bank.TROUBLESHOOTING): [HindsightMemory(text="TROUBLE_B")],
                str(Bank.RETROSPECTIVES): [HindsightMemory(text="RETRO_C")],
                str(Bank.REVIEW_INSIGHTS): [HindsightMemory(text="REVIEW_D")],
                str(Bank.HARNESS_INSIGHTS): [HindsightMemory(text="HARNESS_E")],
            }
        )

        runner = harness.make_runner()

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=harness.recall_side_effect,
        ):
            memory_sec = await runner._inject_memory(query_context="all banks test")

        assert "## Accumulated Learnings" in memory_sec
        assert "LEARN_A" in memory_sec
        assert "## Known Troubleshooting Patterns" in memory_sec
        assert "TROUBLE_B" in memory_sec
        assert "## Past Retrospectives" in memory_sec
        assert "RETRO_C" in memory_sec
        assert "## Common Review Patterns" in memory_sec
        assert "REVIEW_D" in memory_sec
        assert "## Known Pipeline Patterns" in memory_sec
        assert "HARNESS_E" in memory_sec

        # Verify priority order
        learn_pos = memory_sec.index("LEARN_A")
        trouble_pos = memory_sec.index("TROUBLE_B")
        retro_pos = memory_sec.index("RETRO_C")
        review_pos = memory_sec.index("REVIEW_D")
        harness_pos = memory_sec.index("HARNESS_E")
        assert learn_pos < trouble_pos < retro_pos < review_pos < harness_pos


# ---------------------------------------------------------------------------
# 2. Cross-phase memory threading
# ---------------------------------------------------------------------------


class TestCrossPhaseMemoryThreading:
    """Verify memory flows between phases (planner → implementer)."""

    @pytest.mark.asyncio
    async def test_file_memory_suggestion_stores_to_jsonl(self, tmp_path: Path) -> None:
        """file_memory_suggestion parses transcript and writes to local JSONL."""
        from memory import file_memory_suggestion

        config = ConfigFactory.create(repo_root=tmp_path / "repo")

        transcript = (
            "Some output\n"
            "MEMORY_SUGGESTION_START\n"
            "title: Use bulk inserts for batch ops\n"
            "type: knowledge\n"
            "learning: Bulk inserts are 10x faster than individual inserts\n"
            "context: issue #100 implementation\n"
            "MEMORY_SUGGESTION_END\n"
            "More output"
        )

        await file_memory_suggestion(
            transcript,
            source="agent",
            reference="issue #100",
            config=config,
        )

        items_path = config.data_path("memory", "items.jsonl")
        assert items_path.exists()
        lines = items_path.read_text().strip().splitlines()
        assert len(lines) == 1
        item = json.loads(lines[0])
        assert item["title"] == "Use bulk inserts for batch ops"
        assert item["learning"] == "Bulk inserts are 10x faster than individual inserts"
        assert item["memory_type"] == "knowledge"

    @pytest.mark.asyncio
    async def test_stored_memory_is_recallable_by_next_phase(
        self, tmp_path: Path
    ) -> None:
        """Memory stored by one phase can be recalled and injected by the next."""
        from hindsight_types import Bank, HindsightMemory
        from memory import file_memory_suggestion

        config = ConfigFactory.create(repo_root=tmp_path / "repo")

        # Phase 1: Planner produces a memory suggestion
        transcript = (
            "MEMORY_SUGGESTION_START\n"
            "title: Config validation pattern\n"
            "type: knowledge\n"
            "learning: Always validate config before starting workers\n"
            "context: planning for issue #200\n"
            "MEMORY_SUGGESTION_END\n"
        )
        await file_memory_suggestion(
            transcript, source="planner", reference="issue #200", config=config
        )

        # Verify it was stored
        items_path = config.data_path("memory", "items.jsonl")
        stored = json.loads(items_path.read_text().strip())
        assert stored["learning"] == "Always validate config before starting workers"

        # Phase 2: Implementer recalls the memory — seed mock from Phase 1's stored
        # output so the test verifies the storage→recall connection end-to-end.
        harness = MemoryHarness(tmp_path)
        harness.set_bank_responses(
            {
                str(Bank.LEARNINGS): [HindsightMemory(text=stored["learning"])],
            }
        )

        runner = harness.make_runner()

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=harness.recall_side_effect,
        ):
            memory_sec = await runner._inject_memory(
                query_context="Implement config validation for issue #200"
            )

        assert "Always validate config before starting workers" in memory_sec

    @pytest.mark.asyncio
    async def test_multiple_suggestions_accumulate_in_jsonl(
        self, tmp_path: Path
    ) -> None:
        """Multiple memory suggestions from successive phases accumulate."""
        from memory import file_memory_suggestion

        config = ConfigFactory.create(repo_root=tmp_path / "repo")

        for i in range(3):
            transcript = (
                f"MEMORY_SUGGESTION_START\n"
                f"title: Learning {i}\n"
                f"type: knowledge\n"
                f"learning: Insight number {i}\n"
                f"context: phase {i}\n"
                f"MEMORY_SUGGESTION_END\n"
            )
            await file_memory_suggestion(
                transcript, source=f"phase-{i}", reference=f"issue #{i}", config=config
            )

        items_path = config.data_path("memory", "items.jsonl")
        lines = items_path.read_text().strip().splitlines()
        assert len(lines) == 3
        for i, line in enumerate(lines):
            item = json.loads(line)
            assert item["title"] == f"Learning {i}"


# ---------------------------------------------------------------------------
# 3. Degradation when Hindsight is unavailable
# ---------------------------------------------------------------------------


class TestDegradationWithoutHindsight:
    """Agents must still run when Hindsight is down or unavailable."""

    @pytest.mark.asyncio
    async def test_inject_memory_returns_empty_without_client(
        self, tmp_path: Path
    ) -> None:
        """Without a Hindsight client, memory injection returns empty string."""
        harness = MemoryHarness(tmp_path)
        runner = harness.make_runner_without_hindsight()

        memory_sec = await runner._inject_memory(query_context="Some issue context")

        assert memory_sec == ""

    @pytest.mark.asyncio
    async def test_inject_memory_returns_empty_with_empty_query(
        self, tmp_path: Path
    ) -> None:
        """Even with a client, empty query skips recall entirely."""
        harness = MemoryHarness(tmp_path)
        runner = harness.make_runner()

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
        ) as mock_recall:
            memory_sec = await runner._inject_memory(query_context="")

        mock_recall.assert_not_called()
        assert memory_sec == ""

    @pytest.mark.asyncio
    async def test_recall_failure_returns_empty_gracefully(
        self, tmp_path: Path
    ) -> None:
        """When all recall_safe calls raise, memory is empty but no exception."""
        harness = MemoryHarness(tmp_path)
        runner = harness.make_runner()

        async def _all_fail(_client, _bank, _query, **_kw):
            raise RuntimeError("Hindsight is down")

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=_all_fail,
        ):
            memory_sec = await runner._inject_memory(query_context="Should not crash")

        # Memory section is empty but no exception propagated
        assert "## Accumulated Learnings" not in memory_sec

    @pytest.mark.asyncio
    async def test_partial_bank_failure_preserves_healthy_banks(
        self, tmp_path: Path
    ) -> None:
        """One bank failing doesn't affect other banks' results."""
        from hindsight_types import Bank, HindsightMemory

        harness = MemoryHarness(tmp_path)
        runner = harness.make_runner()

        async def _partial_fail(_client, bank, _query, **_kw):
            if bank == Bank.TROUBLESHOOTING:
                raise RuntimeError("this bank is down")
            if bank == Bank.LEARNINGS:
                return [HindsightMemory(text="Healthy learning")]
            return []

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=_partial_fail,
        ):
            memory_sec = await runner._inject_memory(
                query_context="Partial failure test"
            )

        assert "Healthy learning" in memory_sec
        assert "## Known Troubleshooting Patterns" not in memory_sec

    @pytest.mark.asyncio
    async def test_wal_replay_retries_failed_entries(self, tmp_path: Path) -> None:
        """WAL entries are replayed when Hindsight becomes available again."""
        from hindsight_types import WALEntry
        from hindsight_wal import HindsightWAL

        wal = HindsightWAL(tmp_path / "wal" / "replay.jsonl")

        # Simulate buffered entries from a previous outage
        wal.append(WALEntry(bank="hydraflow-learnings", content="Buffered item 1"))
        wal.append(WALEntry(bank="hydraflow-learnings", content="Buffered item 2"))
        assert wal.count == 2

        # Hindsight comes back online
        mock_client = MagicMock()
        mock_client.retain = AsyncMock(return_value={})

        stats = await wal.replay(mock_client)

        assert stats["replayed"] == 2
        assert stats["failed"] == 0
        assert wal.count == 0

    @pytest.mark.asyncio
    async def test_wal_replay_drops_after_max_retries(self, tmp_path: Path) -> None:
        """WAL entries are dropped after exceeding max_retries."""
        from hindsight_types import WALEntry
        from hindsight_wal import HindsightWAL

        wal = HindsightWAL(tmp_path / "wal" / "drop.jsonl", max_retries=2)

        # Entry already at retry limit
        wal.append(WALEntry(bank="hydraflow-learnings", content="Old item", retries=1))
        assert wal.count == 1

        mock_client = MagicMock()
        mock_client.retain = AsyncMock(side_effect=RuntimeError("still down"))

        stats = await wal.replay(mock_client)

        # retries=1 + 1 = 2 >= max_retries=2, so it's dropped
        assert stats["dropped"] == 1
        assert stats["replayed"] == 0
        assert wal.count == 0

    @pytest.mark.asyncio
    async def test_retain_safe_noop_when_client_is_none(self) -> None:
        """retain_safe is a no-op when client is None."""
        from hindsight import retain_safe
        from hindsight_types import Bank

        # Should not raise
        await retain_safe(None, Bank.LEARNINGS, "some content")

    @pytest.mark.asyncio
    async def test_recall_safe_returns_empty_when_client_is_none(self) -> None:
        """recall_safe returns empty list when client is None."""
        from hindsight import recall_safe
        from hindsight_types import Bank

        result = await recall_safe(None, Bank.LEARNINGS, "query")
        assert result == []


# ---------------------------------------------------------------------------
# 4. Memory quality (dedup, contradictions)
# ---------------------------------------------------------------------------


class TestMemoryQuality:
    """Dedup removes actual duplicates; contradictions are both preserved."""

    @pytest.mark.asyncio
    async def test_duplicate_memories_are_deduped(self, tmp_path: Path) -> None:
        """Duplicate memories across banks trigger dedup (keyword overlap >70%)."""
        from hindsight_types import Bank, HindsightMemory

        harness = MemoryHarness(tmp_path)
        # Same content in two different banks — dedup removes at the
        # all-items level, but per-bank rebuild uses set membership so
        # identical strings survive in both bank sections. The dedup
        # stats still reflect that the duplicate was detected.
        harness.set_bank_responses(
            {
                str(Bank.LEARNINGS): [
                    HindsightMemory(
                        text="Always run lint before committing code changes"
                    )
                ],
                str(Bank.REVIEW_INSIGHTS): [
                    HindsightMemory(
                        text="Always run lint before committing code changes"
                    )
                ],
            }
        )

        runner = harness.make_runner()

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=harness.recall_side_effect,
        ):
            await runner._inject_memory(query_context="lint check")

        # Dedup stats should show items were detected as duplicates
        stats = runner._last_context_stats
        assert stats["dedup_items_removed"] >= 1
        assert stats["dedup_chars_saved"] > 0

    @pytest.mark.asyncio
    async def test_contradictory_memories_both_preserved(self, tmp_path: Path) -> None:
        """Similar-but-different (contradictory) memories are both kept."""
        from hindsight_types import Bank, HindsightMemory

        harness = MemoryHarness(tmp_path)
        harness.set_bank_responses(
            {
                str(Bank.LEARNINGS): [
                    HindsightMemory(
                        text="Prefer PostgreSQL for transactional workloads"
                    )
                ],
                str(Bank.REVIEW_INSIGHTS): [
                    HindsightMemory(text="Prefer SQLite for lightweight test databases")
                ],
            }
        )

        runner = harness.make_runner()

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=harness.recall_side_effect,
        ):
            memory_sec = await runner._inject_memory(query_context="database selection")

        assert "Prefer PostgreSQL for transactional workloads" in memory_sec
        assert "Prefer SQLite for lightweight test databases" in memory_sec

    @pytest.mark.asyncio
    async def test_empty_bank_recall_produces_no_section(self, tmp_path: Path) -> None:
        """Banks that return empty results don't produce section headers."""
        from hindsight_types import Bank, HindsightMemory

        harness = MemoryHarness(tmp_path)
        harness.set_bank_responses(
            {
                str(Bank.LEARNINGS): [HindsightMemory(text="One learning")],
                # All other banks return []
            }
        )

        runner = harness.make_runner()

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=harness.recall_side_effect,
        ):
            memory_sec = await runner._inject_memory(query_context="selective recall")

        assert "## Accumulated Learnings" in memory_sec
        assert "## Known Troubleshooting Patterns" not in memory_sec
        assert "## Past Retrospectives" not in memory_sec
        assert "## Common Review Patterns" not in memory_sec
        assert "## Known Pipeline Patterns" not in memory_sec

    @pytest.mark.asyncio
    async def test_memory_section_respects_max_chars_cap(self, tmp_path: Path) -> None:
        """Combined memory section is capped at max_memory_prompt_chars."""
        from hindsight_types import Bank, HindsightMemory

        harness = MemoryHarness(tmp_path)
        harness.config.max_memory_prompt_chars = 100

        big_text = "X" * 500
        harness.set_bank_responses(
            {
                str(Bank.LEARNINGS): [HindsightMemory(text=big_text)],
            }
        )

        runner = harness.make_runner()

        with patch(
            "hindsight.recall_safe",
            new_callable=AsyncMock,
            side_effect=harness.recall_side_effect,
        ):
            memory_sec = await runner._inject_memory(query_context="big memory test")

        # +2 for leading "\n\n" prefix prepended by _inject_memory
        assert len(memory_sec) <= harness.config.max_memory_prompt_chars + 2

    def test_format_memories_with_context(self) -> None:
        """format_memories_as_markdown includes context when present."""
        from hindsight import format_memories_as_markdown
        from hindsight_types import HindsightMemory

        memories = [
            HindsightMemory(
                text="Check import paths",
                context="Discovered during issue #42 debugging",
            ),
            HindsightMemory(text="Use async patterns"),
        ]

        result = format_memories_as_markdown(memories)

        assert "- Check import paths" in result
        assert "_Context: Discovered during issue #42 debugging_" in result
        assert "- Use async patterns" in result

    def test_format_memories_empty_list(self) -> None:
        """format_memories_as_markdown returns empty string for empty list."""
        from hindsight import format_memories_as_markdown

        assert format_memories_as_markdown([]) == ""

    @pytest.mark.asyncio
    async def test_schedule_retain_fires_task(self) -> None:
        """schedule_retain creates an asyncio task for retain_safe."""
        from hindsight import schedule_retain
        from hindsight_types import Bank

        mock_client = MagicMock()

        with patch("hindsight.retain_safe", new_callable=AsyncMock) as mock_retain:
            schedule_retain(
                mock_client,
                Bank.LEARNINGS,
                "Scheduled learning",
                context="test",
            )
            # Yield control so the task runs
            await asyncio.sleep(0)

        mock_retain.assert_called_once_with(
            mock_client,
            Bank.LEARNINGS,
            "Scheduled learning",
            context="test",
            metadata=None,
            wal=None,
        )

    @pytest.mark.asyncio
    async def test_schedule_retain_noop_without_client(self) -> None:
        """schedule_retain is a no-op when client is None."""
        from hindsight import schedule_retain
        from hindsight_types import Bank

        with patch("hindsight.retain_safe", new_callable=AsyncMock) as mock_retain:
            schedule_retain(None, Bank.LEARNINGS, "content")
            await asyncio.sleep(0)

        mock_retain.assert_not_called()
