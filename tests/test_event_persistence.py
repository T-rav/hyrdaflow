"""Tests for event persistence — EventLog JSONL read/write/rotation."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from events import EventBus, EventLog, EventType, HydraFlowEvent
from tests.conftest import EventFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: EventType = EventType.BATCH_START,
    timestamp: str | None = None,
    data: dict | None = None,
) -> HydraFlowEvent:
    return EventFactory.create(
        type=event_type,
        timestamp=timestamp or datetime.now(UTC).isoformat(),
        data=data or {},
    )


def _make_event_at(days_ago: int, **kwargs) -> HydraFlowEvent:  # type: ignore[no-untyped-def]
    ts = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    return _make_event(timestamp=ts, **kwargs)


# ---------------------------------------------------------------------------
# TestEventLogAppend
# ---------------------------------------------------------------------------


class TestEventLogAppend:
    @pytest.mark.asyncio
    async def test_append_single_event_writes_valid_jsonl(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        event = _make_event(data={"batch": 1})
        await log.append(event)

        lines = log.path.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["type"] == "batch_start"
        assert parsed["data"] == {"batch": 1}

    @pytest.mark.asyncio
    async def test_append_multiple_events_produces_multiple_lines(
        self, tmp_path: Path
    ) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        for i in range(5):
            await log.append(_make_event(data={"i": i}))

        lines = log.path.read_text().strip().split("\n")
        assert len(lines) == 5

    @pytest.mark.asyncio
    async def test_file_created_if_not_exists(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        assert not path.exists()
        log = EventLog(path)
        await log.append(_make_event())
        assert path.exists()

    @pytest.mark.asyncio
    async def test_parent_directories_created(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "events.jsonl"
        log = EventLog(path)
        await log.append(_make_event())
        assert path.exists()

    @pytest.mark.asyncio
    async def test_append_is_actually_append(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        await log.append(_make_event(data={"n": 1}))
        await log.append(_make_event(data={"n": 2}))

        lines = log.path.read_text().strip().split("\n")
        assert json.loads(lines[0])["data"]["n"] == 1
        assert json.loads(lines[1])["data"]["n"] == 2


# ---------------------------------------------------------------------------
# TestEventLogLoad
# ---------------------------------------------------------------------------


class TestEventLogLoad:
    @pytest.mark.asyncio
    async def test_load_from_valid_jsonl(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        events = [_make_event(data={"i": i}) for i in range(3)]
        for e in events:
            await log.append(e)

        loaded = await log.load()
        assert len(loaded) == 3
        assert loaded[0].data == {"i": 0}
        assert loaded[2].data == {"i": 2}

    @pytest.mark.asyncio
    async def test_load_with_since_filter(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        old_event = _make_event_at(days_ago=10, data={"age": "old"})
        new_event = _make_event_at(days_ago=1, data={"age": "new"})
        await log.append(old_event)
        await log.append(new_event)

        since = datetime.now(UTC) - timedelta(days=5)
        loaded = await log.load(since=since)
        assert len(loaded) == 1
        assert loaded[0].data == {"age": "new"}

    @pytest.mark.asyncio
    async def test_load_with_max_events(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        for i in range(10):
            await log.append(_make_event(data={"i": i}))

        loaded = await log.load(max_events=3)
        assert len(loaded) == 3
        # Should keep the last 3
        assert loaded[0].data == {"i": 7}
        assert loaded[2].data == {"i": 9}

    @pytest.mark.asyncio
    async def test_corrupt_lines_skipped_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "events.jsonl"
        # Write a valid line, a corrupt line, and another valid line
        valid = _make_event(data={"ok": True})
        lines = [
            valid.model_dump_json(),
            "this is not valid json",
            valid.model_dump_json(),
        ]
        path.write_text("\n".join(lines) + "\n")

        log = EventLog(path)
        loaded = await log.load()
        assert len(loaded) == 2
        assert "Skipping corrupt event log line 2" in caplog.text

    @pytest.mark.asyncio
    async def test_load_from_nonexistent_file(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "nonexistent.jsonl")
        loaded = await log.load()
        assert loaded == []

    @pytest.mark.asyncio
    async def test_roundtrip_append_then_load(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        original = _make_event(
            event_type=EventType.PR_CREATED,
            data={"pr": 42, "branch": "agent/issue-1"},
        )
        await log.append(original)
        loaded = await log.load()
        assert len(loaded) == 1
        assert loaded[0].type == original.type
        assert loaded[0].timestamp == original.timestamp
        assert loaded[0].data == original.data

    @pytest.mark.asyncio
    async def test_load_skips_empty_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        valid = _make_event(data={"ok": True})
        path.write_text(
            valid.model_dump_json() + "\n\n\n" + valid.model_dump_json() + "\n"
        )

        log = EventLog(path)
        loaded = await log.load()
        assert len(loaded) == 2


# ---------------------------------------------------------------------------
# TestEventLogRotation
# ---------------------------------------------------------------------------


class TestEventLogRotation:
    @pytest.mark.asyncio
    async def test_rotation_keeps_only_recent_events(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        # Write old and new events
        old_event = _make_event_at(days_ago=10, data={"age": "old"})
        new_event = _make_event_at(days_ago=1, data={"age": "new"})
        await log.append(old_event)
        await log.append(new_event)

        # Force rotation with a tiny max_size (1 byte) and 5-day retention
        await log.rotate(max_size_bytes=1, max_age_days=5)

        loaded = await log.load()
        assert len(loaded) == 1
        assert loaded[0].data == {"age": "new"}

    @pytest.mark.asyncio
    async def test_rotation_respects_max_age_days(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        for days in [20, 15, 5, 1]:
            await log.append(_make_event_at(days_ago=days, data={"days_ago": days}))

        await log.rotate(max_size_bytes=1, max_age_days=7)

        loaded = await log.load()
        assert len(loaded) == 2
        ages = [e.data["days_ago"] for e in loaded]
        assert ages == [5, 1]

    @pytest.mark.asyncio
    async def test_rotation_all_events_too_old(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        await log.append(_make_event_at(days_ago=30))
        await log.append(_make_event_at(days_ago=20))

        await log.rotate(max_size_bytes=1, max_age_days=7)

        loaded = await log.load()
        assert loaded == []

    @pytest.mark.asyncio
    async def test_rotation_is_atomic(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        event = _make_event_at(days_ago=1, data={"keep": True})
        await log.append(event)
        await log.append(_make_event_at(days_ago=30, data={"keep": False}))

        await log.rotate(max_size_bytes=1, max_age_days=7)

        # File should exist (not be left in a partial state)
        assert log.path.exists()
        loaded = await log.load()
        assert len(loaded) == 1
        assert loaded[0].data["keep"] is True

    @pytest.mark.asyncio
    async def test_rotation_skipped_when_under_size(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        await log.append(_make_event_at(days_ago=30, data={"old": True}))

        original_content = log.path.read_text()
        await log.rotate(max_size_bytes=10_000_000, max_age_days=7)

        # File should be unchanged since it's under the size limit
        assert log.path.read_text() == original_content

    @pytest.mark.asyncio
    async def test_rotation_nonexistent_file(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "nonexistent.jsonl")
        # Should not raise
        await log.rotate(max_size_bytes=1, max_age_days=7)

    @pytest.mark.asyncio
    async def test_no_temp_files_left_after_rotation(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        await log.append(_make_event_at(days_ago=1))

        await log.rotate(max_size_bytes=1, max_age_days=7)

        # Only the events.jsonl file should remain
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "events.jsonl"


# ---------------------------------------------------------------------------
# TestEventBusWithPersistence
# ---------------------------------------------------------------------------


class TestEventBusWithPersistence:
    @pytest.mark.asyncio
    async def test_publish_writes_to_disk(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        bus = EventBus(event_log=log)

        event = _make_event(data={"bus": True})
        await bus.publish(event)

        # Give the fire-and-forget task a moment to complete
        await asyncio.sleep(0.05)

        loaded = await log.load()
        assert len(loaded) == 1
        assert loaded[0].data == {"bus": True}

    @pytest.mark.asyncio
    async def test_load_history_from_disk(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        # Pre-populate disk log
        for i in range(5):
            await log.append(_make_event(data={"i": i}))

        bus = EventBus(event_log=log)
        assert bus.get_history() == []

        await bus.load_history_from_disk()
        history = bus.get_history()
        assert len(history) == 5
        assert history[0].data == {"i": 0}

    @pytest.mark.asyncio
    async def test_load_history_advances_event_counter(self, tmp_path: Path) -> None:
        """After loading history, new events must have IDs higher than all
        historical events so the frontend dedup logic doesn't drop them."""
        log = EventLog(tmp_path / "events.jsonl")
        # Write events that will have auto-assigned IDs
        for _ in range(3):
            await log.append(_make_event(data={"old": True}))

        # Note the max ID from the persisted events
        loaded = await log.load()
        max_historical_id = max(e.id for e in loaded)

        bus = EventBus(event_log=log)
        await bus.load_history_from_disk()

        # Publish a new event — its ID must exceed the historical max
        new_event = _make_event(data={"new": True})
        await bus.publish(new_event)
        history = bus.get_history()
        new_ids = [e.id for e in history if e.data.get("new")]
        assert len(new_ids) == 1
        assert new_ids[0] > max_historical_id

    @pytest.mark.asyncio
    async def test_publish_without_event_log_works(self, event_bus) -> None:
        event = _make_event(data={"no_log": True})
        await event_bus.publish(event)

        history = event_bus.get_history()
        assert len(history) == 1
        assert history[0].data == {"no_log": True}

    @pytest.mark.asyncio
    async def test_load_history_without_event_log_is_noop(self, event_bus) -> None:
        await event_bus.load_history_from_disk()
        assert event_bus.get_history() == []

    @pytest.mark.asyncio
    async def test_publish_does_not_block_subscribers(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        bus = EventBus(event_log=log)
        queue = bus.subscribe()

        event = _make_event(data={"fast": True})
        await bus.publish(event)

        # Subscriber should receive immediately (before disk write completes)
        received = queue.get_nowait()
        assert received.data == {"fast": True}

    @pytest.mark.asyncio
    async def test_load_history_respects_max_history(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        for i in range(20):
            await log.append(_make_event(data={"i": i}))

        bus = EventBus(max_history=5, event_log=log)
        await bus.load_history_from_disk()

        history = bus.get_history()
        assert len(history) == 5
        assert history[0].data == {"i": 15}

    @pytest.mark.asyncio
    async def test_load_events_since_delegates_to_log(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        await log.append(_make_event_at(days_ago=10, data={"age": "old"}))
        await log.append(_make_event_at(days_ago=1, data={"age": "new"}))

        bus = EventBus(event_log=log)
        since = datetime.now(UTC) - timedelta(days=5)
        events = await bus.load_events_since(since)
        assert events is not None
        assert len(events) == 1
        assert events[0].data == {"age": "new"}

    @pytest.mark.asyncio
    async def test_load_events_since_returns_none_without_log(self, event_bus) -> None:
        result = await event_bus.load_events_since(datetime.now(UTC))
        assert result is None

    @pytest.mark.asyncio
    async def test_rotate_log_delegates_to_log(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        await log.append(_make_event_at(days_ago=30, data={"old": True}))
        await log.append(_make_event_at(days_ago=1, data={"new": True}))

        bus = EventBus(event_log=log)
        await bus.rotate_log(max_size_bytes=1, max_age_days=7)

        loaded = await log.load()
        assert len(loaded) == 1
        assert loaded[0].data == {"new": True}

    @pytest.mark.asyncio
    async def test_rotate_log_noop_without_log(self, event_bus) -> None:
        # Should not raise
        await event_bus.rotate_log(max_size_bytes=1, max_age_days=7)

    @pytest.mark.asyncio
    async def test_persist_event_logs_error_on_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        bus = EventBus(event_log=log)

        # Make the directory read-only to force a write error
        log.path.parent.mkdir(parents=True, exist_ok=True)
        log.path.touch()
        log.path.chmod(0o000)

        try:
            event = _make_event(data={"fail": True})
            await bus.publish(event)
            # Give the fire-and-forget task a moment to complete
            await asyncio.sleep(0.1)

            assert "Failed to persist event to disk" in caplog.text
        finally:
            log.path.chmod(0o644)


# ---------------------------------------------------------------------------
# TestEventLogConfig
# ---------------------------------------------------------------------------


class TestEventLogConfig:
    def test_default_event_log_path(self) -> None:
        from config import HydraFlowConfig

        config = HydraFlowConfig(repo="test/repo")
        assert config.event_log_path.name == "events.jsonl"
        assert config.event_log_path.parent.name == ".hydraflow"

    def test_default_max_size_mb(self) -> None:
        from config import HydraFlowConfig

        config = HydraFlowConfig(repo="test/repo")
        assert config.event_log_max_size_mb == 10

    def test_default_retention_days(self) -> None:
        from config import HydraFlowConfig

        config = HydraFlowConfig(repo="test/repo")
        assert config.event_log_retention_days == 7

    def test_custom_event_log_path(self, tmp_path: Path) -> None:
        from config import HydraFlowConfig

        custom_path = tmp_path / "custom.jsonl"
        config = HydraFlowConfig(repo="test/repo", event_log_path=custom_path)
        assert config.event_log_path == custom_path

    def test_max_size_mb_validation(self) -> None:
        from pydantic import ValidationError

        from config import HydraFlowConfig

        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", event_log_max_size_mb=0)
        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", event_log_max_size_mb=101)

    def test_retention_days_validation(self) -> None:
        from pydantic import ValidationError

        from config import HydraFlowConfig

        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", event_log_retention_days=0)
        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", event_log_retention_days=91)
