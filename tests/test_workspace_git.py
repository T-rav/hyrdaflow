"""Tests for workspace — git operations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tests.helpers import make_proc
from workspace import WorkspaceManager

# ---------------------------------------------------------------------------
# WorkspaceManager._fetch_and_merge_main
# ---------------------------------------------------------------------------


class TestFetchAndMergeMain:
    @pytest.mark.asyncio
    async def test_success_returns_true(self, config, tmp_path: Path) -> None:
        """_fetch_and_merge_main should return True when all 3 git commands succeed."""
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch("asyncio.create_subprocess_exec", return_value=success_proc):
            result = await manager._fetch_and_merge_main(tmp_path, "agent/issue-7")

        assert result is True

    @pytest.mark.asyncio
    async def test_fetch_failure_raises_runtime_error(
        self, config, tmp_path: Path
    ) -> None:
        """_fetch_and_merge_main should raise RuntimeError when fetch fails."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: network error")

        with (
            patch("asyncio.create_subprocess_exec", return_value=fail_proc),
            pytest.raises(RuntimeError, match="network error"),
        ):
            await manager._fetch_and_merge_main(tmp_path, "agent/issue-7")

    @pytest.mark.asyncio
    async def test_ff_only_merge_failure_raises_runtime_error(
        self, config, tmp_path: Path
    ) -> None:
        """_fetch_and_merge_main should raise RuntimeError when ff-only merge fails."""
        manager = WorkspaceManager(config)
        success_proc = make_proc(returncode=0)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: not a fast-forward")

        async def fake_exec(*args, **kwargs):
            if args[:3] == ("git", "fetch", "origin"):
                return success_proc  # fetch succeeds
            return fail_proc  # ff-only merge fails

        with (
            patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            pytest.raises(RuntimeError, match="not a fast-forward"),
        ):
            await manager._fetch_and_merge_main(tmp_path, "agent/issue-7")

    @pytest.mark.asyncio
    async def test_main_merge_failure_raises_runtime_error(
        self, config, tmp_path: Path
    ) -> None:
        """_fetch_and_merge_main should raise RuntimeError when merge origin/main fails."""
        manager = WorkspaceManager(config)
        success_proc = make_proc(returncode=0)
        fail_proc = make_proc(
            returncode=1, stderr=b"CONFLICT (content): Merge conflict"
        )

        async def fake_exec(*args, **kwargs):
            if args[:3] == ("git", "fetch", "origin") or "--ff-only" in args:
                return success_proc  # fetch + ff-only succeed
            return fail_proc  # merge origin/main fails

        with (
            patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            pytest.raises(RuntimeError, match="Merge conflict"),
        ):
            await manager._fetch_and_merge_main(tmp_path, "agent/issue-7")

    @pytest.mark.asyncio
    async def test_correct_git_commands(self, config, tmp_path: Path) -> None:
        """_fetch_and_merge_main should issue the 3 correct git commands in order."""
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager._fetch_and_merge_main(tmp_path, "agent/issue-7")

        calls = mock_exec.call_args_list
        assert len(calls) == 3
        # 1. git fetch origin main agent/issue-7
        assert calls[0].args[:3] == ("git", "fetch", "origin")
        assert config.main_branch in calls[0].args
        assert "agent/issue-7" in calls[0].args
        # 2. git merge --ff-only origin/agent/issue-7
        assert calls[1].args[:3] == ("git", "merge", "--ff-only")
        assert calls[1].args[3] == "origin/agent/issue-7"
        # 3. git merge origin/main --no-edit
        assert calls[2].args[:2] == ("git", "merge")
        assert f"origin/{config.main_branch}" in calls[2].args
        assert "--no-edit" in calls[2].args


# ---------------------------------------------------------------------------
# WorkspaceManager.merge_main
# ---------------------------------------------------------------------------


