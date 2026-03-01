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


class TestGetDetailEnriched:
    """Tests for the enriched get_detail with PR/CI/review data."""

    @pytest.mark.asyncio
    async def test_completed_child_has_merged_stage(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10, 20])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        child_20 = IssueFactory.create(number=20, title="Pending", labels=[])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect={10: child_10, 20: child_20}.get
        )
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        assert detail is not None

        c10 = next(c for c in detail.children if c.issue_number == 10)
        assert c10.current_stage == "merged"
        assert c10.status == "done"

    @pytest.mark.asyncio
    async def test_child_with_branch_gets_pr_info(self, tmp_path: Path) -> None:
        from models import PRInfo
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])

        child_10 = IssueFactory.create(
            number=10, title="In Progress", labels=["test-label"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)

        # Set branch in state
        state.set_branch(10, "agent/issue-10")
        pr_info = PRInfo(
            number=42,
            issue_number=10,
            branch="agent/issue-10",
            url="https://github.com/org/repo/pull/42",
        )
        prs.find_open_pr_for_branch = AsyncMock(return_value=pr_info)
        prs.get_pr_checks = AsyncMock(return_value=[{"state": "success", "name": "CI"}])
        prs.get_pr_reviews = AsyncMock(
            return_value=[{"state": "APPROVED", "author": "reviewer"}]
        )
        prs.get_pr_mergeable = AsyncMock(return_value=True)

        detail = await mgr.get_detail(100)
        c10 = detail.children[0]
        assert c10.pr_number == 42
        assert c10.pr_url == "https://github.com/org/repo/pull/42"
        assert c10.pr_state == "open"
        assert c10.branch == "agent/issue-10"
        assert c10.ci_status == "passing"
        assert c10.review_status == "approved"
        assert c10.current_stage == "implement"
        assert c10.status == "running"

    @pytest.mark.asyncio
    async def test_failed_ci_status(self, tmp_path: Path) -> None:
        from models import PRInfo
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])

        child_10 = IssueFactory.create(
            number=10, title="Failing", labels=["hydraflow-review"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)

        state.set_branch(10, "agent/issue-10")
        pr_info = PRInfo(number=42, issue_number=10, branch="agent/issue-10", url="")
        prs.find_open_pr_for_branch = AsyncMock(return_value=pr_info)
        prs.get_pr_checks = AsyncMock(
            return_value=[
                {"state": "failure", "name": "CI"},
                {"state": "success", "name": "Lint"},
            ]
        )
        prs.get_pr_reviews = AsyncMock(
            return_value=[{"state": "CHANGES_REQUESTED", "author": "rev"}]
        )
        prs.get_pr_mergeable = AsyncMock(return_value=False)

        detail = await mgr.get_detail(100)
        c10 = detail.children[0]
        assert c10.ci_status == "failing"
        assert c10.review_status == "changes_requested"

    @pytest.mark.asyncio
    async def test_detail_counts(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10, 20, 30])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        child_20 = IssueFactory.create(number=20, title="Active", labels=["test-label"])
        child_30 = IssueFactory.create(
            number=30, title="Queued", labels=["hydraflow-plan"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect={10: child_10, 20: child_20, 30: child_30}.get
        )
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        assert detail.merged_children == 1
        assert detail.active_children == 1
        assert detail.queued_children == 1


class TestReadiness:
    """Tests for _compute_readiness."""

    @pytest.mark.asyncio
    async def test_readiness_all_done(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "v1.0 Release", [10])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        assert detail.readiness.all_implemented is True
        assert detail.readiness.version == "1.0"
        assert detail.readiness.changelog_ready is True

    @pytest.mark.asyncio
    async def test_readiness_not_all_implemented(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10, 20])

        child_10 = IssueFactory.create(number=10, title="In Progress", labels=[])
        child_20 = IssueFactory.create(number=20, title="Queued", labels=[])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect={10: child_10, 20: child_20}.get
        )
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        assert detail.readiness.all_implemented is False

    @pytest.mark.asyncio
    async def test_readiness_no_version(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic Without Version", [10])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        assert detail.readiness.changelog_ready is False
        assert detail.readiness.version is None


class TestCache:
    """Tests for the background caching mechanism."""

    @pytest.mark.asyncio
    async def test_cache_returns_stale_data(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        # First call builds detail
        detail1 = await mgr.get_detail(100)
        assert detail1 is not None

        # Cache is set, so second call uses cache
        import time

        mgr._cache_timestamps[100] = time.monotonic()
        detail2 = mgr.get_cached_detail(100)
        assert detail2 is not None
        assert detail2.epic_number == 100

    @pytest.mark.asyncio
    async def test_cache_expires(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        await mgr.get_detail(100)
        # Force cache expiry
        mgr._cache_timestamps[100] = 0.0
        cached = mgr.get_cached_detail(100)
        assert cached is None

    @pytest.mark.asyncio
    async def test_refresh_cache_publishes_events(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        # Use 2 children so the epic stays open after completing 1
        await mgr.register_epic(100, "v1.0 Epic", [10, 20])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        child_20 = IssueFactory.create(number=20, title="Pending", labels=[])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect={10: child_10, 20: child_20}.get
        )
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        await mgr.refresh_cache()

        progress_events = [
            e for e in bus.get_history() if e.type == EventType.EPIC_PROGRESS
        ]
        assert len(progress_events) >= 1
        assert progress_events[0].data["epic_number"] == 100


class TestTriggerRelease:
    """Tests for the trigger_release method."""

    @pytest.mark.asyncio
    async def test_trigger_release_returns_job_id(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "v1.0 Release", [10])

        result = await mgr.trigger_release(100)
        assert "job_id" in result
        assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_trigger_release_unknown_epic(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path)

        result = await mgr.trigger_release(999)
        assert "error" in result
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_trigger_release_already_closed(self, tmp_path: Path) -> None:
        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "Epic", [10])
        await mgr.on_child_completed(100, 10)

        result = await mgr.trigger_release(100)
        assert "error" in result
        assert "already closed" in result["error"]

    @pytest.mark.asyncio
    async def test_trigger_release_duplicate_returns_in_progress(
        self, tmp_path: Path
    ) -> None:
        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10, 20])

        # Simulate a running job
        mgr._release_jobs[100] = "release-100-existing"
        result = await mgr.trigger_release(100)
        assert result["status"] == "in_progress"
        assert result["job_id"] == "release-100-existing"


