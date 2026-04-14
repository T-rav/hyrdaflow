"""Tests for hindsight_wal.py — write-ahead log for Hindsight retains."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hindsight_wal import HindsightWAL, WALEntry, run_wal_replay_loop

# ---------------------------------------------------------------------------
# WALEntry
# ---------------------------------------------------------------------------


class TestWALEntry:
    """Tests for the WALEntry model."""

    def test_defaults(self) -> None:
        entry = WALEntry(bank="test", content="hello")
        assert entry.bank == "test"
        assert entry.content == "hello"
        assert entry.context == ""
        assert entry.metadata == {}
        assert entry.retries == 0
        assert entry.created_at  # non-empty timestamp

    def test_full_construction(self) -> None:
        entry = WALEntry(
            bank="learnings",
            content="lesson",
            context="CI",
            metadata={"issue": "42"},
            retries=2,
        )
        assert entry.retries == 2
        assert entry.metadata["issue"] == "42"


# ---------------------------------------------------------------------------
# HindsightWAL — file operations
# ---------------------------------------------------------------------------


class TestHindsightWAL:
    """Tests for HindsightWAL file operations."""

    def test_append_creates_file(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="test", content="hello"))
        assert (tmp_path / "wal.jsonl").exists()
        assert wal.count == 1

    def test_append_multiple(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="a", content="one"))
        wal.append(WALEntry(bank="b", content="two"))
        assert wal.count == 2

    def test_load_returns_entries(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="test", content="hello", context="ctx"))
        entries = wal.load()
        assert len(entries) == 1
        assert entries[0].bank == "test"
        assert entries[0].content == "hello"
        assert entries[0].context == "ctx"

    def test_load_empty_file(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        assert wal.load() == []
        assert wal.count == 0

    def test_load_missing_file(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "nonexistent.jsonl")
        assert wal.load() == []

    def test_load_skips_corrupt_lines(self, tmp_path: Path) -> None:
        wal_path = tmp_path / "wal.jsonl"
        wal_path.write_text('{"bank":"a","content":"good"}\nnot json\n')
        wal = HindsightWAL(wal_path)
        entries = wal.load()
        assert len(entries) == 1
        assert entries[0].content == "good"

    def test_clear_empties_wal(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="a", content="one"))
        wal.clear()
        assert wal.count == 0

    def test_write_all_replaces_content(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="old", content="old"))
        new_entries = [WALEntry(bank="new", content="new")]
        wal.write_all(new_entries)
        loaded = wal.load()
        assert len(loaded) == 1
        assert loaded[0].bank == "new"

    def test_trim_drops_oldest(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl", max_entries=3)
        for i in range(5):
            wal.append(WALEntry(bank="b", content=f"entry-{i}"))
        entries = wal.load()
        assert len(entries) == 3
        assert entries[0].content == "entry-2"  # oldest kept
        assert entries[2].content == "entry-4"  # newest


# ---------------------------------------------------------------------------
# HindsightWAL — replay
# ---------------------------------------------------------------------------


class TestWALReplay:
    """Tests for HindsightWAL.replay()."""

    @pytest.mark.asyncio
    async def test_replay_succeeds(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="test", content="hello"))
        wal.append(WALEntry(bank="test", content="world"))

        client = MagicMock()
        client.retain = AsyncMock()

        result = await wal.replay(client)
        assert result["replayed"] == 2
        assert result["failed"] == 0
        assert result["dropped"] == 0
        assert wal.count == 0  # all drained

    @pytest.mark.asyncio
    async def test_replay_retries_on_failure(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl", max_retries=3)
        wal.append(WALEntry(bank="test", content="flaky"))

        client = MagicMock()
        client.retain = AsyncMock(side_effect=RuntimeError("down"))

        result = await wal.replay(client)
        assert result["replayed"] == 0
        assert result["failed"] == 1

        # Entry still in WAL with incremented retry count
        entries = wal.load()
        assert len(entries) == 1
        assert entries[0].retries == 1

    @pytest.mark.asyncio
    async def test_replay_drops_after_max_retries(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl", max_retries=2)
        wal.append(WALEntry(bank="test", content="hopeless", retries=1))

        client = MagicMock()
        client.retain = AsyncMock(side_effect=RuntimeError("permanent"))

        result = await wal.replay(client)
        assert result["dropped"] == 1
        assert result["failed"] == 0
        assert wal.count == 0  # dropped, not retained

    @pytest.mark.asyncio
    async def test_replay_empty_wal_is_noop(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        client = MagicMock()
        result = await wal.replay(client)
        assert result == {"replayed": 0, "failed": 0, "dropped": 0}

    @pytest.mark.asyncio
    async def test_replay_partial_success(self, tmp_path: Path) -> None:
        """First entry succeeds, second fails."""
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="a", content="good"))
        wal.append(WALEntry(bank="b", content="bad"))

        client = MagicMock()
        client.retain = AsyncMock(side_effect=[None, RuntimeError("fail")])

        result = await wal.replay(client)
        assert result["replayed"] == 1
        assert result["failed"] == 1

        remaining = wal.load()
        assert len(remaining) == 1
        assert remaining[0].content == "bad"


# ---------------------------------------------------------------------------
# retain_safe + WAL integration
# ---------------------------------------------------------------------------


class TestRetainSafeWithWAL:
    """Tests that retain_safe buffers to WAL on failure."""

    @pytest.mark.asyncio
    async def test_failed_retain_appends_to_wal(self, tmp_path: Path) -> None:
        from hindsight import retain_safe

        wal = HindsightWAL(tmp_path / "wal.jsonl")
        client = MagicMock()
        client.retain = AsyncMock(side_effect=RuntimeError("down"))

        await retain_safe(
            client,
            "test-bank",
            "important lesson",
            context="CI",
            metadata={"issue": "42"},
            wal=wal,
        )

        entries = wal.load()
        assert len(entries) == 1
        assert entries[0].bank == "test-bank"
        assert entries[0].content == "important lesson"
        assert entries[0].context == "CI"

    @pytest.mark.asyncio
    async def test_successful_retain_does_not_write_wal(self, tmp_path: Path) -> None:
        from hindsight import retain_safe

        wal = HindsightWAL(tmp_path / "wal.jsonl")
        client = MagicMock()
        client.retain = AsyncMock()

        await retain_safe(client, "test-bank", "good", wal=wal)

        assert wal.count == 0

    @pytest.mark.asyncio
    async def test_failed_retain_without_wal_logs_only(self, tmp_path: Path) -> None:
        from hindsight import retain_safe

        client = MagicMock()
        client.retain = AsyncMock(side_effect=RuntimeError("down"))

        # Should not raise, and no WAL to write to
        await retain_safe(client, "test-bank", "lost forever")


# ---------------------------------------------------------------------------
# run_wal_replay_loop
# ---------------------------------------------------------------------------


class TestWALReplayLoop:
    """Tests for the background replay loop."""

    @pytest.mark.asyncio
    async def test_replay_loop_drains_wal(self, tmp_path: Path) -> None:
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="test", content="buffered"))

        client = MagicMock()
        client.retain = AsyncMock()
        stop = asyncio.Event()

        # Run one iteration then stop
        async def run_and_stop() -> None:
            await asyncio.sleep(0.1)
            stop.set()

        await asyncio.gather(
            run_wal_replay_loop(wal, client, stop, interval=1),
            run_and_stop(),
        )

        assert wal.count == 0
        client.retain.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_replay_loop_handles_errors(self, tmp_path: Path) -> None:
        """Loop continues even if replay raises."""
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="test", content="retry"))

        client = MagicMock()
        client.retain = AsyncMock(side_effect=RuntimeError("fail"))
        stop = asyncio.Event()

        async def run_and_stop() -> None:
            await asyncio.sleep(0.1)
            stop.set()

        # Should not raise
        await asyncio.gather(
            run_wal_replay_loop(wal, client, stop, interval=1),
            run_and_stop(),
        )


# ---------------------------------------------------------------------------
# Sentry breadcrumb tests
# ---------------------------------------------------------------------------


class TestWALSentryBreadcrumbs:
    """Sentry breadcrumbs are emitted on WAL append and replay failure."""

    def test_append_adds_breadcrumb(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        wal = HindsightWAL(tmp_path / "wal.jsonl")
        sentry_mock = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": sentry_mock}):
            wal.append(WALEntry(bank="test-bank", content="hello"))
            sentry_mock.add_breadcrumb.assert_called_once()
            kw = sentry_mock.add_breadcrumb.call_args[1]
            assert kw["category"] == "hindsight_wal.buffered"
            assert kw["data"]["bank"] == "test-bank"

    @pytest.mark.asyncio
    async def test_replay_failure_adds_breadcrumb(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="test", content="retry"))

        client = MagicMock()
        client.retain = AsyncMock(side_effect=RuntimeError("fail"))

        sentry_mock = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": sentry_mock}):
            await wal.replay(client)
            sentry_mock.add_breadcrumb.assert_called()
            calls = sentry_mock.add_breadcrumb.call_args_list
            replay_call = [
                c
                for c in calls
                if c[1].get("category") == "hindsight_wal.replay_failed"
            ]
            assert len(replay_call) == 1


# ---------------------------------------------------------------------------
# Concurrency regression — #6142
# ---------------------------------------------------------------------------


class TestConcurrentAppendReplaySafety:
    """Regression tests for issue #6142.

    HindsightWAL file ops (append / _trim / load / write_all) had no locking.
    append() (sync, called from async code) and replay() (async) could race:
    an append between replay's load() and write_all() would be overwritten
    and silently lost. The RLock fix serializes file ops.
    """

    @pytest.mark.asyncio
    async def test_append_during_replay_is_not_lost(self, tmp_path: Path) -> None:
        """An append() racing replay() must survive the write_all that rebuilds the WAL."""
        import threading

        wal = HindsightWAL(tmp_path / "wal.jsonl")
        # Seed with 5 entries that will replay successfully (client.retain stub OK)
        for i in range(5):
            wal.append(WALEntry(bank="seed", content=f"seed-{i}"))
        assert wal.count == 5

        # Gate the replay's retain so we can append mid-flight
        first_retain_seen = threading.Event()
        gate = threading.Event()

        async def _gated_retain(*args: object, **kwargs: object) -> None:
            first_retain_seen.set()
            # Hold the replay in-progress until the appender has had time
            # to race us; gate.wait is blocking so we let the event loop
            # handle the appender thread via asyncio.to_thread-free sleep.
            while not gate.is_set():
                await asyncio.sleep(0.01)

        client = MagicMock()
        client.retain = AsyncMock(side_effect=_gated_retain)

        appended_count = 0

        def _append_new() -> None:
            """Runs in a separate thread. Blocks on the RLock until replay finishes."""
            nonlocal appended_count
            first_retain_seen.wait()
            # The RLock in append() will make this block until replay() releases.
            for i in range(3):
                wal.append(WALEntry(bank="new", content=f"new-{i}"))
                appended_count += 1

        appender = threading.Thread(target=_append_new)
        appender.start()

        replay_task = asyncio.create_task(wal.replay(client))
        # Let replay get past its first retain so first_retain_seen fires
        await asyncio.sleep(0.05)
        # Release the gate so replay can finish its remaining retains
        gate.set()
        result = await replay_task
        appender.join(timeout=2.0)

        # All 5 seeds replayed → 0 remaining from replay, plus 3 appends = 3 total
        assert result == {"replayed": 5, "failed": 0, "dropped": 0}
        assert appended_count == 3
        entries = wal.load()
        new_entries = [e for e in entries if e.bank == "new"]
        assert len(new_entries) == 3, (
            f"All 3 appends during replay must survive the terminal write_all; "
            f"got {len(new_entries)} new entries in final WAL: {entries}"
        )