class TestMergeMain:
    @pytest.mark.asyncio
    async def test_merge_main_success_returns_true(
        self, config, tmp_path: Path
    ) -> None:
        """merge_main should return True when fetch, ff-pull, and merge succeed."""
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch("asyncio.create_subprocess_exec", return_value=success_proc):
            result = await manager.merge_main(tmp_path, "agent/issue-7")

        assert result is True

    @pytest.mark.asyncio
    async def test_merge_main_conflict_aborts_and_returns_false(
        self, config, tmp_path: Path
    ) -> None:
        """merge_main should abort and return False when conflicts occur."""
        manager = WorkspaceManager(config)

        success_proc = make_proc(returncode=0)
        merge_fail_proc = make_proc(
            returncode=1, stderr=b"CONFLICT (content): Merge conflict"
        )
        abort_proc = make_proc(returncode=0)

        async def fake_exec(*args, **kwargs):
            if "--abort" in args:
                return abort_proc  # git merge --abort
            if args[:3] == ("git", "fetch", "origin") or "--ff-only" in args:
                return success_proc  # git fetch + ff-only merge succeed
            return merge_fail_proc  # git merge origin/main fails

        with patch(
            "asyncio.create_subprocess_exec", side_effect=fake_exec
        ) as mock_exec:
            result = await manager.merge_main(tmp_path, "agent/issue-7")

        assert result is False
        # Verify abort was called
        abort_calls = [c for c in mock_exec.call_args_list if "--abort" in c.args]
        assert len(abort_calls) == 1

    @pytest.mark.asyncio
    async def test_merge_main_fetch_failure_returns_false(
        self, config, tmp_path: Path
    ) -> None:
        """merge_main should return False if the initial fetch fails."""
        manager = WorkspaceManager(config)

        fetch_fail_proc = make_proc(returncode=1, stderr=b"fatal: network error")
        abort_proc = make_proc(returncode=0)

        async def fake_exec(*args, **kwargs):
            if args[:3] == ("git", "fetch", "origin"):
                return fetch_fail_proc
            return abort_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.merge_main(tmp_path, "agent/issue-7")

        assert result is False

    @pytest.mark.asyncio
    async def test_merge_main_retries_ref_lock_fetch_race_and_succeeds(
        self, config, tmp_path: Path
    ) -> None:
        """merge_main should retry fetch lock-race errors and complete successfully."""
        manager = WorkspaceManager(config)

        lock_error = RuntimeError(
            "Command ('git', 'fetch', 'origin', 'main') failed (rc=1): "
            "error: cannot lock ref 'refs/remotes/origin/main': is at aaaaaaaa "
            "but expected bbbbbbbb\n"
            "! bbbbbbbb..aaaaaaaa main -> origin/main (unable to update local ref)"
        )
        calls: list[tuple[str, ...]] = []
        fetch_failures = 0

        async def fake_run_subprocess(*cmd, **kwargs):
            nonlocal fetch_failures
            calls.append(tuple(str(p) for p in cmd))
            if cmd[:3] == ("git", "fetch", "origin"):
                if fetch_failures == 0:
                    fetch_failures += 1
                    raise lock_error
                return ""
            return ""

        with (
            patch("workspace.run_subprocess", side_effect=fake_run_subprocess),
            patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
        ):
            result = await manager.merge_main(tmp_path, "agent/issue-7")

        assert result is True
        fetch_calls = [c for c in calls if c[:3] == ("git", "fetch", "origin")]
        assert len(fetch_calls) == 2  # first fetch failed, second fetch retried
        sleep_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# WorkspaceManager._delete_local_branch
# ---------------------------------------------------------------------------


class TestDeleteLocalBranch:
    @pytest.mark.asyncio
    async def test_deletes_existing_branch(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)
        success_proc = make_proc(returncode=0)

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager._delete_local_branch("agent/issue-7")

        mock_exec.assert_called_once()
        assert mock_exec.call_args.args[:4] == ("git", "branch", "-D", "agent/issue-7")

    @pytest.mark.asyncio
    async def test_swallows_error_when_branch_missing(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"error: branch not found")

        with patch(
            "asyncio.create_subprocess_exec", return_value=fail_proc
        ) as mock_exec:
            # Should not raise
            await manager._delete_local_branch("agent/issue-999")

        mock_exec.assert_called_once()


# ---------------------------------------------------------------------------
# WorkspaceManager._remote_branch_exists
# ---------------------------------------------------------------------------


class TestRemoteBranchExists:
    @pytest.mark.asyncio
    async def test_returns_true_when_ls_remote_has_output(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)
        proc = make_proc(returncode=0, stdout=b"abc123\trefs/heads/agent/issue-7")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager._remote_branch_exists("agent/issue-7")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_ls_remote_empty(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)
        proc = make_proc(returncode=0, stdout=b"")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager._remote_branch_exists("agent/issue-99")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)
        proc = make_proc(returncode=1, stderr=b"fatal: network error")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager._remote_branch_exists("agent/issue-7")

        assert result is False


# ---------------------------------------------------------------------------
# WorkspaceManager.start_merge_main
# ---------------------------------------------------------------------------


