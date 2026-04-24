"""Tests for StagingBisectLoop (spec §4.3)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from state import StateTracker


def _make_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HydraFlowConfig:
    monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
    monkeypatch.setenv("HYDRAFLOW_STAGING_BISECT_INTERVAL", "600")
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
    )


def _make_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, MagicMock, StateTracker]:
    from staging_bisect_loop import StagingBisectLoop

    cfg = _make_cfg(tmp_path, monkeypatch)
    stop_event = asyncio.Event()

    async def _sleep(_s: float) -> None:
        return None

    loop_deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _n: True,
        sleep_fn=_sleep,
    )
    prs = MagicMock()
    state = StateTracker(state_file=tmp_path / "s.json")
    loop = StagingBisectLoop(config=cfg, prs=prs, deps=loop_deps, state=state)
    return loop, prs, state


class TestSkeleton:
    @pytest.mark.asyncio
    async def test_do_work_returns_noop_when_no_red_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        assert state.get_last_rc_red_sha() == ""
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "no_red"}

    @pytest.mark.asyncio
    async def test_do_work_idempotent_on_already_processed_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("abc")
        loop._last_processed_rc_red_sha = "abc"  # type: ignore[attr-defined]
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "already_processed", "sha": "abc"}

    @pytest.mark.asyncio
    async def test_do_work_noop_when_staging_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        # _make_cfg sets STAGING_ENABLED=true; override on the constructed
        # config for this scenario (env is read at config-construct time).
        loop._config.staging_enabled = False  # type: ignore[attr-defined]
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "staging_disabled"}

    def test_interval_uses_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        assert loop._get_default_interval() == 600  # type: ignore[attr-defined]


class TestPersistence:
    @pytest.mark.asyncio
    async def test_processed_sha_persists_across_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("abc")
        # First run marks abc as seen
        await loop._do_work()  # type: ignore[attr-defined]

        # Simulate restart: create a fresh loop with the same data_root
        loop2, _prs2, _state2 = _make_loop(tmp_path, monkeypatch)
        result = await loop2._do_work()  # type: ignore[attr-defined]
        assert result["status"] == "already_processed"


class TestFlakeFilter:
    @pytest.mark.asyncio
    async def test_second_probe_passes_increments_flake_counter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("red123")
        loop._run_bisect_probe = AsyncMock(return_value=(True, ""))  # type: ignore[attr-defined]

        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result["status"] == "flake_dismissed"
        assert state.get_flake_reruns_total() == 1
        loop._run_bisect_probe.assert_awaited_once_with("red123")  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_second_probe_fails_proceeds_to_bisect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("red456")
        loop._run_bisect_probe = AsyncMock(return_value=(False, "failing: test_foo"))  # type: ignore[attr-defined]
        loop._run_full_bisect_pipeline = AsyncMock(  # type: ignore[attr-defined]
            return_value={"status": "reverted", "pr": 99}
        )

        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result["status"] == "reverted"
        assert state.get_flake_reruns_total() == 0


class TestBisectHarness:
    @pytest.mark.asyncio
    async def test_run_bisect_returns_first_bad_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)

        async def fake_git(cmd: list[str], cwd: Path, timeout: int):
            if cmd[:2] == ["git", "bisect"] and cmd[2] == "run":
                return (
                    0,
                    "Bisecting: 3 revisions left to test\n"
                    "abc123def456 is the first bad commit\n"
                    "commit abc123def456\n",
                    "",
                )
            return (0, "", "")

        loop._run_git = AsyncMock(side_effect=fake_git)  # type: ignore[attr-defined]
        loop._setup_worktree = AsyncMock(return_value=tmp_path / "bisect-wt")  # type: ignore[attr-defined]
        loop._cleanup_worktree = AsyncMock()  # type: ignore[attr-defined]

        culprit = await loop._run_bisect("green_sha", "red_sha")  # type: ignore[attr-defined]

        assert culprit == "abc123def456"
        loop._cleanup_worktree.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_bisect_timeout_raises_bisect_timeout_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from staging_bisect_loop import BisectTimeoutError

        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        loop._setup_worktree = AsyncMock(return_value=tmp_path / "bisect-wt")  # type: ignore[attr-defined]
        loop._cleanup_worktree = AsyncMock()  # type: ignore[attr-defined]

        async def hanging(cmd: list[str], cwd: Path, timeout: int):
            raise TimeoutError("git bisect run exceeded budget")

        loop._run_git = AsyncMock(side_effect=hanging)  # type: ignore[attr-defined]

        with pytest.raises(BisectTimeoutError):
            await loop._run_bisect("green", "red")  # type: ignore[attr-defined]
        loop._cleanup_worktree.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_bisect_unreachable_green_sha_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from staging_bisect_loop import BisectRangeError

        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        loop._setup_worktree = AsyncMock(return_value=tmp_path / "bisect-wt")  # type: ignore[attr-defined]
        loop._cleanup_worktree = AsyncMock()  # type: ignore[attr-defined]

        async def fake_git(cmd: list[str], cwd: Path, timeout: int):
            if cmd[:3] == ["git", "bisect", "start"]:
                return (1, "", "fatal: bad object green_sha")
            return (0, "", "")

        loop._run_git = AsyncMock(side_effect=fake_git)  # type: ignore[attr-defined]

        with pytest.raises(BisectRangeError):
            await loop._run_bisect("green_sha", "red_sha")  # type: ignore[attr-defined]


class TestAttribution:
    @pytest.mark.asyncio
    async def test_attribute_resolves_sha_to_pr_number(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)

        async def fake_gh(cmd: list[str]) -> str:
            assert cmd[0] == "gh"
            return (
                '[{"number": 321, "title": "Feature: widgets",'
                ' "merge_commit_sha": "culprit_sha"}]'
            )

        loop._run_gh = AsyncMock(side_effect=fake_gh)  # type: ignore[attr-defined]

        pr_number, pr_title = await loop._attribute_culprit("culprit_sha")  # type: ignore[attr-defined]

        assert pr_number == 321
        assert pr_title == "Feature: widgets"

    @pytest.mark.asyncio
    async def test_attribute_returns_zero_when_no_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        loop._run_gh = AsyncMock(return_value="[]")  # type: ignore[attr-defined]

        pr_number, pr_title = await loop._attribute_culprit("culprit_sha")  # type: ignore[attr-defined]

        assert pr_number == 0
        assert pr_title == ""

    @pytest.mark.asyncio
    async def test_attribute_handles_malformed_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        loop._run_gh = AsyncMock(return_value="not valid json")  # type: ignore[attr-defined]

        pr_number, pr_title = await loop._attribute_culprit("culprit_sha")  # type: ignore[attr-defined]

        assert pr_number == 0
        assert pr_title == ""


class TestGuardrail:
    @pytest.mark.asyncio
    async def test_second_revert_in_cycle_escalates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        # Simulate a prior auto-revert in this cycle
        state.set_last_rc_red_sha_and_bump_cycle("prev_red")
        state.increment_auto_reverts_in_cycle()
        state.set_last_rc_red_sha_and_bump_cycle("current_red")
        state.increment_auto_reverts_in_cycle()  # we are at 2 reverts
        prs.create_issue = AsyncMock(return_value=555)

        result = await loop._check_guardrail_and_maybe_escalate(  # type: ignore[attr-defined]
            red_sha="current_red",
            culprit_sha="culprit_sha",
            culprit_pr=321,
            bisect_log="log",
        )

        assert result == {
            "status": "guardrail_escalated",
            "escalation_issue": 555,
        }
        prs.create_issue.assert_awaited_once()
        title = prs.create_issue.await_args.args[0]
        labels = prs.create_issue.await_args.args[2]
        assert "rc-red-attribution-unsafe" in labels
        assert "hitl-escalation" in labels
        assert "current_red" in title

    @pytest.mark.asyncio
    async def test_first_revert_passes_guardrail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("current_red")
        # auto_reverts_in_cycle == 0 — guardrail allows proceeding
        prs.create_issue = AsyncMock()

        result = await loop._check_guardrail_and_maybe_escalate(  # type: ignore[attr-defined]
            red_sha="current_red",
            culprit_sha="culprit_sha",
            culprit_pr=321,
            bisect_log="log",
        )

        assert result is None
        prs.create_issue.assert_not_awaited()


class TestRevertPR:
    @pytest.mark.asyncio
    async def test_create_revert_pr_merge_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = _make_loop(tmp_path, monkeypatch)
        prs.create_issue = AsyncMock()
        prs._run_gh = AsyncMock(
            return_value="https://github.com/o/r/pull/900"
        )  # not used
        loop._run_git = AsyncMock(return_value=(0, "", ""))  # type: ignore[attr-defined]
        loop._is_merge_commit = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        loop._create_pr_via_gh = AsyncMock(return_value=900)  # type: ignore[attr-defined]

        pr_number, branch = await loop._create_revert_pr(  # type: ignore[attr-defined]
            culprit_sha="culprit_sha",
            culprit_pr=321,
            failing_tests="test_foo, test_bar",
            rc_pr_url="https://github.com/o/r/pull/77",
            bisect_log="log",
            retry_issue_number=654,
        )

        assert pr_number == 900
        assert branch.startswith("auto-revert/pr-321-rc-")
        # Verify git revert -m 1 was invoked
        calls = [c.args[0] for c in loop._run_git.await_args_list]  # type: ignore[attr-defined]
        revert_cmds = [c for c in calls if len(c) >= 2 and c[1] == "revert"]
        assert revert_cmds
        assert "-m" in revert_cmds[0] and "1" in revert_cmds[0]

    @pytest.mark.asyncio
    async def test_create_revert_pr_single_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = _make_loop(tmp_path, monkeypatch)
        prs.create_issue = AsyncMock()
        loop._run_git = AsyncMock(return_value=(0, "", ""))  # type: ignore[attr-defined]
        loop._is_merge_commit = AsyncMock(return_value=False)  # type: ignore[attr-defined]
        loop._create_pr_via_gh = AsyncMock(return_value=901)  # type: ignore[attr-defined]

        await loop._create_revert_pr(  # type: ignore[attr-defined]
            culprit_sha="c",
            culprit_pr=321,
            failing_tests="t",
            rc_pr_url="u",
            bisect_log="l",
            retry_issue_number=0,
        )

        calls = [c.args[0] for c in loop._run_git.await_args_list]  # type: ignore[attr-defined]
        revert_cmds = [c for c in calls if len(c) >= 2 and c[1] == "revert"]
        assert revert_cmds
        assert "-m" not in revert_cmds[0]

    @pytest.mark.asyncio
    async def test_revert_conflict_escalates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from staging_bisect_loop import RevertConflictError

        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        loop._is_merge_commit = AsyncMock(return_value=True)  # type: ignore[attr-defined]

        async def fake_git(cmd, **_kw):
            if len(cmd) >= 2 and cmd[1] == "revert":
                return (1, "", "CONFLICT (content): Merge conflict in foo.py")
            return (0, "", "")

        loop._run_git = AsyncMock(side_effect=fake_git)  # type: ignore[attr-defined]

        with pytest.raises(RevertConflictError):
            await loop._create_revert_pr(  # type: ignore[attr-defined]
                culprit_sha="c",
                culprit_pr=321,
                failing_tests="t",
                rc_pr_url="u",
                bisect_log="l",
                retry_issue_number=0,
            )


class TestRetryIssue:
    @pytest.mark.asyncio
    async def test_file_retry_issue_title_and_labels(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = _make_loop(tmp_path, monkeypatch)
        prs.create_issue = AsyncMock(return_value=654)

        issue = await loop._file_retry_issue(  # type: ignore[attr-defined]
            culprit_pr=321,
            culprit_pr_title="Feature: widgets",
            culprit_sha="culprit_sha",
            green_sha="green_sha",
            red_sha="red_sha",
            failing_tests="test_foo",
            bisect_log="log",
            revert_pr_url="https://github.com/o/r/pull/900",
        )

        assert issue == 654
        prs.create_issue.assert_awaited_once()
        title, body, labels = prs.create_issue.await_args.args
        assert title == "Retry: Feature: widgets"
        assert "hydraflow-find" in labels
        assert "rc-red-retry" in labels
        assert "pull/900" in body
        assert "green_sha" in body
        assert "red_sha" in body


class TestWatchdog:
    @pytest.mark.asyncio
    async def test_watchdog_green_outcome(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.increment_auto_reverts_in_cycle()  # simulate prior revert
        loop._pending_watchdog = {  # type: ignore[attr-defined]
            "red_sha_at_revert": "red_A",
            "rc_cycle_at_revert": state.get_rc_cycle_id(),
            "deadline_ts": 9_999_999_999.0,
        }
        # Promotion happened -> last_green_rc_sha advanced
        state.set_last_green_rc_sha("green_B")
        state.reset_auto_reverts_in_cycle()

        result = await loop._check_pending_watchdog()  # type: ignore[attr-defined]

        assert result == {"status": "watchdog_green"}
        assert state.get_auto_reverts_successful() == 1
        assert loop._pending_watchdog is None  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_watchdog_still_red_escalates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("red_A")
        state.increment_auto_reverts_in_cycle()
        prior_cycle = state.get_rc_cycle_id()

        # New red arrives
        state.set_last_rc_red_sha_and_bump_cycle("red_B")
        prs.create_issue = AsyncMock(return_value=888)
        loop._pending_watchdog = {  # type: ignore[attr-defined]
            "red_sha_at_revert": "red_A",
            "rc_cycle_at_revert": prior_cycle,
            "deadline_ts": 9_999_999_999.0,
        }

        result = await loop._check_pending_watchdog()  # type: ignore[attr-defined]

        assert result["status"] == "watchdog_still_red"
        labels = prs.create_issue.await_args.args[2]
        assert "rc-red-post-revert-red" in labels

    @pytest.mark.asyncio
    async def test_watchdog_timeout_escalates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = _make_loop(tmp_path, monkeypatch)
        prs.create_issue = AsyncMock(return_value=889)
        loop._pending_watchdog = {  # type: ignore[attr-defined]
            "red_sha_at_revert": "red_A",
            "rc_cycle_at_revert": 1,
            "deadline_ts": 0.0,  # already past
        }

        result = await loop._check_pending_watchdog()  # type: ignore[attr-defined]

        assert result["status"] == "watchdog_timeout"
        labels = prs.create_issue.await_args.args[2]
        assert "rc-red-verify-timeout" in labels


class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_confirmed_red_happy_path_revert_and_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_green_rc_sha("green_sha")
        state.set_last_rc_red_sha_and_bump_cycle("red_sha")

        loop._run_bisect_probe = AsyncMock(return_value=(False, "test_foo failed"))  # type: ignore[attr-defined]
        loop._run_bisect = AsyncMock(return_value="culprit_sha")  # type: ignore[attr-defined]
        loop._attribute_culprit = AsyncMock(return_value=(321, "Feature: widgets"))  # type: ignore[attr-defined]
        loop._create_revert_pr = AsyncMock(
            return_value=(900, "auto-revert/pr-321-rc-123")
        )  # type: ignore[attr-defined]
        loop._file_retry_issue = AsyncMock(return_value=654)  # type: ignore[attr-defined]
        prs.find_open_pr = AsyncMock()
        prs.get_pr_head_sha = AsyncMock(return_value="red_sha")
        prs.find_open_promotion_pr = AsyncMock(
            return_value=MagicMock(number=77, url="https://github.com/o/r/pull/77")
        )

        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result["status"] == "reverted"
        assert result["revert_pr"] == 900
        assert result["retry_issue"] == 654
        assert state.get_auto_reverts_in_cycle() == 1
        assert loop._pending_watchdog is not None  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_timeout_during_bisect_escalates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from staging_bisect_loop import BisectTimeoutError

        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_green_rc_sha("green_sha")
        state.set_last_rc_red_sha_and_bump_cycle("red_sha")
        loop._run_bisect_probe = AsyncMock(return_value=(False, ""))  # type: ignore[attr-defined]
        loop._run_bisect = AsyncMock(side_effect=BisectTimeoutError("timeout"))  # type: ignore[attr-defined]
        prs.create_issue = AsyncMock(return_value=777)
        prs.find_open_promotion_pr = AsyncMock(
            return_value=MagicMock(number=77, url="u")
        )

        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result["status"] == "bisect_timeout"
        labels = prs.create_issue.await_args.args[2]
        assert "bisect-timeout" in labels
        assert "hitl-escalation" in labels


class TestInvalidRange:
    @pytest.mark.asyncio
    async def test_invalid_range_logs_and_noops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        from staging_bisect_loop import BisectRangeError

        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_green_rc_sha("unreachable_sha")
        state.set_last_rc_red_sha_and_bump_cycle("red_sha")
        loop._run_bisect_probe = AsyncMock(return_value=(False, ""))  # type: ignore[attr-defined]
        loop._run_bisect = AsyncMock(side_effect=BisectRangeError("bad object"))  # type: ignore[attr-defined]
        prs.find_open_promotion_pr = AsyncMock(
            return_value=MagicMock(number=77, url="u")
        )

        caplog.set_level("WARNING")
        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result == {"status": "invalid_bisect_range", "sha": "red_sha"}
        assert any("invalid bisect range" in rec.message for rec in caplog.records)