class TestGetAllDetail:
    """Tests for the get_all_detail method."""

    @pytest.mark.asyncio
    async def test_returns_all_epic_details(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic A", [10])
        await mgr.register_epic(200, "Epic B", [20])

        child_10 = IssueFactory.create(number=10, title="A1", labels=[])
        child_20 = IssueFactory.create(number=20, title="B1", labels=[])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect={10: child_10, 20: child_20}.get
        )
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        details = await mgr.get_all_detail()
        assert len(details) == 2
        numbers = {d.epic_number for d in details}
        assert numbers == {100, 200}

    @pytest.mark.asyncio
    async def test_detail_includes_merge_strategy(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])

        child_10 = IssueFactory.create(number=10, title="A1", labels=[])
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        details = await mgr.get_all_detail()
        assert details[0].merge_strategy == "independent"

    @pytest.mark.asyncio
    async def test_detail_includes_readiness(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])

        child_10 = IssueFactory.create(number=10, title="A1", labels=[])
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        details = await mgr.get_all_detail()
        assert hasattr(details[0], "readiness")
        assert details[0].readiness.all_implemented is False


class TestReleaseEpic:
    """Tests for the release_epic merge sequence."""

    @staticmethod
    def _approve_children_directly(state, epic_number: int, children: list[int]):
        """Approve children via state directly to avoid triggering auto-merge."""
        for child in children:
            state.mark_epic_child_approved(epic_number, child)

    @pytest.mark.asyncio
    async def test_merges_all_child_prs(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(
            tmp_path, epic_merge_strategy="bundled"
        )
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "v1.0 Epic", [10, 20])
        # Approve via state directly to avoid triggering on_child_approved auto-merge
        self._approve_children_directly(state, 100, [10, 20])

        prs.find_pr_for_issue = AsyncMock(side_effect={10: 42, 20: 43}.get)
        prs.merge_pr = AsyncMock(return_value=True)

        result = await mgr.release_epic(100)
        assert "error" not in result
        assert result["epic_number"] == 100
        merges = result["merges"]
        assert len(merges) == 2
        assert merges[0]["status"] == "merged"
        assert merges[1]["status"] == "merged"

        # Verify epic is marked as released
        epic = state.get_epic_state(100)
        assert epic.released is True

    @pytest.mark.asyncio
    async def test_halts_on_missing_pr(self, tmp_path: Path) -> None:
        mgr, state, _, prs, fetcher = _make_manager(
            tmp_path, epic_merge_strategy="bundled"
        )
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "v1.0 Epic", [10, 20])
        self._approve_children_directly(state, 100, [10, 20])

        # First child has no PR
        prs.find_pr_for_issue = AsyncMock(side_effect={10: 0, 20: 43}.get)

        result = await mgr.release_epic(100)
        assert "error" in result
        assert "no PR found" in result["error"]
        # Epic should NOT be marked as released
        epic = state.get_epic_state(100)
        assert epic.released is False

    @pytest.mark.asyncio
    async def test_halts_on_merge_failure(self, tmp_path: Path) -> None:
        mgr, state, _, prs, fetcher = _make_manager(
            tmp_path, epic_merge_strategy="bundled"
        )
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "v1.0 Epic", [10, 20])
        self._approve_children_directly(state, 100, [10, 20])

        prs.find_pr_for_issue = AsyncMock(side_effect={10: 42, 20: 43}.get)
        prs.merge_pr = AsyncMock(return_value=False)

        result = await mgr.release_epic(100)
        assert "error" in result
        assert "merge failed" in result["error"]
        epic = state.get_epic_state(100)
        assert epic.released is False

    @pytest.mark.asyncio
    async def test_returns_error_for_not_ready_epic(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path, epic_merge_strategy="bundled")
        await mgr.register_epic(100, "Epic", [10, 20])
        # No approvals — not ready

        result = await mgr.release_epic(100)
        assert "error" in result
        assert "not ready" in result["error"]

    @pytest.mark.asyncio
    async def test_idempotent_rejects_second_call(self, tmp_path: Path) -> None:
        mgr, state, _, prs, fetcher = _make_manager(
            tmp_path, epic_merge_strategy="bundled"
        )
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "v1.0 Epic", [10])
        self._approve_children_directly(state, 100, [10])

        prs.find_pr_for_issue = AsyncMock(return_value=42)
        prs.merge_pr = AsyncMock(return_value=True)

        # First release succeeds
        result1 = await mgr.release_epic(100)
        assert "error" not in result1

        # Second release should fail (already released)
        result2 = await mgr.release_epic(100)
        assert "error" in result2
        assert "already been released" in result2["error"]

    @pytest.mark.asyncio
    async def test_trigger_release_already_released(self, tmp_path: Path) -> None:
        mgr, state, _, prs, fetcher = _make_manager(
            tmp_path, epic_merge_strategy="bundled"
        )
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "v1.0 Epic", [10])
        self._approve_children_directly(state, 100, [10])

        prs.find_pr_for_issue = AsyncMock(return_value=42)
        prs.merge_pr = AsyncMock(return_value=True)

        # Release the epic first
        await mgr.release_epic(100)

        # trigger_release should also detect the released flag
        result = await mgr.trigger_release(100)
        assert "error" in result
        assert "already released" in result["error"]


