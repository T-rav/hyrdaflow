"""Tests for EpicManager lifecycle management."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from events import EventBus, EventType
from models import EpicState
from state import StateTracker
from tests.helpers import ConfigFactory


def _make_manager(
    tmp_path: Path,
    **config_kw,
):
    """Build an EpicManager with standard mocks."""
    from epic import EpicManager

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        state_file=tmp_path / "state.json",
        **config_kw,
    )
    state = StateTracker(config.state_file)
    bus = EventBus()
    prs = AsyncMock()
    fetcher = AsyncMock()
    manager = EpicManager(config, state, prs, fetcher, bus)
    return manager, state, bus, prs, fetcher


class TestRegisterEpic:
    @pytest.mark.asyncio
    async def test_register_persists_state(self, tmp_path: Path) -> None:
        mgr, state, bus, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "My Epic", [1, 2, 3])

        epic = state.get_epic_state(100)
        assert epic is not None
        assert epic.epic_number == 100
        assert epic.title == "My Epic"
        assert epic.child_issues == [1, 2, 3]
        assert epic.closed is False

    @pytest.mark.asyncio
    async def test_register_publishes_event(self, tmp_path: Path) -> None:
        mgr, _, bus, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "My Epic", [1, 2])

        history = bus.get_history()
        epic_events = [e for e in history if e.type == EventType.EPIC_UPDATE]
        assert len(epic_events) == 1
        assert epic_events[0].data["action"] == "registered"
        assert epic_events[0].data["epic_number"] == 100

    @pytest.mark.asyncio
    async def test_register_auto_decomposed_flag(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Auto Epic", [1], auto_decomposed=True)

        epic = state.get_epic_state(100)
        assert epic is not None
        assert epic.auto_decomposed is True


class TestOnChildCompleted:
    @pytest.mark.asyncio
    async def test_marks_child_complete_and_publishes(self, tmp_path: Path) -> None:
        mgr, state, bus, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [1, 2, 3])

        await mgr.on_child_completed(100, 1)

        epic = state.get_epic_state(100)
        assert 1 in epic.completed_children
        history = bus.get_history()
        updates = [e for e in history if e.type == EventType.EPIC_UPDATE]
        # registered + child_completed
        assert any(e.data["action"] == "child_completed" for e in updates)

    @pytest.mark.asyncio
    async def test_auto_close_when_all_complete(self, tmp_path: Path) -> None:
        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        # Stub fetcher to return issues with fixed_label
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "Epic", [1, 2])

        await mgr.on_child_completed(100, 1)
        epic = state.get_epic_state(100)
        assert epic.closed is False

        await mgr.on_child_completed(100, 2)
        epic = state.get_epic_state(100)
        assert epic.closed is True

    @pytest.mark.asyncio
    async def test_no_auto_close_with_remaining_children(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [1, 2, 3])

        await mgr.on_child_completed(100, 1)
        await mgr.on_child_completed(100, 2)

        epic = state.get_epic_state(100)
        assert epic.closed is False


class TestOnChildFailed:
    @pytest.mark.asyncio
    async def test_marks_child_failed(self, tmp_path: Path) -> None:
        mgr, state, bus, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [1, 2])

        await mgr.on_child_failed(100, 1)

        epic = state.get_epic_state(100)
        assert 1 in epic.failed_children
        updates = [e for e in bus.get_history() if e.type == EventType.EPIC_UPDATE]
        assert any(e.data["action"] == "child_failed" for e in updates)


class TestOnChildPlanned:
    @pytest.mark.asyncio
    async def test_updates_last_activity(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path)
        # Register with an old timestamp
        old_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        es = EpicState(
            epic_number=100,
            title="Epic",
            child_issues=[1, 2],
            last_activity=old_time,
        )
        state.upsert_epic_state(es)

        await mgr.on_child_planned(100, 1)

        updated = state.get_epic_state(100)
        assert updated.last_activity > old_time

    @pytest.mark.asyncio
    async def test_noop_for_unknown_epic(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path)
        # Should not raise
        await mgr.on_child_planned(999, 1)


class TestGetProgress:
    @pytest.mark.asyncio
    async def test_active_status(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [1, 2, 3])
        await mgr.on_child_completed(100, 1)

        progress = mgr.get_progress(100)
        assert progress is not None
        assert progress.status == "active"
        assert progress.completed == 1
        assert progress.total_children == 3
        assert progress.in_progress == 2
        assert progress.percent_complete == 33.3

    @pytest.mark.asyncio
    async def test_blocked_status(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_completed(100, 1)
        await mgr.on_child_failed(100, 2)

        progress = mgr.get_progress(100)
        assert progress.status == "blocked"

    @pytest.mark.asyncio
    async def test_stale_status(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path, epic_stale_days=1)
        old_time = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        es = EpicState(
            epic_number=100,
            title="Stale Epic",
            child_issues=[1, 2],
            last_activity=old_time,
        )
        state.upsert_epic_state(es)

        progress = mgr.get_progress(100)
        assert progress.status == "stale"

    @pytest.mark.asyncio
    async def test_completed_status(self, tmp_path: Path) -> None:
        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "Done Epic", [1])
        await mgr.on_child_completed(100, 1)

        progress = mgr.get_progress(100)
        assert progress.status == "completed"
        assert progress.percent_complete == 100.0

    def test_returns_none_for_unknown(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path)
        assert mgr.get_progress(999) is None

    @pytest.mark.asyncio
    async def test_includes_child_issues(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10, 20, 30])

        progress = mgr.get_progress(100)
        assert progress.child_issues == [10, 20, 30]


class TestGetAllProgress:
    @pytest.mark.asyncio
    async def test_returns_all_tracked(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic A", [1, 2])
        await mgr.register_epic(200, "Epic B", [3])

        all_progress = mgr.get_all_progress()
        assert len(all_progress) == 2
        numbers = {p.epic_number for p in all_progress}
        assert numbers == {100, 200}


class TestCheckStaleEpics:
    @pytest.mark.asyncio
    async def test_detects_stale_and_posts_comment(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, _ = _make_manager(tmp_path, epic_stale_days=1)
        old_time = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        es = EpicState(
            epic_number=100,
            title="Old Epic",
            child_issues=[1],
            last_activity=old_time,
        )
        state.upsert_epic_state(es)

        stale = await mgr.check_stale_epics()
        assert stale == [100]
        prs.post_comment.assert_called_once()
        assert prs.post_comment.call_args[0][0] == 100

        # Should publish SYSTEM_ALERT
        alerts = [e for e in bus.get_history() if e.type == EventType.SYSTEM_ALERT]
        assert len(alerts) == 1

    @pytest.mark.asyncio
    async def test_skips_closed_epics(self, tmp_path: Path) -> None:
        mgr, state, _, prs, _ = _make_manager(tmp_path, epic_stale_days=1)
        old_time = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        es = EpicState(
            epic_number=100,
            title="Closed",
            child_issues=[1],
            last_activity=old_time,
            closed=True,
        )
        state.upsert_epic_state(es)

        stale = await mgr.check_stale_epics()
        assert stale == []
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_fresh_epics(self, tmp_path: Path) -> None:
        mgr, _, _, prs, _ = _make_manager(tmp_path, epic_stale_days=7)
        await mgr.register_epic(100, "Fresh Epic", [1])

        stale = await mgr.check_stale_epics()
        assert stale == []
        prs.post_comment.assert_not_called()


class TestGetDetail:
    @pytest.mark.asyncio
    async def test_fetches_child_details(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, _, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10, 20])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Child 10", labels=["hydraflow-fixed"]
        )
        child_20 = IssueFactory.create(number=20, title="Child 20", labels=[])
        child_map = {10: child_10, 20: child_20}
        fetcher.fetch_issue_by_number = AsyncMock(side_effect=child_map.get)

        detail = await mgr.get_detail(100)
        assert detail is not None
        assert detail.epic_number == 100
        assert len(detail.children) == 2

        c10 = next(c for c in detail.children if c.issue_number == 10)
        assert c10.title == "Child 10"
        assert c10.is_completed is True
        assert c10.url.startswith("https://github.com/")

        c20 = next(c for c in detail.children if c.issue_number == 20)
        assert c20.title == "Child 20"
        assert c20.is_completed is False

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path)
        assert await mgr.get_detail(999) is None


class TestStateCrud:
    """Test StateTracker epic CRUD methods directly."""

    def test_round_trip(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        es = EpicState(epic_number=42, title="Test", child_issues=[1, 2, 3])
        state.upsert_epic_state(es)

        loaded = state.get_epic_state(42)
        assert loaded is not None
        assert loaded.epic_number == 42
        assert loaded.child_issues == [1, 2, 3]

    def test_persistence_across_reload(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        state1 = StateTracker(path)
        state1.upsert_epic_state(EpicState(epic_number=42, title="Persist"))

        state2 = StateTracker(path)
        loaded = state2.get_epic_state(42)
        assert loaded is not None
        assert loaded.title == "Persist"

    def test_mark_child_complete(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.upsert_epic_state(EpicState(epic_number=42, child_issues=[1, 2]))

        state.mark_epic_child_complete(42, 1)
        es = state.get_epic_state(42)
        assert 1 in es.completed_children

    def test_mark_child_failed(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.upsert_epic_state(EpicState(epic_number=42, child_issues=[1, 2]))

        state.mark_epic_child_failed(42, 1)
        es = state.get_epic_state(42)
        assert 1 in es.failed_children

    def test_close_epic(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.upsert_epic_state(EpicState(epic_number=42, child_issues=[1]))

        state.close_epic(42)
        es = state.get_epic_state(42)
        assert es.closed is True

    def test_get_all_epic_states(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.upsert_epic_state(EpicState(epic_number=1, title="A"))
        state.upsert_epic_state(EpicState(epic_number=2, title="B"))

        all_states = state.get_all_epic_states()
        assert len(all_states) == 2
        assert "1" in all_states
        assert "2" in all_states

    def test_noop_for_unknown_epic(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        # Should not raise
        state.mark_epic_child_complete(999, 1)
        state.mark_epic_child_failed(999, 1)
        state.close_epic(999)
        assert state.get_epic_state(999) is None

    def test_complete_removes_from_failed(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.upsert_epic_state(EpicState(epic_number=42, child_issues=[1]))
        state.mark_epic_child_failed(42, 1)
        assert 1 in state.get_epic_state(42).failed_children

        state.mark_epic_child_complete(42, 1)
        es = state.get_epic_state(42)
        assert 1 in es.completed_children
        assert 1 not in es.failed_children

    def test_deep_copy_isolation(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.upsert_epic_state(EpicState(epic_number=42, child_issues=[1, 2]))

        retrieved = state.get_epic_state(42)
        retrieved.child_issues.append(999)

        original = state.get_epic_state(42)
        assert 999 not in original.child_issues
