"""End-to-end test for ``StagingBisectLoop._run_full_bisect_pipeline``.

Drives the real ``git bisect`` against the three-commit sandbox fixture
in ``tests/fixtures/staging_bisect_sandbox/`` and asserts that the loop
attributes commit C (the red HEAD) back to commit B (the culprit).

Non-bisect phases of the pipeline (culprit→PR attribution, revert PR,
retry issue) are mocked per the plan — this test verifies the bisect
attribution link only. See spec §4.3 Task 24.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from state import StateTracker
from tests.fixtures.staging_bisect_sandbox import init_three_commit_repo


class TestStagingBisectE2E:
    """Drive the full bisect pipeline against a real three-commit repo."""

    @pytest.mark.asyncio
    async def test_full_pipeline_attributes_culprit_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # --- Arrange: fixture repo + loop ---------------------------------
        repo_root = tmp_path / "fixture_repo"
        good, culprit, head = init_three_commit_repo(repo_root)

        monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
        cfg = HydraFlowConfig(
            repo_root=repo_root,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "state.json",
            data_root=tmp_path / "data",
        )

        async def _sleep(_s: float) -> None:
            return None

        loop_deps = LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=MagicMock(),
            enabled_cb=lambda _n: True,
            sleep_fn=_sleep,
        )

        prs = MagicMock()
        prs.create_issue = AsyncMock(return_value=654)
        prs.find_open_promotion_pr = AsyncMock(
            return_value=MagicMock(number=77, url="https://example/pull/77")
        )

        state = StateTracker(state_file=tmp_path / "state.json")
        state.set_last_green_rc_sha(good)
        state.set_last_rc_red_sha_and_bump_cycle(head)

        from staging_bisect_loop import StagingBisectLoop

        loop = StagingBisectLoop(config=cfg, prs=prs, deps=loop_deps, state=state)

        # --- Arrange: stub worktree to point at the fixture ---------------
        # The real _setup_worktree calls `git worktree add`, which we don't
        # want here — just run bisect in-place on the fixture repo.
        async def fake_setup(_rc_sha: str) -> Path:
            return repo_root

        async def fake_cleanup(_wt: Path) -> None:
            return None

        loop._setup_worktree = fake_setup  # type: ignore[attr-defined]
        loop._cleanup_worktree = fake_cleanup  # type: ignore[attr-defined]

        # --- Arrange: route `_run_git` through real subprocess -----------
        # The real _run_bisect issues two git commands via _run_git:
        #   1. git bisect start <red> <green>
        #   2. git bisect run make -C <repo_root> bisect-probe
        # We rewrite the second form to run the fixture's probe.sh so the
        # test does not depend on the full Makefile.
        async def patched_run_git(
            cmd: list[str], *, cwd: Path, timeout: int
        ) -> tuple[int, str, str]:
            if cmd[:3] == ["git", "bisect", "run"]:
                cmd = ["git", "bisect", "run", str(repo_root / "probe.sh")]
            proc = subprocess.run(  # noqa: S603 — controlled, test-local
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return proc.returncode, proc.stdout, proc.stderr

        loop._run_git = patched_run_git  # type: ignore[attr-defined]

        # --- Arrange: mock non-bisect pipeline phases --------------------
        # Per plan Task 24 / user rule 7: focus the assertion on bisect
        # attribution only. Revert-PR + retry-issue phases are mocked.
        loop._attribute_culprit = AsyncMock(  # type: ignore[attr-defined]
            return_value=(321, "culprit: flip probe.sh to exit 1")
        )
        loop._create_revert_pr = AsyncMock(  # type: ignore[attr-defined]
            return_value=(900, "auto-revert/pr-321-rc-abc")
        )
        loop._file_retry_issue = AsyncMock(return_value=654)  # type: ignore[attr-defined]

        # --- Act ----------------------------------------------------------
        try:
            result = await loop._run_full_bisect_pipeline(  # type: ignore[attr-defined]
                red_sha=head, probe_output="FAILED tests/fake::test_probe"
            )
        finally:
            # Always reset bisect state so later tests / cleanup aren't
            # tangled up in a half-finished bisect session.
            subprocess.run(  # noqa: S603,S607
                ["git", "bisect", "reset"],
                cwd=repo_root,
                capture_output=True,
                check=False,
            )

        # --- Assert: bisect identified commit C as the culprit -----------
        loop._attribute_culprit.assert_awaited_once()  # type: ignore[attr-defined]
        attribution_args = loop._attribute_culprit.await_args.args  # type: ignore[attr-defined]
        identified_sha = attribution_args[0]
        assert identified_sha.startswith(culprit[:7]), (
            f"bisect should identify culprit={culprit[:12]} but called "
            f"_attribute_culprit with {identified_sha[:12]}"
        )

        # --- Assert: full pipeline completed end-to-end ------------------
        assert result["status"] == "reverted"
        assert result["revert_pr"] == 900
        assert result["retry_issue"] == 654
        assert result["culprit_pr"] == 321
        assert result["culprit_sha"].startswith(culprit[:7])