class TestStartMergeMain:
    @pytest.mark.asyncio
    async def test_start_merge_main_clean_merge_returns_true(
        self, config, tmp_path: Path
    ) -> None:
        """start_merge_main should return True when all commands succeed."""
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch("asyncio.create_subprocess_exec", return_value=success_proc):
            result = await manager.start_merge_main(tmp_path, "agent/issue-7")

        assert result is True

    @pytest.mark.asyncio
    async def test_start_merge_main_conflict_returns_false_without_abort(
        self, config, tmp_path: Path
    ) -> None:
        """start_merge_main should return False on conflict and NOT call --abort."""
        manager = WorkspaceManager(config)

        success_proc = make_proc(returncode=0)
        merge_fail_proc = make_proc(
            returncode=1, stderr=b"CONFLICT (content): Merge conflict"
        )

        async def fake_exec(*args, **kwargs):
            if args[:3] == ("git", "fetch", "origin") or "--ff-only" in args:
                return success_proc  # git fetch + ff-only merge succeed
            return merge_fail_proc  # git merge origin/main fails

        with patch(
            "asyncio.create_subprocess_exec", side_effect=fake_exec
        ) as mock_exec:
            result = await manager.start_merge_main(tmp_path, "agent/issue-7")

        assert result is False
        # Critical: start_merge_main must NOT call git merge --abort
        for call in mock_exec.call_args_list:
            assert "--abort" not in call.args, (
                "start_merge_main must NOT abort on conflict — "
                "caller resolves conflicts"
            )

    @pytest.mark.asyncio
    async def test_start_merge_main_fetch_failure_returns_false(
        self, config, tmp_path: Path
    ) -> None:
        """start_merge_main should return False if fetch fails."""
        manager = WorkspaceManager(config)

        fetch_fail_proc = make_proc(returncode=1, stderr=b"fatal: network error")

        with patch("asyncio.create_subprocess_exec", return_value=fetch_fail_proc):
            result = await manager.start_merge_main(tmp_path, "agent/issue-7")

        assert result is False


# ---------------------------------------------------------------------------
# WorkspaceManager.abort_merge
# ---------------------------------------------------------------------------