class TestExecuteRelease:
    """Tests for the _execute_release background task events."""

    @staticmethod
    def _approve_children_directly(state, epic_number: int, children: list[int]):
        """Approve children via state directly to avoid triggering auto-merge."""
        for child in children:
            state.mark_epic_child_approved(epic_number, child)

    @pytest.mark.asyncio
    async def test_publishes_releasing_and_released_events(
        self, tmp_path: Path
    ) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(
            tmp_path, epic_merge_strategy="bundled"
        )
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "v1.0 Epic", [10])
        self._approve_children_directly(state, 100, [10])

        prs.find_pr_for_issue = AsyncMock(return_value=42)
        prs.merge_pr = AsyncMock(return_value=True)

        await mgr._execute_release(100, "test-job-1")

        history = bus.get_history()
        releasing = [e for e in history if e.type == EventType.EPIC_RELEASING]
        released = [e for e in history if e.type == EventType.EPIC_RELEASED]

        assert len(releasing) == 1
        assert releasing[0].data["epic_number"] == 100
        assert releasing[0].data["job_id"] == "test-job-1"

        assert len(released) == 1
        assert released[0].data["epic_number"] == 100
        assert released[0].data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_publishes_failed_status_on_error(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(
            tmp_path, epic_merge_strategy="bundled"
        )
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "v1.0 Epic", [10])
        self._approve_children_directly(state, 100, [10])

        # Merge fails, so release_epic returns an error
        prs.find_pr_for_issue = AsyncMock(return_value=42)
        prs.merge_pr = AsyncMock(return_value=False)

        await mgr._execute_release(100, "test-job-2")

        history = bus.get_history()
        released = [e for e in history if e.type == EventType.EPIC_RELEASED]

        assert len(released) == 1
        assert released[0].data["status"] == "failed"

    @pytest.mark.asyncio
    async def test_cleans_up_job_id(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(
            tmp_path, epic_merge_strategy="bundled"
        )
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "v1.0 Epic", [10])
        self._approve_children_directly(state, 100, [10])

        prs.find_pr_for_issue = AsyncMock(return_value=42)
        prs.merge_pr = AsyncMock(return_value=True)

        mgr._release_jobs[100] = "test-job-3"
        await mgr._execute_release(100, "test-job-3")

        # Job should be cleaned up after execution
        assert 100 not in mgr._release_jobs


