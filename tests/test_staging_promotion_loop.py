"""Tests for StagingPromotionLoop."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from models import PRInfo
from staging_promotion_loop import StagingPromotionLoop
from state import StateTracker


def _make_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HydraFlowConfig:
    monkeypatch.setenv("HYDRAFLOW_STAGING_PROMOTION_INTERVAL", "300")
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
    )


def _make_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    staging_enabled: bool = True,
    rc_cadence_hours: int = 4,
    open_promotion: PRInfo | None = None,
    ci_result: tuple[bool, str] = (True, "ok"),
    merge_result: bool = True,
) -> tuple[StagingPromotionLoop, MagicMock]:
    monkeypatch.setenv(
        "HYDRAFLOW_STAGING_ENABLED", "true" if staging_enabled else "false"
    )
    monkeypatch.setenv("HYDRAFLOW_RC_CADENCE_HOURS", str(rc_cadence_hours))
    cfg = _make_cfg(tmp_path, monkeypatch)

    stop_event = asyncio.Event()

    async def _sleep(_s: float) -> None:  # instant sleep for tests
        return None

    loop_deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _n: True,
        sleep_fn=_sleep,
    )

    prs = MagicMock()
    prs.find_open_promotion_pr = AsyncMock(return_value=open_promotion)
    prs.wait_for_ci = AsyncMock(return_value=ci_result)
    prs.merge_promotion_pr = AsyncMock(return_value=merge_result)
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    prs.create_rc_branch = AsyncMock(return_value="sha123")
    prs.create_promotion_pr = AsyncMock(return_value=42)
    prs.create_issue = AsyncMock(return_value=1234)
    prs.list_rc_branches = AsyncMock(return_value=[])
    prs.delete_branch = AsyncMock(return_value=True)

    loop = StagingPromotionLoop(config=cfg, prs=prs, deps=loop_deps)
    return loop, prs


def _make_pr(number: int = 42, branch: str = "rc/2026-04-18-1200") -> PRInfo:
    return PRInfo(
        number=number,
        issue_number=0,
        branch=branch,
        url=f"https://github.com/o/r/pull/{number}",
        draft=False,
    )


class TestStagingDisabled:
    @pytest.mark.asyncio
    async def test_noop_when_staging_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch, staging_enabled=False)
        result = await loop._do_work()
        assert result == {"status": "staging_disabled"}
        prs.find_open_promotion_pr.assert_not_called()
        prs.create_rc_branch.assert_not_called()


class TestCadenceGate:
    @pytest.mark.asyncio
    async def test_no_op_when_cadence_not_elapsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch, rc_cadence_hours=4)
        loop._record_last_rc(datetime.now(UTC) - timedelta(hours=1))
        result = await loop._do_work()
        assert result == {"status": "cadence_not_elapsed"}
        prs.create_rc_branch.assert_not_called()

    @pytest.mark.asyncio
    async def test_cuts_rc_when_cadence_elapsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch, rc_cadence_hours=4)
        loop._record_last_rc(datetime.now(UTC) - timedelta(hours=5))
        result = await loop._do_work()
        assert result["status"] == "opened"
        assert result["pr"] == 42
        prs.create_rc_branch.assert_called_once()
        prs.create_promotion_pr.assert_called_once()

    @pytest.mark.asyncio
    async def test_cuts_rc_on_first_run_no_timestamp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        result = await loop._do_work()
        assert result["status"] == "opened"
        prs.create_rc_branch.assert_called_once()


class TestRcBranchNaming:
    @pytest.mark.asyncio
    async def test_rc_branch_uses_prefix_and_timestamp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        await loop._do_work()
        (branch,) = prs.create_rc_branch.call_args.args
        assert branch.startswith("rc/")
        # rc/YYYY-MM-DD-HHMM = 18 chars total
        assert len(branch) == len("rc/") + len("YYYY-MM-DD-HHMM")


class TestRecordOnCreate:
    @pytest.mark.asyncio
    async def test_records_timestamp_after_successful_creation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch)
        assert not loop._cadence_path().exists()
        await loop._do_work()
        assert loop._cadence_path().exists()

    @pytest.mark.asyncio
    async def test_does_not_record_when_rc_branch_creation_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        prs.create_rc_branch.side_effect = RuntimeError("boom")
        result = await loop._do_work()
        assert result["status"] == "rc_branch_failed"
        assert not loop._cadence_path().exists()


class TestOpenPromotionPassing:
    @pytest.mark.asyncio
    async def test_merges_on_green_ci(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(True, "ok"),
        )
        result = await loop._do_work()
        assert result == {"status": "promoted", "pr": 99}
        prs.merge_promotion_pr.assert_called_once_with(99)
        prs.create_rc_branch.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_merge_failed_when_merge_rejects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _ = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(True, "ok"),
            merge_result=False,
        )
        result = await loop._do_work()
        assert result == {"status": "merge_failed", "pr": 99}


class TestOpenPromotionFailing:
    @pytest.mark.asyncio
    async def test_closes_pr_on_ci_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(False, "ci failed: scenario tests"),
        )
        result = await loop._do_work()
        assert result == {"status": "ci_failed", "pr": 99, "find_issue": 1234}
        prs.post_comment.assert_called_once()
        prs.close_issue.assert_called_once_with(99)

    @pytest.mark.asyncio
    async def test_files_hydraflow_find_issue_on_ci_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(False, "scenario suite failed"),
        )
        await loop._do_work()
        prs.create_issue.assert_called_once()
        args, _kwargs = prs.create_issue.call_args
        title, body, labels = args
        assert "RC promotion #99 failed CI" in title
        assert "scenario suite failed" in body
        assert labels == ["hydraflow-find"]

    @pytest.mark.asyncio
    async def test_closes_pr_even_if_issue_filing_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(False, "boom"),
        )
        prs.create_issue.side_effect = RuntimeError("gh down")
        result = await loop._do_work()
        assert result == {"status": "ci_failed", "pr": 99, "find_issue": 0}
        prs.close_issue.assert_called_once_with(99)

    @pytest.mark.asyncio
    async def test_ci_pending_leaves_pr_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(False, "Timed out after 60s"),
        )
        result = await loop._do_work()
        assert result == {"status": "ci_pending", "pr": 99}
        prs.close_issue.assert_not_called()
        prs.merge_promotion_pr.assert_not_called()


class TestDefaultInterval:
    def test_returns_config_interval(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch)
        assert loop._get_default_interval() == 300


class TestRetentionSweep:
    def _iso(self, dt: datetime) -> str:
        return dt.isoformat().replace("+00:00", "Z")

    @pytest.mark.asyncio
    async def test_sweep_skipped_when_recently_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        loop._sweep_path().parent.mkdir(parents=True, exist_ok=True)
        loop._sweep_path().write_text(datetime.now(UTC).isoformat())
        # Block other work paths so _do_work completes promptly.
        prs.find_open_promotion_pr.return_value = _make_pr(99)
        prs.wait_for_ci.return_value = (False, "Timed out")
        await loop._do_work()
        prs.list_rc_branches.assert_not_called()

    @pytest.mark.asyncio
    async def test_deletes_rc_branches_older_than_retention(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        old = datetime.now(UTC) - timedelta(days=30)
        recent = datetime.now(UTC) - timedelta(days=2)
        prs.list_rc_branches.return_value = [
            ("rc/2026-03-10-1200", self._iso(old)),
            ("rc/2026-04-16-0800", self._iso(recent)),
        ]
        # Force _do_work straight into the sweep by making it cadence_not_elapsed.
        loop._record_last_rc(datetime.now(UTC))
        result = await loop._do_work()
        prs.delete_branch.assert_called_once_with("rc/2026-03-10-1200")
        assert result["swept"] == 1

    @pytest.mark.asyncio
    async def test_preserves_newest_even_if_past_retention(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        # Every branch is older than retention (7d default); the newest should
        # still survive so the repo isn't left with zero RC snapshots.
        prs.list_rc_branches.return_value = [
            ("rc/2026-01-01-1200", self._iso(datetime.now(UTC) - timedelta(days=90))),
            ("rc/2026-01-10-1200", self._iso(datetime.now(UTC) - timedelta(days=80))),
        ]
        loop._record_last_rc(datetime.now(UTC))
        await loop._do_work()
        deleted_branches = [c.args[0] for c in prs.delete_branch.call_args_list]
        assert "rc/2026-01-10-1200" not in deleted_branches
        assert "rc/2026-01-01-1200" in deleted_branches

    @pytest.mark.asyncio
    async def test_preserves_branch_with_open_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        open_pr = _make_pr(99, branch="rc/2026-01-01-1200")
        loop, prs = _make_loop(tmp_path, monkeypatch, open_promotion=open_pr)
        prs.list_rc_branches.return_value = [
            ("rc/2026-01-01-1200", self._iso(datetime.now(UTC) - timedelta(days=90))),
            ("rc/2026-04-16-0800", self._iso(datetime.now(UTC) - timedelta(days=2))),
        ]
        prs.wait_for_ci.return_value = (False, "Timed out")
        await loop._do_work()
        deleted_branches = [c.args[0] for c in prs.delete_branch.call_args_list]
        assert "rc/2026-01-01-1200" not in deleted_branches

    @pytest.mark.asyncio
    async def test_records_sweep_timestamp_even_when_no_deletes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch)
        assert not loop._sweep_path().exists()
        loop._record_last_rc(datetime.now(UTC))
        await loop._do_work()
        assert loop._sweep_path().exists()


class TestStateWritesOnPromoted:
    @pytest.mark.asyncio
    async def test_writes_last_green_rc_sha_on_promoted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=77),
            ci_result=(True, "ok"),
            merge_result=True,
        )
        prs.get_pr_head_sha = AsyncMock(return_value="abc123deadbeef")
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]
        # seed a stale counter so reset is observable
        state.increment_auto_reverts_in_cycle()
        assert state.get_auto_reverts_in_cycle() == 1

        result = await loop._do_work()

        assert result["status"] == "promoted"
        assert state.get_last_green_rc_sha() == "abc123deadbeef"
        assert state.get_auto_reverts_in_cycle() == 0