class TestAbortMerge:
    @pytest.mark.asyncio
    async def test_abort_merge_calls_git_merge_abort(
        self, config, tmp_path: Path
    ) -> None:
        """abort_merge should call 'git merge --abort' with correct cwd."""
        manager = WorkspaceManager(config)
        success_proc = make_proc(returncode=0)

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager.abort_merge(tmp_path)

        mock_exec.assert_called_once()
        args = mock_exec.call_args.args
        assert args[:3] == ("git", "merge", "--abort")

    @pytest.mark.asyncio
    async def test_abort_merge_swallows_runtime_error(
        self, config, tmp_path: Path
    ) -> None:
        """abort_merge should suppress RuntimeError via contextlib.suppress."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: no merge in progress")

        with patch(
            "asyncio.create_subprocess_exec", return_value=fail_proc
        ) as mock_exec:
            # Should not raise
            await manager.abort_merge(tmp_path)

        mock_exec.assert_called_once()


# ---------------------------------------------------------------------------
# WorkspaceManager.get_conflicting_files
# ---------------------------------------------------------------------------


class TestGetConflictingFiles:
    @pytest.mark.asyncio
    async def test_returns_list_of_conflicting_files(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)
        output = b"src/foo.py\nsrc/bar.py\n"
        proc = make_proc(returncode=0, stdout=output)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager.get_conflicting_files(tmp_path)

        assert result == ["src/foo.py", "src/bar.py"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_conflicts(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)
        proc = make_proc(returncode=0, stdout=b"")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager.get_conflicting_files(tmp_path)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)
        proc = make_proc(returncode=1, stderr=b"fatal: not a git repo")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager.get_conflicting_files(tmp_path)

        assert result == []

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_filenames(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)
        output = b"  foo.py  \n  bar.py  \n\n"
        proc = make_proc(returncode=0, stdout=output)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager.get_conflicting_files(tmp_path)

        assert result == ["foo.py", "bar.py"]


# ---------------------------------------------------------------------------
# WorkspaceManager.get_main_diff_for_files
# ---------------------------------------------------------------------------


class TestGetMainDiffForFiles:
    @pytest.mark.asyncio
    async def test_returns_diff_for_specified_files(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)
        merge_base_proc = make_proc(returncode=0, stdout=b"abc123\n")
        diff_proc = make_proc(
            returncode=0, stdout=b"diff --git a/foo.py b/foo.py\n+added\n"
        )

        async def fake_exec(*args, **kwargs):
            if args[1] == "merge-base":
                return merge_base_proc
            return diff_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_diff_for_files(tmp_path, ["foo.py"])

        assert "diff --git a/foo.py b/foo.py" in result
        assert "+added" in result

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_file_list(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await manager.get_main_diff_for_files(tmp_path, [])

        assert result == ""
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_truncates_large_diff(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)
        merge_base_proc = make_proc(returncode=0, stdout=b"abc123\n")
        large_diff = b"x" * 50_000
        diff_proc = make_proc(returncode=0, stdout=large_diff)

        async def fake_exec(*args, **kwargs):
            if args[1] == "merge-base":
                return merge_base_proc
            return diff_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_diff_for_files(
                tmp_path, ["foo.py"], max_chars=1000
            )

        assert len(result) < 1100  # 1000 + truncation marker
        assert "[Diff truncated]" in result

    @pytest.mark.asyncio
    async def test_returns_empty_on_merge_base_failure(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: bad revision")

        with patch("asyncio.create_subprocess_exec", return_value=fail_proc):
            result = await manager.get_main_diff_for_files(tmp_path, ["foo.py"])

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_on_diff_failure(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)
        merge_base_proc = make_proc(returncode=0, stdout=b"abc123\n")
        diff_fail_proc = make_proc(returncode=1, stderr=b"fatal: bad path")

        async def fake_exec(*args, **kwargs):
            if args[1] == "merge-base":
                return merge_base_proc
            return diff_fail_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_diff_for_files(tmp_path, ["foo.py"])

        assert result == ""

    @pytest.mark.asyncio
    async def test_passes_multiple_files(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)
        merge_base_proc = make_proc(returncode=0, stdout=b"abc123\n")
        diff_proc = make_proc(returncode=0, stdout=b"combined diff\n")

        async def fake_exec(*args, **kwargs):
            if args[1] == "merge-base":
                return merge_base_proc
            return diff_proc

        with patch(
            "asyncio.create_subprocess_exec", side_effect=fake_exec
        ) as mock_exec:
            await manager.get_main_diff_for_files(
                tmp_path, ["foo.py", "bar.py", "baz.py"]
            )

        # The second call is git diff — check that all files are in the args
        diff_call = mock_exec.call_args_list[1]
        assert "foo.py" in diff_call.args
        assert "bar.py" in diff_call.args
        assert "baz.py" in diff_call.args


# ---------------------------------------------------------------------------
# WorkspaceManager.get_main_commits_since_diverge
# ---------------------------------------------------------------------------


class TestGetMainCommitsSinceDiverge:
    @pytest.mark.asyncio
    async def test_returns_commit_log(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)

        fetch_proc = make_proc(returncode=0)
        log_output = b"abc1234 Add feature X\ndef5678 Fix bug Y\n"
        log_proc = make_proc(returncode=0, stdout=log_output)

        async def fake_exec(*args, **kwargs):
            if args[:3] == ("git", "fetch", "origin"):
                return fetch_proc
            return log_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_commits_since_diverge(tmp_path)

        assert "abc1234 Add feature X" in result
        assert "def5678 Fix bug Y" in result

    @pytest.mark.asyncio
    async def test_returns_empty_on_fetch_failure(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: network error")

        with patch("asyncio.create_subprocess_exec", return_value=fail_proc):
            result = await manager.get_main_commits_since_diverge(tmp_path)

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_on_log_failure(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)

        fetch_proc = make_proc(returncode=0)
        log_fail_proc = make_proc(returncode=1, stderr=b"fatal: bad revision")

        async def fake_exec(*args, **kwargs):
            if args[:3] == ("git", "fetch", "origin"):
                return fetch_proc
            return log_fail_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_commits_since_diverge(tmp_path)

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_diverged_commits(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)

        fetch_proc = make_proc(returncode=0)
        log_proc = make_proc(returncode=0, stdout=b"")

        async def fake_exec(*args, **kwargs):
            if args[:3] == ("git", "fetch", "origin"):
                return fetch_proc
            return log_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_commits_since_diverge(tmp_path)

        assert result == ""

    @pytest.mark.asyncio
    async def test_passes_limit_flag(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)

        success_proc = make_proc(returncode=0, stdout=b"abc123 commit\n")

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager.get_main_commits_since_diverge(tmp_path)

        # Second call is git log
        log_call = mock_exec.call_args_list[1]
        assert "-30" in log_call.args


# ---------------------------------------------------------------------------
# WorkspaceManager.enable_rerere
# ---------------------------------------------------------------------------


class TestEnableRerere:
    @pytest.mark.asyncio
    async def test_enable_rerere_runs_git_config(self, config) -> None:
        """enable_rerere should run ``git config rerere.enabled true`` in repo root."""
        manager = WorkspaceManager(config)
        success_proc = make_proc(returncode=0)

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager.enable_rerere()

        args = mock_exec.call_args.args
        assert "git" in args
        assert "config" in args
        assert "rerere.enabled" in args
        assert "true" in args

    @pytest.mark.asyncio
    async def test_enable_rerere_swallows_runtime_error(self, config) -> None:
        """enable_rerere should not raise when git config fails."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: not in a git repo")

        with patch("asyncio.create_subprocess_exec", return_value=fail_proc):
            await manager.enable_rerere()  # Should not raise

    @pytest.mark.asyncio
    async def test_enable_rerere_swallows_file_not_found(self, config) -> None:
        """enable_rerere should not raise when git binary is missing."""
        manager = WorkspaceManager(config)

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            await manager.enable_rerere()  # Should not raise