class TestCacheInvalidation:
    """Verify that child state changes invalidate the detail cache."""

    @pytest.mark.asyncio
    async def test_on_child_completed_invalidates_cache(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "Epic", [10, 20])

        # Seed the cache manually
        from models import EpicDetail

        mgr._detail_cache[100] = EpicDetail(epic_number=100)
        mgr._cache_timestamps[100] = 999999.0

        await mgr.on_child_completed(100, 10)

        assert 100 not in mgr._detail_cache
        assert 100 not in mgr._cache_timestamps

    @pytest.mark.asyncio
    async def test_on_child_failed_invalidates_cache(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "Epic", [10, 20])

        from models import EpicDetail

        mgr._detail_cache[100] = EpicDetail(epic_number=100)
        mgr._cache_timestamps[100] = 999999.0

        await mgr.on_child_failed(100, 10)

        assert 100 not in mgr._detail_cache
        assert 100 not in mgr._cache_timestamps

    @pytest.mark.asyncio
    async def test_on_child_approved_invalidates_cache(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "Epic", [10, 20])

        from models import EpicDetail

        mgr._detail_cache[100] = EpicDetail(epic_number=100)
        mgr._cache_timestamps[100] = 999999.0

        await mgr.on_child_approved(100, 10)

        assert 100 not in mgr._detail_cache
        assert 100 not in mgr._cache_timestamps

    @pytest.mark.asyncio
    async def test_on_child_planned_invalidates_cache(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "Epic", [10, 20])

        from models import EpicDetail

        mgr._detail_cache[100] = EpicDetail(epic_number=100)
        mgr._cache_timestamps[100] = 999999.0

        await mgr.on_child_planned(100, 10)

        assert 100 not in mgr._detail_cache
        assert 100 not in mgr._cache_timestamps

    @pytest.mark.asyncio
    async def test_cache_invalidation_no_op_for_unknown_epic(
        self, tmp_path: Path
    ) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        # Should not raise even if epic doesn't exist in cache
        mgr._invalidate_cache(999)
        assert 999 not in mgr._detail_cache

    @pytest.mark.asyncio
    async def test_get_detail_returns_fresh_data_after_invalidation(
        self, tmp_path: Path
    ) -> None:
        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
        await mgr.register_epic(100, "Epic", [10])

        from models import EpicDetail

        stale_detail = EpicDetail(epic_number=100, title="Stale")
        mgr._detail_cache[100] = stale_detail
        mgr._cache_timestamps[100] = 999999999.0  # far in the future

        # Cache should return stale data before invalidation
        cached = mgr.get_cached_detail(100)
        assert cached is not None
        assert cached.title == "Stale"

        # Invalidate
        mgr._invalidate_cache(100)

        # Cache should now return None
        assert mgr.get_cached_detail(100) is None


