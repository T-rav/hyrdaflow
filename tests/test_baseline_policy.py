"""Tests for baseline policy enforcement, approval, audit trail, and rollback."""

from __future__ import annotations

from pathlib import Path

import pytest

from baseline_policy import BaselinePolicy, _glob_match
from events import EventBus, EventType
from models import (
    BaselineApprovalResult,
    BaselineAuditRecord,
    BaselineChangeType,
)
from state import StateTracker
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config(tmp_path: Path):
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        state_file=tmp_path / "state.json",
        baseline_approval_required=True,
        baseline_approvers=["alice", "bob"],
        baseline_snapshot_patterns=[
            "**/__snapshots__/**",
            "**/*.snap.png",
            "**/*.baseline.png",
        ],
    )


@pytest.fixture
def state(tmp_path: Path):
    return StateTracker(tmp_path / "state.json")


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def policy(config, state, bus):
    return BaselinePolicy(config=config, state=state, event_bus=bus)


# ---------------------------------------------------------------------------
# _glob_match
# ---------------------------------------------------------------------------


class TestGlobMatch:
    """Tests for _glob_match helper with ** glob support."""

    def test_standard_fnmatch_still_works(self):
        assert _glob_match("ui/dashboard.snap.png", "**/*.snap.png") is True

    def test_double_star_leading_matches_zero_dirs(self):
        """** at the start should match files in the root directory."""
        assert _glob_match("dashboard.snap.png", "**/*.snap.png") is True

    def test_double_star_trailing_matches_zero_dirs(self):
        """** at the end should match files without trailing path segments."""
        assert _glob_match("__snapshots__/file.png", "**/__snapshots__/**") is True

    def test_double_star_both_sides_zero_dirs(self):
        """** on both sides should match a single-segment __snapshots__ path."""
        assert _glob_match("__snapshots__/file.png", "**/__snapshots__/**") is True

    def test_deep_nested_path(self):
        assert _glob_match("a/b/c/__snapshots__/d.png", "**/__snapshots__/**") is True

    def test_no_match(self):
        assert _glob_match("src/app.py", "**/*.snap.png") is False

    def test_exact_filename_pattern(self):
        assert _glob_match("file.golden", "*.golden") is True

    def test_nested_with_no_double_star(self):
        assert _glob_match("a/file.golden", "*.golden") is True


# ---------------------------------------------------------------------------
# detect_baseline_changes
# ---------------------------------------------------------------------------


class TestDetectBaselineChanges:
    """Tests for BaselinePolicy.detect_baseline_changes."""

    def test_no_baseline_files(self, policy: BaselinePolicy):
        result = policy.detect_baseline_changes(["src/app.py", "README.md"])
        assert result == []

    def test_snapshot_directory_match(self, policy: BaselinePolicy):
        files = [
            "src/app.py",
            "tests/__snapshots__/home.snap.png",
            "tests/__snapshots__/login.snap.png",
        ]
        result = policy.detect_baseline_changes(files)
        assert len(result) == 2
        assert "tests/__snapshots__/home.snap.png" in result
        assert "tests/__snapshots__/login.snap.png" in result

    def test_snap_png_extension_match(self, policy: BaselinePolicy):
        files = ["ui/dashboard.snap.png", "src/main.py"]
        result = policy.detect_baseline_changes(files)
        assert result == ["ui/dashboard.snap.png"]

    def test_baseline_png_extension_match(self, policy: BaselinePolicy):
        files = ["visuals/header.baseline.png", "src/config.py"]
        result = policy.detect_baseline_changes(files)
        assert result == ["visuals/header.baseline.png"]

    def test_no_duplicates(self, policy: BaselinePolicy):
        # A file that matches two patterns should only appear once
        files = ["tests/__snapshots__/widget.snap.png"]
        result = policy.detect_baseline_changes(files)
        assert result == ["tests/__snapshots__/widget.snap.png"]

    def test_root_level_snap_file(self, policy: BaselinePolicy):
        """A .snap.png file in the root dir should match **/*.snap.png."""
        files = ["widget.snap.png", "src/main.py"]
        result = policy.detect_baseline_changes(files)
        assert result == ["widget.snap.png"]

    def test_root_level_snapshots_dir(self, policy: BaselinePolicy):
        """__snapshots__/ at the root should match **/__snapshots__/**."""
        files = ["__snapshots__/home.snap.png"]
        result = policy.detect_baseline_changes(files)
        assert result == ["__snapshots__/home.snap.png"]

    def test_empty_file_list(self, policy: BaselinePolicy):
        result = policy.detect_baseline_changes([])
        assert result == []

    def test_custom_patterns(self, tmp_path: Path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            baseline_snapshot_patterns=["*.golden"],
        )
        st = StateTracker(tmp_path / "state.json")
        bp = BaselinePolicy(config=cfg, state=st, event_bus=EventBus())
        result = bp.detect_baseline_changes(["output.golden", "main.py"])
        assert result == ["output.golden"]


