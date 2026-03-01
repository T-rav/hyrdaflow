"""Tests for epic-aware pipeline with merge coordination (issue #1547)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from events import EventBus, EventType
from models import (
    EpicChildInfo,
    EpicDetail,
    EpicProgress,
    EpicState,
    Task,
    TaskLinkKind,
    parse_task_links,
)
from state import StateTracker
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# TaskLinkKind: BLOCKS / BLOCKED_BY
# ---------------------------------------------------------------------------


class TestBlocksAndBlockedByLinkKind:
    """Tests for the BLOCKS and BLOCKED_BY link kinds."""

    def test_blocks_enum_value(self) -> None:
        assert TaskLinkKind.BLOCKS == "blocks"

    def test_blocked_by_enum_value(self) -> None:
        assert TaskLinkKind.BLOCKED_BY == "blocked_by"

    def test_parse_blocks_pattern(self) -> None:
        links = parse_task_links("This blocks #42.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.BLOCKS
        assert links[0].target_id == 42

    def test_parse_block_singular(self) -> None:
        links = parse_task_links("block #10")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.BLOCKS
        assert links[0].target_id == 10

    def test_parse_blocked_by_pattern(self) -> None:
        links = parse_task_links("This is blocked by #99.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.BLOCKED_BY
        assert links[0].target_id == 99

    def test_parse_blocks_case_insensitive(self) -> None:
        links = parse_task_links("BLOCKS #5")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.BLOCKS

    def test_parse_blocked_by_case_insensitive(self) -> None:
        links = parse_task_links("BLOCKED BY #7")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.BLOCKED_BY

    def test_multiple_blocks_and_blocked_by(self) -> None:
        links = parse_task_links("blocks #1, blocked by #2")

        assert len(links) == 2
        blocks = [lnk for lnk in links if lnk.kind == TaskLinkKind.BLOCKS]
        blocked_by = [lnk for lnk in links if lnk.kind == TaskLinkKind.BLOCKED_BY]
        assert len(blocks) == 1
        assert blocks[0].target_id == 1
        assert len(blocked_by) == 1
        assert blocked_by[0].target_id == 2

    def test_blocks_mixed_with_other_links(self) -> None:
        body = "relates to #10, blocks #20, duplicate of #30"
        links = parse_task_links(body)

        assert len(links) == 3
        kinds = {lnk.kind for lnk in links}
        assert TaskLinkKind.RELATES_TO in kinds
        assert TaskLinkKind.BLOCKS in kinds
        assert TaskLinkKind.DUPLICATES in kinds


# ---------------------------------------------------------------------------
# Task: parent_epic field
# ---------------------------------------------------------------------------


class TestTaskParentEpic:
    """Tests for the Task.parent_epic field."""

    def test_parent_epic_defaults_to_none(self) -> None:
        task = Task(id=1, title="test")
        assert task.parent_epic is None

    def test_parent_epic_can_be_set(self) -> None:
        task = Task(id=1, title="test", parent_epic=42)
        assert task.parent_epic == 42

    def test_parent_epic_mutable(self) -> None:
        task = Task(id=1, title="test")
        task.parent_epic = 100
        assert task.parent_epic == 100


# ---------------------------------------------------------------------------
# EpicState: approved_children and merge_strategy
# ---------------------------------------------------------------------------


class TestEpicStateNewFields:
    """Tests for approved_children and merge_strategy on EpicState."""

    def test_approved_children_defaults_to_empty(self) -> None:
        epic = EpicState(epic_number=1)
        assert epic.approved_children == []

    def test_merge_strategy_defaults_to_independent(self) -> None:
        epic = EpicState(epic_number=1)
        assert epic.merge_strategy == "independent"

    def test_merge_strategy_can_be_set(self) -> None:
        epic = EpicState(epic_number=1, merge_strategy="bundled")
        assert epic.merge_strategy == "bundled"

    def test_approved_children_persistence(self) -> None:
        epic = EpicState(epic_number=1, approved_children=[1, 2, 3])
        assert epic.approved_children == [1, 2, 3]

    def test_released_defaults_to_false(self) -> None:
        epic = EpicState(epic_number=1)
        assert epic.released is False

    def test_released_can_be_set(self) -> None:
        epic = EpicState(epic_number=1, released=True)
        assert epic.released is True


# ---------------------------------------------------------------------------
# EpicProgress: approved, ready_to_merge, merge_strategy
# ---------------------------------------------------------------------------


class TestEpicProgressNewFields:
    """Tests for new fields on EpicProgress."""

    def test_approved_defaults_to_zero(self) -> None:
        progress = EpicProgress(epic_number=1)
        assert progress.approved == 0

    def test_ready_to_merge_defaults_to_false(self) -> None:
        progress = EpicProgress(epic_number=1)
        assert progress.ready_to_merge is False

    def test_merge_strategy_defaults_to_independent(self) -> None:
        progress = EpicProgress(epic_number=1)
        assert progress.merge_strategy == "independent"


# ---------------------------------------------------------------------------
# EpicChildInfo: is_approved field
# ---------------------------------------------------------------------------


class TestEpicChildInfoApproved:
    """Tests for the is_approved field on EpicChildInfo."""

    def test_is_approved_defaults_to_false(self) -> None:
        child = EpicChildInfo(issue_number=1)
        assert child.is_approved is False

    def test_is_approved_can_be_set(self) -> None:
        child = EpicChildInfo(issue_number=1, is_approved=True)
        assert child.is_approved is True


# ---------------------------------------------------------------------------
# EpicDetail: approved, ready_to_merge, merge_strategy
# ---------------------------------------------------------------------------


class TestEpicDetailNewFields:
    """Tests for new fields on EpicDetail."""

    def test_approved_defaults_to_zero(self) -> None:
        detail = EpicDetail(epic_number=1)
        assert detail.approved == 0

    def test_ready_to_merge_defaults_to_false(self) -> None:
        detail = EpicDetail(epic_number=1)
        assert detail.ready_to_merge is False

    def test_merge_strategy_defaults_to_independent(self) -> None:
        detail = EpicDetail(epic_number=1)
        assert detail.merge_strategy == "independent"


# ---------------------------------------------------------------------------
# StateTracker: mark_epic_child_approved and get_epic_progress
# ---------------------------------------------------------------------------


class TestStateTrackerEpicApproval:
    """Tests for StateTracker epic approval methods."""

    def test_mark_epic_child_approved(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        epic = EpicState(
            epic_number=100,
            child_issues=[1, 2, 3],
        )
        state.upsert_epic_state(epic)

        state.mark_epic_child_approved(100, 1)

        epic_state = state.get_epic_state(100)
        assert epic_state is not None
        assert 1 in epic_state.approved_children

    def test_mark_epic_child_approved_idempotent(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        epic = EpicState(epic_number=100, child_issues=[1, 2])
        state.upsert_epic_state(epic)

        state.mark_epic_child_approved(100, 1)
        state.mark_epic_child_approved(100, 1)

        epic_state = state.get_epic_state(100)
        assert epic_state is not None
        assert epic_state.approved_children.count(1) == 1

    def test_mark_epic_child_approved_missing_epic(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        # Should not raise
        state.mark_epic_child_approved(999, 1)

    def test_get_epic_progress_empty(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        result = state.get_epic_progress(999)
        assert result == {}

    def test_get_epic_progress_basic(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        epic = EpicState(
            epic_number=100,
            child_issues=[1, 2, 3, 4, 5],
            completed_children=[1, 2, 3],
            approved_children=[4],
            merge_strategy="bundled",
        )
        state.upsert_epic_state(epic)

        result = state.get_epic_progress(100)

        assert result["total"] == 5
        assert result["merged"] == 3
        assert result["approved"] == 1
        assert result["merge_strategy"] == "bundled"
        assert result["ready_to_merge"] is False  # child #5 not approved

    def test_get_epic_progress_ready_to_merge(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        epic = EpicState(
            epic_number=100,
            child_issues=[1, 2, 3],
            completed_children=[1],
            approved_children=[2, 3],
            merge_strategy="bundled",
        )
        state.upsert_epic_state(epic)

        result = state.get_epic_progress(100)

        assert result["ready_to_merge"] is True

    def test_get_epic_progress_not_ready_for_independent(self, tmp_path: Path) -> None:
        """Independent strategy is never ready_to_merge even when all approved."""
        state = StateTracker(tmp_path / "state.json")
        epic = EpicState(
            epic_number=100,
            child_issues=[1, 2],
            approved_children=[1, 2],
            merge_strategy="independent",
        )
        state.upsert_epic_state(epic)

        result = state.get_epic_progress(100)

        assert result["ready_to_merge"] is False

    def test_get_epic_progress_not_ready_when_failed(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        epic = EpicState(
            epic_number=100,
            child_issues=[1, 2, 3],
            completed_children=[1],
            approved_children=[2],
            failed_children=[3],
        )
        state.upsert_epic_state(epic)

        result = state.get_epic_progress(100)

        assert result["ready_to_merge"] is False


# ---------------------------------------------------------------------------
# EpicManager: on_child_approved and merge coordination
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path, **config_kw):
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


class TestOnChildApproved:
    """Tests for EpicManager.on_child_approved."""

    @pytest.mark.asyncio
    async def test_marks_child_approved(self, tmp_path: Path) -> None:
        mgr, state, bus, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [1, 2, 3])

        await mgr.on_child_approved(100, 1)

        epic = state.get_epic_state(100)
        assert epic is not None
        assert 1 in epic.approved_children

    @pytest.mark.asyncio
    async def test_publishes_child_approved_event(self, tmp_path: Path) -> None:
        mgr, _, bus, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [1, 2])

        await mgr.on_child_approved(100, 1)

        events = [e for e in bus.get_history() if e.type == EventType.EPIC_UPDATE]
        assert any(e.data["action"] == "child_approved" for e in events)

    @pytest.mark.asyncio
    async def test_independent_strategy_no_bundle_check(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [1, 2])

        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        # Independent strategy: no EPIC_READY event
        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 0
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_bundled_strategy_triggers_when_all_approved(
        self, tmp_path: Path
    ) -> None:
        mgr, state, bus, prs, _ = _make_manager(tmp_path, epic_merge_strategy="bundled")
        await mgr.register_epic(100, "Epic", [1, 2])

        await mgr.on_child_approved(100, 1)
        # After first approval, should not trigger
        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 0

        await mgr.on_child_approved(100, 2)
        # After all approved, should trigger EPIC_READY
        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 1
        assert ready_events[0].data["strategy"] == "bundled"

    @pytest.mark.asyncio
    async def test_bundled_hitl_strategy_triggers_when_all_approved(
        self, tmp_path: Path
    ) -> None:
        mgr, state, bus, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1, 2])

        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 1
        assert ready_events[0].data["strategy"] == "bundled_hitl"

    @pytest.mark.asyncio
    async def test_ordered_strategy_triggers_when_all_approved(
        self, tmp_path: Path
    ) -> None:
        mgr, state, bus, prs, _ = _make_manager(tmp_path, epic_merge_strategy="ordered")
        await mgr.register_epic(100, "Epic", [1, 2])

        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 1
        assert ready_events[0].data["strategy"] == "ordered"

    @pytest.mark.asyncio
    async def test_bundled_with_completed_children(self, tmp_path: Path) -> None:
        """Already-merged children count toward readiness."""
        mgr, state, bus, prs, _ = _make_manager(tmp_path, epic_merge_strategy="bundled")
        await mgr.register_epic(100, "Epic", [1, 2, 3])
        await mgr.on_child_completed(100, 1)

        await mgr.on_child_approved(100, 2)
        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 0  # child 3 not approved

        await mgr.on_child_approved(100, 3)
        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 1

    @pytest.mark.asyncio
    async def test_failed_child_blocks_readiness(self, tmp_path: Path) -> None:
        mgr, state, bus, prs, _ = _make_manager(tmp_path, epic_merge_strategy="bundled")
        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_failed(100, 1)

        await mgr.on_child_approved(100, 2)

        ready_events = [e for e in bus.get_history() if e.type == EventType.EPIC_READY]
        assert len(ready_events) == 0

    @pytest.mark.asyncio
    async def test_already_released_skips_dispatch(self, tmp_path: Path) -> None:
        """Duplicate on_child_approved after a successful release must not re-trigger
        bundled handlers or post spurious GitHub comments."""
        mgr, state, bus, prs, _ = _make_manager(tmp_path, epic_merge_strategy="bundled")
        prs.find_pr_for_issue = AsyncMock(side_effect=[10, 20])
        prs.merge_pr = AsyncMock(return_value=True)

        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)  # triggers auto-release

        # Reset mock call counts after the first (legitimate) release
        prs.post_comment.reset_mock()
        prs.merge_pr.reset_mock()

        # Simulate a duplicate approval event after the epic is already released
        await mgr.on_child_approved(100, 2)

        # No additional comments or merge attempts
        prs.post_comment.assert_not_called()
        prs.merge_pr.assert_not_called()


# ---------------------------------------------------------------------------
# EpicManager: find_parent_epics
# ---------------------------------------------------------------------------


class TestFindParentEpics:
    """Tests for EpicManager.find_parent_epics."""

    @pytest.mark.asyncio
    async def test_finds_parent(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic A", [1, 2, 3])
        await mgr.register_epic(200, "Epic B", [4, 5])

        assert mgr.find_parent_epics(2) == [100]
        assert mgr.find_parent_epics(4) == [200]

    @pytest.mark.asyncio
    async def test_no_parent(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic A", [1, 2])

        assert mgr.find_parent_epics(99) == []

    @pytest.mark.asyncio
    async def test_multiple_parents(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic A", [1, 2])
        await mgr.register_epic(200, "Epic B", [1, 3])

        parents = mgr.find_parent_epics(1)
        assert 100 in parents
        assert 200 in parents


# ---------------------------------------------------------------------------
# EpicManager: release_epic
# ---------------------------------------------------------------------------


class TestReleaseEpic:
    """Tests for EpicManager.release_epic."""

    @pytest.mark.asyncio
    async def test_release_not_found(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path)
        result = await mgr.release_epic(999)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_release_not_ready(self, tmp_path: Path) -> None:
        mgr, _, _, _, _ = _make_manager(tmp_path, epic_merge_strategy="bundled")
        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_approved(100, 1)
        # Only 1 of 2 approved
        result = await mgr.release_epic(100)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_release_merges_prs(self, tmp_path: Path) -> None:
        # Use bundled_hitl so on_child_approved doesn't auto-merge
        mgr, state, bus, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        prs.find_pr_for_issue = AsyncMock(side_effect=[10, 20])
        prs.merge_pr = AsyncMock(return_value=True)

        result = await mgr.release_epic(100)
        assert result["epic_number"] == 100
        assert len(result["merges"]) == 2
        assert all(m["status"] == "merged" for m in result["merges"])

    @pytest.mark.asyncio
    async def test_release_handles_no_pr(self, tmp_path: Path) -> None:
        """Missing PR halts the bundle rather than silently skipping."""
        mgr, _, _, prs, _ = _make_manager(tmp_path, epic_merge_strategy="bundled_hitl")
        await mgr.register_epic(100, "Epic", [1])
        await mgr.on_child_approved(100, 1)

        prs.find_pr_for_issue = AsyncMock(return_value=0)

        result = await mgr.release_epic(100)
        assert result["merges"][0]["status"] == "no_pr"
        assert "error" in result  # bundle halts — doesn't mark as released
        assert "no PR" in result["error"]

    @pytest.mark.asyncio
    async def test_release_no_pr_does_not_set_released(self, tmp_path: Path) -> None:
        """A missing PR halts and leaves released=False so the operator can retry."""
        mgr, state, _, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1])
        await mgr.on_child_approved(100, 1)

        prs.find_pr_for_issue = AsyncMock(return_value=0)

        await mgr.release_epic(100)

        epic = state.get_epic_state(100)
        assert epic is not None
        assert epic.released is False

    @pytest.mark.asyncio
    async def test_release_handles_merge_failure(self, tmp_path: Path) -> None:
        mgr, _, _, prs, _ = _make_manager(tmp_path, epic_merge_strategy="bundled_hitl")
        await mgr.register_epic(100, "Epic", [1])
        await mgr.on_child_approved(100, 1)

        prs.find_pr_for_issue = AsyncMock(return_value=10)
        prs.merge_pr = AsyncMock(return_value=False)

        result = await mgr.release_epic(100)
        assert result["merges"][0]["status"] == "failed"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_release_handles_merge_exception(self, tmp_path: Path) -> None:
        """Exception during merge halts the bundle and returns error."""
        mgr, state, _, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1])
        await mgr.on_child_approved(100, 1)

        prs.find_pr_for_issue = AsyncMock(return_value=10)
        prs.merge_pr = AsyncMock(side_effect=RuntimeError("network error"))

        result = await mgr.release_epic(100)

        assert result["merges"][0]["status"] == "error"
        assert "error" in result
        assert "exception" in result["error"]
        # Should not mark as released so operator can retry
        epic = state.get_epic_state(100)
        assert epic is not None
        assert epic.released is False

    @pytest.mark.asyncio
    async def test_release_halts_on_second_child_failure(self, tmp_path: Path) -> None:
        """When the second child fails, the first is already merged but we halt."""
        mgr, state, _, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        prs.find_pr_for_issue = AsyncMock(side_effect=[10, 20])
        prs.merge_pr = AsyncMock(side_effect=[True, False])

        result = await mgr.release_epic(100)

        assert len(result["merges"]) == 2
        assert result["merges"][0]["status"] == "merged"
        assert result["merges"][1]["status"] == "failed"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_release_idempotent_second_call_rejected(
        self, tmp_path: Path
    ) -> None:
        """Calling release_epic twice returns an error on the second call."""
        mgr, state, _, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        prs.find_pr_for_issue = AsyncMock(side_effect=[10, 20])
        prs.merge_pr = AsyncMock(return_value=True)

        first = await mgr.release_epic(100)
        assert "error" not in first

        second = await mgr.release_epic(100)
        assert "error" in second
        assert "already" in second["error"]

    @pytest.mark.asyncio
    async def test_release_sets_released_flag(self, tmp_path: Path) -> None:
        """Successful release marks epic as released in state."""
        mgr, state, _, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1])
        await mgr.on_child_approved(100, 1)

        prs.find_pr_for_issue = AsyncMock(return_value=10)
        prs.merge_pr = AsyncMock(return_value=True)

        await mgr.release_epic(100)

        epic = state.get_epic_state(100)
        assert epic is not None
        assert epic.released is True

    @pytest.mark.asyncio
    async def test_release_failure_does_not_set_released(self, tmp_path: Path) -> None:
        """Failed release does NOT mark epic as released (can retry)."""
        mgr, state, _, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1])
        await mgr.on_child_approved(100, 1)

        prs.find_pr_for_issue = AsyncMock(return_value=10)
        prs.merge_pr = AsyncMock(return_value=False)

        await mgr.release_epic(100)

        epic = state.get_epic_state(100)
        assert epic is not None
        assert epic.released is False

    @pytest.mark.asyncio
    async def test_bundled_auto_trigger_sets_released(self, tmp_path: Path) -> None:
        """Bundled auto-trigger marks epic as released after merge."""
        mgr, state, _, prs, _ = _make_manager(tmp_path, epic_merge_strategy="bundled")
        prs.find_pr_for_issue = AsyncMock(side_effect=[10, 20])
        prs.merge_pr = AsyncMock(return_value=True)

        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        # Auto-trigger should have merged and set released
        epic = state.get_epic_state(100)
        assert epic is not None
        assert epic.released is True

    @pytest.mark.asyncio
    async def test_bundled_auto_trigger_blocks_manual_release(
        self, tmp_path: Path
    ) -> None:
        """After bundled auto-trigger, manual release_epic is rejected."""
        mgr, state, _, prs, _ = _make_manager(tmp_path, epic_merge_strategy="bundled")
        prs.find_pr_for_issue = AsyncMock(side_effect=[10, 20])
        prs.merge_pr = AsyncMock(return_value=True)

        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        result = await mgr.release_epic(100)
        assert "error" in result
        assert "already" in result["error"]


# ---------------------------------------------------------------------------
# EpicManager: get_progress with approval tracking
# ---------------------------------------------------------------------------


class TestEpicProgressApprovalTracking:
    """Tests for EpicManager.get_progress with approved/ready_to_merge."""

    @pytest.mark.asyncio
    async def test_progress_includes_approved_count(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path, epic_merge_strategy="bundled")
        await mgr.register_epic(100, "Epic", [1, 2, 3])
        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        progress = mgr.get_progress(100)
        assert progress is not None
        assert progress.approved == 2
        assert progress.ready_to_merge is False

    @pytest.mark.asyncio
    async def test_progress_ready_when_all_approved(self, tmp_path: Path) -> None:
        # Use bundled_hitl so on_child_approved does NOT auto-trigger a merge;
        # that lets us inspect the ready_to_merge state before any release occurs.
        mgr, state, _, _, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        progress = mgr.get_progress(100)
        assert progress is not None
        assert progress.ready_to_merge is True
        assert progress.merge_strategy == "bundled_hitl"

    @pytest.mark.asyncio
    async def test_progress_not_ready_for_independent(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_approved(100, 1)
        await mgr.on_child_approved(100, 2)

        progress = mgr.get_progress(100)
        assert progress is not None
        assert progress.ready_to_merge is False  # independent = never ready

    @pytest.mark.asyncio
    async def test_detail_includes_is_approved(self, tmp_path: Path) -> None:
        mgr, state, _, _, fetcher = _make_manager(
            tmp_path, epic_merge_strategy="bundled"
        )
        await mgr.register_epic(100, "Epic", [1, 2])
        await mgr.on_child_approved(100, 1)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        detail = await mgr.get_detail(100)
        assert detail is not None
        child_1 = next(c for c in detail.children if c.issue_number == 1)
        child_2 = next(c for c in detail.children if c.issue_number == 2)
        assert child_1.is_approved is True
        assert child_2.is_approved is False
        assert detail.approved == 1
        assert detail.merge_strategy == "bundled"

    @pytest.mark.asyncio
    async def test_ready_to_merge_false_after_release(self, tmp_path: Path) -> None:
        """ready_to_merge should be False once the epic has been released."""
        mgr, state, _, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1])
        await mgr.on_child_approved(100, 1)

        # Verify it's True before release
        progress = mgr.get_progress(100)
        assert progress is not None
        assert progress.ready_to_merge is True

        prs.find_pr_for_issue = AsyncMock(return_value=10)
        prs.merge_pr = AsyncMock(return_value=True)
        await mgr.release_epic(100)

        # Should be False after release
        progress = mgr.get_progress(100)
        assert progress is not None
        assert progress.ready_to_merge is False


# ---------------------------------------------------------------------------
# Config: epic_merge_strategy
# ---------------------------------------------------------------------------


class TestEpicMergeStrategyConfig:
    """Tests for the epic_merge_strategy config field."""

    def test_default_is_independent(self) -> None:
        config = ConfigFactory.create()
        assert config.epic_merge_strategy == "independent"

    def test_bundled_strategy(self) -> None:
        config = ConfigFactory.create(epic_merge_strategy="bundled")
        assert config.epic_merge_strategy == "bundled"

    def test_bundled_hitl_strategy(self) -> None:
        config = ConfigFactory.create(epic_merge_strategy="bundled_hitl")
        assert config.epic_merge_strategy == "bundled_hitl"

    def test_ordered_strategy(self) -> None:
        config = ConfigFactory.create(epic_merge_strategy="ordered")
        assert config.epic_merge_strategy == "ordered"


# ---------------------------------------------------------------------------
# EpicManager: register_epic inherits merge_strategy from config
# ---------------------------------------------------------------------------


class TestRegisterEpicMergeStrategy:
    """Tests for merge_strategy propagation during epic registration."""

    @pytest.mark.asyncio
    async def test_inherits_config_strategy(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1, 2])

        epic = state.get_epic_state(100)
        assert epic is not None
        assert epic.merge_strategy == "bundled_hitl"

    @pytest.mark.asyncio
    async def test_default_strategy_is_independent(self, tmp_path: Path) -> None:
        mgr, state, _, _, _ = _make_manager(tmp_path)
        await mgr.register_epic(100, "Epic", [1, 2])

        epic = state.get_epic_state(100)
        assert epic is not None
        assert epic.merge_strategy == "independent"


# ---------------------------------------------------------------------------
# PostMergeHandler: defer merge for bundled strategies
# ---------------------------------------------------------------------------


class TestPostMergeHandlerDeferMerge:
    """Tests for _should_defer_merge and _notify_epic_approval."""

    def _make_handler(self, tmp_path: Path, epic_merge_strategy: str = "independent"):
        from epic import EpicManager
        from post_merge_handler import PostMergeHandler

        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_merge_strategy=epic_merge_strategy,
        )
        state = StateTracker(config.state_file)
        prs = AsyncMock()
        bus = EventBus()
        fetcher = AsyncMock()
        epic_manager = EpicManager(config, state, prs, fetcher, bus)
        handler = PostMergeHandler(
            config=config,
            state=state,
            prs=prs,
            event_bus=bus,
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
            epic_manager=epic_manager,
        )
        return handler, state, epic_manager, prs, bus

    def test_should_not_defer_when_independent(self, tmp_path: Path) -> None:
        handler, state, epic_manager, _, _ = self._make_handler(tmp_path)
        # Register epic with independent strategy
        epic = EpicState(
            epic_number=100,
            child_issues=[1, 2],
            merge_strategy="independent",
        )
        state.upsert_epic_state(epic)

        assert handler._should_defer_merge(1) is False

    def test_should_defer_when_bundled(self, tmp_path: Path) -> None:
        handler, state, epic_manager, _, _ = self._make_handler(
            tmp_path, epic_merge_strategy="bundled"
        )
        epic = EpicState(
            epic_number=100,
            child_issues=[1, 2],
            merge_strategy="bundled",
        )
        state.upsert_epic_state(epic)

        assert handler._should_defer_merge(1) is True

    def test_should_not_defer_when_not_in_epic(self, tmp_path: Path) -> None:
        handler, state, _, _, _ = self._make_handler(
            tmp_path, epic_merge_strategy="bundled"
        )
        # No epic registered for issue #99
        assert handler._should_defer_merge(99) is False

    @pytest.mark.asyncio
    async def test_notify_epic_approval(self, tmp_path: Path) -> None:
        handler, state, epic_manager, _, bus = self._make_handler(
            tmp_path, epic_merge_strategy="bundled"
        )
        epic = EpicState(
            epic_number=100,
            child_issues=[1, 2],
            merge_strategy="bundled",
        )
        state.upsert_epic_state(epic)

        await handler._notify_epic_approval(1)

        epic_state = state.get_epic_state(100)
        assert epic_state is not None
        assert 1 in epic_state.approved_children


# ---------------------------------------------------------------------------
# TriagePhase: parent_epic enrichment
# ---------------------------------------------------------------------------


class TestTriageParentEpicEnrichment:
    """Tests for TriagePhase._enrich_parent_epic."""

    def _make_triage_phase(
        self, tmp_path: Path, epic_merge_strategy: str = "independent"
    ):
        from epic import EpicManager
        from triage_phase import TriagePhase

        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_merge_strategy=epic_merge_strategy,
        )
        state = StateTracker(config.state_file)
        bus = EventBus()
        prs = AsyncMock()
        fetcher = AsyncMock()
        epic_manager = EpicManager(config, state, prs, fetcher, bus)
        store = MagicMock()
        triage_runner = AsyncMock()
        stop_event = MagicMock()

        phase = TriagePhase(
            config=config,
            state=state,
            store=store,
            triage=triage_runner,
            prs=prs,
            event_bus=bus,
            stop_event=stop_event,
            epic_manager=epic_manager,
        )
        return phase, state, epic_manager

    @pytest.mark.asyncio
    async def test_enrich_sets_parent_epic(self, tmp_path: Path) -> None:
        phase, state, epic_manager = self._make_triage_phase(tmp_path)
        # Register epic
        epic = EpicState(
            epic_number=100,
            child_issues=[1, 2, 3],
        )
        state.upsert_epic_state(epic)

        task = Task(id=2, title="Sub-issue")
        phase._enrich_parent_epic(task)

        assert task.parent_epic == 100

    @pytest.mark.asyncio
    async def test_enrich_no_parent(self, tmp_path: Path) -> None:
        phase, state, _ = self._make_triage_phase(tmp_path)

        task = Task(id=99, title="Standalone issue")
        phase._enrich_parent_epic(task)

        assert task.parent_epic is None

    def test_enrich_without_epic_manager(self, tmp_path: Path) -> None:
        from triage_phase import TriagePhase

        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        state = StateTracker(config.state_file)
        bus = EventBus()
        prs = AsyncMock()
        store = MagicMock()
        triage_runner = AsyncMock()
        stop_event = MagicMock()

        phase = TriagePhase(
            config=config,
            state=state,
            store=store,
            triage=triage_runner,
            prs=prs,
            event_bus=bus,
            stop_event=stop_event,
            epic_manager=None,
        )

        task = Task(id=1, title="Issue")
        phase._enrich_parent_epic(task)
        assert task.parent_epic is None


# ---------------------------------------------------------------------------
# EventType: EPIC_READY
# ---------------------------------------------------------------------------


class TestReleaseEpicConcurrency:
    """Tests for concurrent-call safety of release_epic."""

    @pytest.mark.asyncio
    async def test_concurrent_release_calls_merge_prs_once(
        self, tmp_path: Path
    ) -> None:
        """Two concurrent release_epic calls must not double-merge PRs."""
        import asyncio

        mgr, state, _, prs, _ = _make_manager(
            tmp_path, epic_merge_strategy="bundled_hitl"
        )
        await mgr.register_epic(100, "Epic", [1])
        await mgr.on_child_approved(100, 1)

        prs.find_pr_for_issue = AsyncMock(return_value=10)
        prs.merge_pr = AsyncMock(return_value=True)

        # Fire two concurrent release calls
        results = await asyncio.gather(
            mgr.release_epic(100),
            mgr.release_epic(100),
        )

        # Exactly one should succeed; the other must return an error
        successes = [r for r in results if "error" not in r]
        errors = [r for r in results if "error" in r]
        assert len(successes) == 1
        assert len(errors) == 1
        # merge_pr called exactly once (not twice)
        assert prs.merge_pr.call_count == 1


class TestEpicReadyEventType:
    """Tests for the EPIC_READY event type."""

    def test_epic_ready_exists(self) -> None:
        assert hasattr(EventType, "EPIC_READY")
        assert EventType.EPIC_READY == "epic_ready"