class TestRefreshCacheReadyGuard:
    """Tests for EPIC_READY event publishing with released guard."""

    @pytest.mark.asyncio
    async def test_publishes_ready_when_all_conditions_met(
        self, tmp_path: Path
    ) -> None:
        from models import PRInfo
        from tests.conftest import IssueFactory

        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        # Use 2 children: one completed, one with an approved PR.
        # This keeps the epic open (not auto-closed) while meeting readiness.
        await mgr.register_epic(100, "v1.0 Epic", [10, 20])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        child_20 = IssueFactory.create(
            number=20, title="In Review", labels=["hydraflow-review"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect={10: child_10, 20: child_20}.get
        )

        state.set_branch(20, "agent/issue-20")
        pr_info = PRInfo(number=43, issue_number=20, branch="agent/issue-20", url="")
        prs.find_open_pr_for_branch = AsyncMock(return_value=pr_info)
        prs.get_pr_checks = AsyncMock(return_value=[{"state": "success", "name": "CI"}])
        prs.get_pr_reviews = AsyncMock(
            return_value=[{"state": "APPROVED", "author": "rev"}]
        )
        prs.get_pr_mergeable = AsyncMock(return_value=True)

        await mgr.refresh_cache()

        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 1
        assert ready_events[0].data["epic_number"] == 100

    @pytest.mark.asyncio
    async def test_does_not_publish_ready_for_released_epic(
        self, tmp_path: Path
    ) -> None:
        from models import PRInfo
        from tests.conftest import IssueFactory

        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "v1.0 Epic", [10])
        await mgr.on_child_completed(100, 10)

        # Mark epic as released
        epic = state.get_epic_state(100)
        epic.released = True
        state.upsert_epic_state(epic)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)

        state.set_branch(10, "agent/issue-10")
        pr_info = PRInfo(number=42, issue_number=10, branch="agent/issue-10", url="")
        prs.find_open_pr_for_branch = AsyncMock(return_value=pr_info)
        prs.get_pr_checks = AsyncMock(return_value=[{"state": "success", "name": "CI"}])
        prs.get_pr_reviews = AsyncMock(
            return_value=[{"state": "APPROVED", "author": "rev"}]
        )
        prs.get_pr_mergeable = AsyncMock(return_value=True)

        await mgr.refresh_cache()

        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 0

    @pytest.mark.asyncio
    async def test_does_not_publish_ready_when_conditions_not_met(
        self, tmp_path: Path
    ) -> None:
        from tests.conftest import IssueFactory

        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "v1.0 Epic", [10, 20])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        child_20 = IssueFactory.create(number=20, title="WIP", labels=[])
        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect={10: child_10, 20: child_20}.get
        )
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        await mgr.refresh_cache()

        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 0

    @pytest.mark.asyncio
    async def test_skips_closed_epics(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, bus, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "v1.0 Epic", [10])
        await mgr.on_child_completed(100, 10)

        # Close the epic
        state.close_epic(100)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        await mgr.refresh_cache()

        progress_events = [
            e for e in bus.get_history() if e.type == EventType.EPIC_PROGRESS
        ]
        assert len(progress_events) == 0


class TestReadinessEdgeCases:
    """Edge case tests for _compute_readiness."""

    @pytest.mark.asyncio
    async def test_empty_children_returns_default(self, tmp_path: Path) -> None:
        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Empty Epic", [])

        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        assert detail is not None
        assert detail.readiness.all_implemented is False
        assert detail.readiness.all_approved is False

    @pytest.mark.asyncio
    async def test_children_with_no_prs_vacuously_pass_ci_review(
        self, tmp_path: Path
    ) -> None:
        """Children without PRs should vacuously pass CI/review checks.

        The `all()` over empty generator is True in Python.
        """
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "v2.0 Release", [10])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        # All children are done (no open PRs), so CI/review/conflicts are
        # vacuously True
        assert detail.readiness.all_ci_passing is True
        assert detail.readiness.all_approved is True
        assert detail.readiness.no_conflicts is True

    @pytest.mark.asyncio
    async def test_draft_pr_detected(self, tmp_path: Path) -> None:
        from models import PRInfo
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])

        child_10 = IssueFactory.create(number=10, title="WIP", labels=[])
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)

        state.set_branch(10, "agent/issue-10")
        pr_info = PRInfo(
            number=42,
            issue_number=10,
            branch="agent/issue-10",
            url="",
            draft=True,
        )
        prs.find_open_pr_for_branch = AsyncMock(return_value=pr_info)
        prs.get_pr_checks = AsyncMock(return_value=[])
        prs.get_pr_reviews = AsyncMock(return_value=[])
        prs.get_pr_mergeable = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        c10 = detail.children[0]
        assert c10.pr_state == "draft"

    @pytest.mark.asyncio
    async def test_pending_ci_status(self, tmp_path: Path) -> None:
        from models import PRInfo
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])

        child_10 = IssueFactory.create(
            number=10, title="Pending", labels=["hydraflow-review"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)

        state.set_branch(10, "agent/issue-10")
        pr_info = PRInfo(number=42, issue_number=10, branch="agent/issue-10", url="")
        prs.find_open_pr_for_branch = AsyncMock(return_value=pr_info)
        prs.get_pr_checks = AsyncMock(return_value=[{"state": "pending", "name": "CI"}])
        prs.get_pr_reviews = AsyncMock(return_value=[])
        prs.get_pr_mergeable = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        c10 = detail.children[0]
        assert c10.ci_status == "pending"

    @pytest.mark.asyncio
    async def test_pr_enrichment_failure_graceful(self, tmp_path: Path) -> None:
        """PR lookup failure should not crash detail building."""
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])

        child_10 = IssueFactory.create(number=10, title="Active", labels=[])
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)

        state.set_branch(10, "agent/issue-10")
        prs.find_open_pr_for_branch = AsyncMock(side_effect=RuntimeError("API error"))

        detail = await mgr.get_detail(100)
        assert detail is not None
        c10 = detail.children[0]
        # PR data should be absent but child should still be present
        assert c10.pr_number is None
        assert c10.ci_status is None

    @pytest.mark.asyncio
    async def test_github_fetch_failure_graceful(self, tmp_path: Path) -> None:
        """GitHub issue fetch failure should not crash detail building."""
        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])

        fetcher.fetch_issue_by_number = AsyncMock(side_effect=RuntimeError("timeout"))
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        assert detail is not None
        assert len(detail.children) == 1
        # Title won't be fetched, but the child entry exists
        assert detail.children[0].issue_number == 10