# ---------------------------------------------------------------------------
# check_approval
# ---------------------------------------------------------------------------


class TestCheckApproval:
    """Tests for BaselinePolicy.check_approval."""

    @pytest.mark.asyncio
    async def test_no_baseline_files_auto_approved(self, policy: BaselinePolicy):
        result = await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["src/app.py"],
            pr_approvers=["charlie"],
        )
        assert result.approved is True
        assert result.requires_approval is False
        assert result.changed_files == []

    @pytest.mark.asyncio
    async def test_approval_required_with_designated_approver(
        self, policy: BaselinePolicy
    ):
        result = await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["alice"],
        )
        assert result.approved is True
        assert result.requires_approval is True
        assert result.approver == "alice"
        assert "home.snap.png" in result.changed_files[0]

    @pytest.mark.asyncio
    async def test_approval_denied_without_designated_approver(
        self, policy: BaselinePolicy
    ):
        result = await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["charlie"],  # Not in baseline_approvers
        )
        assert result.approved is False
        assert result.requires_approval is True
        assert result.approver == ""

    @pytest.mark.asyncio
    async def test_approval_denied_with_no_approvers(self, policy: BaselinePolicy):
        result = await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=[],
        )
        assert result.approved is False
        assert result.requires_approval is True

    @pytest.mark.asyncio
    async def test_approval_not_required_by_policy(self, tmp_path: Path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            baseline_approval_required=False,
        )
        st = StateTracker(tmp_path / "state.json")
        bp = BaselinePolicy(config=cfg, state=st, event_bus=EventBus())
        result = await bp.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=[],
        )
        assert result.approved is True
        assert result.requires_approval is False

    @pytest.mark.asyncio
    async def test_approval_not_required_still_records_audit(self, tmp_path: Path):
        """Audit trail must be written even when approval is not required."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            baseline_approval_required=False,
        )
        st = StateTracker(tmp_path / "state.json")
        bp = BaselinePolicy(config=cfg, state=st, event_bus=EventBus())
        await bp.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=[],
            commit_sha="abc123",
        )
        records = st.get_baseline_audit(42)
        assert len(records) == 1
        assert records[0].pr_number == 101
        assert records[0].change_type == BaselineChangeType.INITIAL
        assert "auto-approved" in records[0].reason.lower()
        assert records[0].commit_sha == "abc123"

    @pytest.mark.asyncio
    async def test_approval_not_required_publishes_event(self, tmp_path: Path):
        """BASELINE_UPDATE event must be published even when approval is not required."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            baseline_approval_required=False,
        )
        st = StateTracker(tmp_path / "state.json")
        bus = EventBus()
        bp = BaselinePolicy(config=cfg, state=st, event_bus=bus)
        queue = bus.subscribe()
        await bp.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=[],
        )
        event = queue.get_nowait()
        assert event.type == EventType.BASELINE_UPDATE
        assert event.data["pr_number"] == 101
        assert event.data["approved"] is True

    @pytest.mark.asyncio
    async def test_approval_not_required_second_record_uses_update_type(
        self, tmp_path: Path
    ):
        """Second baseline record when approval not required should use UPDATE type."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            baseline_approval_required=False,
        )
        st = StateTracker(tmp_path / "state.json")
        bp = BaselinePolicy(config=cfg, state=st, event_bus=EventBus())
        await bp.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=[],
        )
        await bp.check_approval(
            pr_number=102,
            issue_number=42,
            changed_files=["tests/__snapshots__/login.snap.png"],
            pr_approvers=[],
        )
        records = st.get_baseline_audit(42)
        assert len(records) == 2
        assert records[0].change_type == BaselineChangeType.INITIAL
        assert records[1].change_type == BaselineChangeType.UPDATE

    @pytest.mark.asyncio
    async def test_empty_approvers_list_accepts_any(self, tmp_path: Path):
        """When baseline_approvers is empty, any PR approver is accepted."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            baseline_approval_required=True,
            baseline_approvers=[],
        )
        st = StateTracker(tmp_path / "state.json")
        bp = BaselinePolicy(config=cfg, state=st, event_bus=EventBus())
        result = await bp.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["anyone"],
        )
        assert result.approved is True
        assert result.approver == "anyone"

    @pytest.mark.asyncio
    async def test_publishes_event_on_check(
        self, policy: BaselinePolicy, bus: EventBus
    ):
        queue = bus.subscribe()
        await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["alice"],
        )
        event = queue.get_nowait()
        assert event.type == EventType.BASELINE_UPDATE
        assert event.data["pr_number"] == 101
        assert event.data["approved"] is True

    @pytest.mark.asyncio
    async def test_publishes_event_on_denial(
        self, policy: BaselinePolicy, bus: EventBus
    ):
        """BASELINE_UPDATE event must be published even when approval is denied."""
        queue = bus.subscribe()
        await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["charlie"],  # Not in baseline_approvers
        )
        event = queue.get_nowait()
        assert event.type == EventType.BASELINE_UPDATE
        assert event.data["pr_number"] == 101
        assert event.data["approved"] is False
        assert event.data["approver"] == ""

    @pytest.mark.asyncio
    async def test_first_audit_record_uses_initial_type(
        self, policy: BaselinePolicy, state: StateTracker
    ):
        """First baseline record for an issue should use INITIAL change type."""
        await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["alice"],
        )
        records = state.get_baseline_audit(42)
        assert len(records) == 1
        assert records[0].approver == "alice"
        assert records[0].change_type == BaselineChangeType.INITIAL

    @pytest.mark.asyncio
    async def test_subsequent_record_uses_update_type(
        self, policy: BaselinePolicy, state: StateTracker
    ):
        """Second baseline record for an issue should use UPDATE change type."""
        await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["alice"],
        )
        await policy.check_approval(
            pr_number=102,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["bob"],
        )
        records = state.get_baseline_audit(42)
        assert len(records) == 2
        assert records[0].change_type == BaselineChangeType.INITIAL
        assert records[1].change_type == BaselineChangeType.UPDATE

    @pytest.mark.asyncio
    async def test_commit_sha_recorded_in_audit(
        self, policy: BaselinePolicy, state: StateTracker
    ):
        """commit_sha should be stored in the audit record."""
        await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["alice"],
            commit_sha="abc123def456",
        )
        records = state.get_baseline_audit(42)
        assert len(records) == 1
        assert records[0].commit_sha == "abc123def456"

    @pytest.mark.asyncio
    async def test_denial_is_recorded_in_audit(
        self, policy: BaselinePolicy, state: StateTracker
    ):
        """Denied baseline change attempts must be persistently recorded for audit."""
        await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["charlie"],
        )
        records = state.get_baseline_audit(42)
        assert len(records) == 1
        assert records[0].approver == ""
        assert "denied" in records[0].reason.lower()
        assert records[0].change_type == BaselineChangeType.INITIAL


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