class TestOnChildApproved:
    """Tests for on_child_approved and bundled strategy handling."""

    @pytest.mark.asyncio
    async def test_marks_approved_and_publishes(self, tmp_path: Path) -> None:
        mgr, state, bus, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10, 20])

        await mgr.on_child_approved(100, 10)

        epic = state.get_epic_state(100)
        assert 10 in epic.approved_children
        updates = [e for e in bus.get_history() if e.type == EventType.EPIC_UPDATE]
        assert any(e.data["action"] == "child_approved" for e in updates)

    @pytest.mark.asyncio
    async def test_independent_strategy_no_auto_merge(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="independent"
        )
        await mgr.register_epic(100, "Epic", [10])
        await mgr.on_child_approved(100, 10)

        # Independent strategy should NOT trigger merge
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_released_epic(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, _ = _make_manager(tmp_path, epic_merge_strategy="bundled")
        await mgr.register_epic(100, "Epic", [10])

        # Mark as released before approving
        epic = state.get_epic_state(100)
        epic.released = True
        state.upsert_epic_state(epic)

        await mgr.on_child_approved(100, 10)

        # Should not trigger any merge behavior
        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 0


class TestReleaseData:
    """Tests for release data in epic detail."""

    @pytest.mark.asyncio
    async def test_release_data_included_when_present(self, tmp_path: Path) -> None:
        from models import Release
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "v1.0 Epic", [10])
        await mgr.on_child_completed(100, 10)

        child_10 = IssueFactory.create(
            number=10, title="Done", labels=["hydraflow-fixed"]
        )
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        # Add a release record
        release = Release(
            version="1.0",
            epic_number=100,
            sub_issues=[10],
            status="released",
            released_at="2026-01-01T00:00:00Z",
            tag="v1.0",
        )
        state.upsert_release(release)

        detail = await mgr.get_detail(100)
        assert detail.release is not None
        assert detail.release["version"] == "1.0"
        assert detail.release["tag"] == "v1.0"
        assert detail.release["status"] == "released"

    @pytest.mark.asyncio
    async def test_release_data_none_when_absent(self, tmp_path: Path) -> None:
        from tests.conftest import IssueFactory

        mgr, state, _, prs, fetcher = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [10])

        child_10 = IssueFactory.create(number=10, title="Active", labels=[])
        fetcher.fetch_issue_by_number = AsyncMock(return_value=child_10)
        prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        assert detail.release is None


class TestFindParentEpics:
    """Tests for find_parent_epics."""

    @pytest.mark.asyncio
    async def test_finds_parent_epics(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic A", [10, 20])
        await mgr.register_epic(200, "Epic B", [20, 30])

        parents = mgr.find_parent_epics(20)
        assert set(parents) == {100, 200}

    @pytest.mark.asyncio
    async def test_returns_empty_for_orphan(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic A", [10])

        parents = mgr.find_parent_epics(999)
        assert parents == []