class TestRollback:
    """Tests for BaselinePolicy.rollback."""

    @pytest.mark.asyncio
    async def test_rollback_records_audit(
        self, policy: BaselinePolicy, state: StateTracker
    ):
        # First record an update
        await policy.check_approval(
            pr_number=100,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["alice"],
        )

        # Now rollback
        record = await policy.rollback(
            issue_number=42,
            pr_number=101,
            approver="bob",
            reason="Bad baseline — visual regression",
        )

        assert record.change_type == BaselineChangeType.ROLLBACK
        assert record.approver == "bob"
        assert record.reason == "Bad baseline — visual regression"
        assert "home.snap.png" in record.changed_files[0]

    @pytest.mark.asyncio
    async def test_rollback_publishes_event(
        self, policy: BaselinePolicy, bus: EventBus
    ):
        # Initial update
        await policy.check_approval(
            pr_number=100,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["alice"],
        )

        queue = bus.subscribe()
        await policy.rollback(
            issue_number=42,
            pr_number=101,
            approver="bob",
            reason="regression",
        )
        event = queue.get_nowait()
        assert event.type == EventType.BASELINE_UPDATE
        assert event.data["rollback"] is True

    @pytest.mark.asyncio
    async def test_rollback_without_prior_update(
        self, policy: BaselinePolicy, state: StateTracker
    ):
        """Rollback with no prior update should still create a record."""
        record = await policy.rollback(
            issue_number=99,
            pr_number=101,
            approver="bob",
            reason="rollback test",
        )
        assert record.change_type == BaselineChangeType.ROLLBACK
        assert record.changed_files == []

        records = state.get_baseline_audit(99)
        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_rollback_rejects_unauthorized_approver(
        self, policy: BaselinePolicy, state: StateTracker
    ):
        """Rollback by a user not in baseline_approvers should raise ValueError."""
        with pytest.raises(ValueError, match="not permitted"):
            await policy.rollback(
                issue_number=42,
                pr_number=101,
                approver="unauthorized_user",
                reason="attempt by non-owner",
            )

    @pytest.mark.asyncio
    async def test_rollback_accepts_any_approver_when_list_is_empty(
        self, tmp_path: Path
    ):
        """When baseline_approvers is empty, any approver can trigger a rollback."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            baseline_approval_required=True,
            baseline_approvers=[],
        )
        st = StateTracker(tmp_path / "state.json")
        bp = BaselinePolicy(config=cfg, state=st, event_bus=EventBus())
        record = await bp.rollback(
            issue_number=42,
            pr_number=101,
            approver="anyone",
            reason="open policy rollback",
        )
        assert record.change_type == BaselineChangeType.ROLLBACK
        assert record.approver == "anyone"

    @pytest.mark.asyncio
    async def test_rollback_records_commit_sha(
        self, policy: BaselinePolicy, state: StateTracker
    ):
        """commit_sha should be stored in the rollback audit record."""
        record = await policy.rollback(
            issue_number=42,
            pr_number=101,
            approver="alice",
            reason="regression",
            commit_sha="deadbeef1234",
        )
        assert record.commit_sha == "deadbeef1234"
        records = state.get_baseline_audit(42)
        assert records[-1].commit_sha == "deadbeef1234"

    @pytest.mark.asyncio
    async def test_rollback_event_publish_failure_does_not_raise(
        self, policy: BaselinePolicy, state: StateTracker
    ):
        """A failed bus publish during rollback must not propagate — audit record is already persisted."""
        from unittest.mock import AsyncMock, patch

        with patch.object(
            policy._bus, "publish", new=AsyncMock(side_effect=RuntimeError("bus down"))
        ):
            # Should not raise even though publish fails
            record = await policy.rollback(
                issue_number=42,
                pr_number=101,
                approver="alice",
                reason="regression",
            )
        assert record.change_type == BaselineChangeType.ROLLBACK
        # Audit record must be persisted regardless of publish failure
        records = state.get_baseline_audit(42)
        assert len(records) == 1


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class TestAuditTrail:
    """Tests for audit trail retrieval and formatting."""

    @pytest.mark.asyncio
    async def test_get_audit_trail(self, policy: BaselinePolicy, state: StateTracker):
        await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["alice"],
        )
        trail = policy.get_audit_trail(42)
        assert len(trail) == 1
        assert trail[0].pr_number == 101

    def test_empty_audit_trail(self, policy: BaselinePolicy):
        trail = policy.get_audit_trail(999)
        assert trail == []

    @pytest.mark.asyncio
    async def test_format_audit_summary(self, policy: BaselinePolicy):
        await policy.check_approval(
            pr_number=101,
            issue_number=42,
            changed_files=["tests/__snapshots__/home.snap.png"],
            pr_approvers=["alice"],
        )
        summary = policy.format_audit_summary(42)
        assert "INITIAL" in summary
        assert "alice" in summary
        assert "home.snap.png" in summary

    def test_format_empty_summary(self, policy: BaselinePolicy):
        summary = policy.format_audit_summary(999)
        assert summary == "No baseline changes recorded."

    @pytest.mark.asyncio
    async def test_format_truncates_long_file_lists(
        self, policy: BaselinePolicy, state: StateTracker
    ):
        record = BaselineAuditRecord(
            pr_number=101,
            issue_number=42,
            changed_files=[f"file{i}.snap.png" for i in range(10)],
            change_type=BaselineChangeType.UPDATE,
            approver="alice",
        )
        state.record_baseline_change(42, record)
        summary = policy.format_audit_summary(42)
        assert "+7 more" in summary


# ---------------------------------------------------------------------------
# StateTracker baseline methods
# ---------------------------------------------------------------------------


class TestStateTrackerBaseline:
    """Tests for StateTracker baseline audit methods."""

    def test_record_and_get(self, state: StateTracker):
        record = BaselineAuditRecord(
            pr_number=101,
            issue_number=42,
            changed_files=["a.snap.png"],
            change_type=BaselineChangeType.UPDATE,
            approver="alice",
        )
        state.record_baseline_change(42, record)
        records = state.get_baseline_audit(42)
        assert len(records) == 1
        assert records[0].approver == "alice"

    def test_get_latest(self, state: StateTracker):
        for i in range(3):
            record = BaselineAuditRecord(
                pr_number=100 + i,
                issue_number=42,
                changed_files=[f"file{i}.snap.png"],
                change_type=BaselineChangeType.UPDATE,
                approver=f"user{i}",
            )
            state.record_baseline_change(42, record)
        latest = state.get_latest_baseline_record(42)
        assert latest is not None
        assert latest.pr_number == 102
        assert latest.approver == "user2"

    def test_get_latest_empty(self, state: StateTracker):
        assert state.get_latest_baseline_record(999) is None

    def test_cap_enforced(self, state: StateTracker):
        for i in range(15):
            record = BaselineAuditRecord(
                pr_number=i,
                issue_number=42,
                changed_files=[f"f{i}.png"],
                change_type=BaselineChangeType.UPDATE,
                approver="alice",
            )
            state.record_baseline_change(42, record, max_records=10)
        records = state.get_baseline_audit(42)
        assert len(records) == 10
        # Oldest should have been evicted
        assert records[0].pr_number == 5

    def test_rollback_baseline(self, state: StateTracker):
        # Setup: record an initial update
        update = BaselineAuditRecord(
            pr_number=100,
            issue_number=42,
            changed_files=["home.snap.png"],
            change_type=BaselineChangeType.UPDATE,
            approver="alice",
        )
        state.record_baseline_change(42, update)

        # Rollback
        rollback = state.rollback_baseline(
            issue_number=42,
            pr_number=101,
            approver="bob",
            reason="regression",
        )
        assert rollback.change_type == BaselineChangeType.ROLLBACK
        assert rollback.changed_files == ["home.snap.png"]
        assert rollback.approver == "bob"

        records = state.get_baseline_audit(42)
        assert len(records) == 2
        assert records[-1].change_type == BaselineChangeType.ROLLBACK

    def test_rollback_without_prior(self, state: StateTracker):
        rollback = state.rollback_baseline(
            issue_number=42,
            pr_number=101,
            approver="bob",
            reason="no prior",
        )
        assert rollback.changed_files == []

    def test_persistence_survives_reload(self, tmp_path: Path):
        path = tmp_path / "state.json"
        st1 = StateTracker(path)
        record = BaselineAuditRecord(
            pr_number=101,
            issue_number=42,
            changed_files=["home.snap.png"],
            change_type=BaselineChangeType.UPDATE,
            approver="alice",
        )
        st1.record_baseline_change(42, record)

        # Reload from disk
        st2 = StateTracker(path)
        records = st2.get_baseline_audit(42)
        assert len(records) == 1
        assert records[0].approver == "alice"


# ---------------------------------------------------------------------------
# Config fields
# ---------------------------------------------------------------------------


class TestConfigFields:
    """Tests for baseline-related config fields."""

    def test_baseline_config_has_expected_defaults(self, tmp_path: Path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        assert cfg.baseline_approval_required is True
        assert cfg.baseline_approvers == []
        assert len(cfg.baseline_snapshot_patterns) == 3
        assert cfg.baseline_max_audit_records == 100

    def test_custom_values(self, tmp_path: Path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            baseline_approval_required=False,
            baseline_approvers=["alice"],
            baseline_snapshot_patterns=["*.golden"],
            baseline_max_audit_records=50,
        )
        assert cfg.baseline_approval_required is False
        assert cfg.baseline_approvers == ["alice"]
        assert cfg.baseline_snapshot_patterns == ["*.golden"]
        assert cfg.baseline_max_audit_records == 50


# ---------------------------------------------------------------------------
# Event type
# ---------------------------------------------------------------------------


class TestEventType:
    """Tests for BASELINE_UPDATE event type."""

    def test_baseline_update_exists(self):
        assert EventType.BASELINE_UPDATE == "baseline_update"

    def test_baseline_update_in_enum(self):
        assert "BASELINE_UPDATE" in EventType.__members__


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestBaselineModels:
    """Tests for baseline data models."""

    def test_baseline_change_type_values(self):
        assert BaselineChangeType.UPDATE == "update"
        assert BaselineChangeType.ROLLBACK == "rollback"
        assert BaselineChangeType.INITIAL == "initial"

    def test_audit_record_defaults(self):
        record = BaselineAuditRecord(
            pr_number=101,
            issue_number=42,
        )
        assert record.changed_files == []
        assert record.change_type == BaselineChangeType.UPDATE
        assert record.approver == ""
        assert record.reason == ""
        assert record.commit_sha == ""
        assert record.timestamp  # Should be set

    def test_approval_result_defaults(self):
        result = BaselineApprovalResult()
        assert result.approved is False
        assert result.approver == ""
        assert result.changed_files == []
        assert result.reason == ""
        assert result.requires_approval is False

    def test_audit_record_serialization(self):
        record = BaselineAuditRecord(
            pr_number=101,
            issue_number=42,
            changed_files=["a.png", "b.png"],
            change_type=BaselineChangeType.ROLLBACK,
            approver="alice",
            reason="regression",
        )
        data = record.model_dump()
        restored = BaselineAuditRecord.model_validate(data)
        assert restored.pr_number == 101
        assert restored.change_type == BaselineChangeType.ROLLBACK
        assert restored.changed_files == ["a.png", "b.png"]
