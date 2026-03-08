"""Tests for pr_manager.py — list/query operations."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, patch

import pytest

from pr_manager import PRManager
from tests.conftest import SubprocessMockBuilder
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(config, event_bus):
    return PRManager(config=config, event_bus=event_bus)


def _assert_search_api_cmd(cmd: tuple[str, ...]) -> None:
    """Assert common structure of a gh API search command."""
    assert "api" in cmd
    assert "search/issues" in cmd
    assert ".total_count" in cmd
    assert "--limit" not in cmd


# ---------------------------------------------------------------------------
# list_open_prs
# ---------------------------------------------------------------------------


class TestListOpenPrs:
    """Tests for PRManager.list_open_prs."""

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_labels(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        result = await mgr.list_open_prs([])
        assert result == []

    @pytest.mark.asyncio
    async def test_parses_pr_data_correctly(self, event_bus, tmp_path):
        import json

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        pr_json = json.dumps(
            [
                {
                    "number": 10,
                    "url": "https://github.com/org/repo/pull/10",
                    "headRefName": "agent/issue-42",
                    "isDraft": False,
                    "title": "Fix widget",
                },
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(pr_json).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_open_prs(["test-label"])

        assert len(result) == 1
        assert result[0].pr == 10
        assert result[0].issue == 42
        assert result[0].branch == "agent/issue-42"
        assert result[0].url == "https://github.com/org/repo/pull/10"
        assert result[0].draft is False
        assert result[0].title == "Fix widget"

    @pytest.mark.asyncio
    async def test_deduplicates_by_pr_number(self, event_bus, tmp_path):
        import json

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        pr_json = json.dumps(
            [
                {
                    "number": 42,
                    "url": "https://github.com/org/repo/pull/42",
                    "headRefName": "agent/issue-10",
                    "isDraft": False,
                    "title": "Dup PR",
                },
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(pr_json).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_open_prs(["label-a", "label-b"])

        # Same PR returned for both labels, should appear only once
        assert len(result) == 1
        assert result[0].pr == 42

    @pytest.mark.asyncio
    async def test_extracts_issue_number_from_branch(self, event_bus, tmp_path):
        import json

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        pr_json = json.dumps(
            [
                {
                    "number": 5,
                    "url": "",
                    "headRefName": "agent/issue-99",
                    "isDraft": False,
                    "title": "PR",
                },
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(pr_json).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_open_prs(["label"])

        assert result[0].issue == 99

    @pytest.mark.asyncio
    async def test_returns_zero_issue_for_non_agent_branch(self, event_bus, tmp_path):
        import json

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        pr_json = json.dumps(
            [
                {
                    "number": 5,
                    "url": "",
                    "headRefName": "feature/my-branch",
                    "isDraft": False,
                    "title": "Manual PR",
                },
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(pr_json).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_open_prs(["label"])

        assert result[0].issue == 0
        assert result[0].branch == "feature/my-branch"

    @pytest.mark.asyncio
    async def test_returns_empty_on_subprocess_failure(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("error").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_open_prs(["label"])

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_in_dry_run(self, dry_config, event_bus):
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_open_prs(["label"])

        mock_create.assert_not_called()
        assert result == []


# ---------------------------------------------------------------------------
# list_hitl_items
# ---------------------------------------------------------------------------


class TestListHitlItems:
    """Tests for PRManager.list_hitl_items."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_issues(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("[]").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_hitl_items(["hydraflow-hitl"])

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_issue_with_pr_info(self, event_bus, tmp_path):
        import json

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        issues_json = json.dumps(
            [
                {
                    "number": 42,
                    "title": "Fix widget",
                    "url": "https://github.com/org/repo/issues/42",
                },
            ]
        )
        pr_json = json.dumps(
            [{"number": 99, "url": "https://github.com/org/repo/pull/99"}]
        )

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = AsyncMock()
            if call_count == 1:
                mock_proc.returncode = 0
                mock_proc.communicate = AsyncMock(
                    return_value=(issues_json.encode(), b"")
                )
            else:
                mock_proc.returncode = 0
                mock_proc.communicate = AsyncMock(return_value=(pr_json.encode(), b""))
            mock_proc.wait = AsyncMock(return_value=0)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await mgr.list_hitl_items(["hydraflow-hitl"])

        assert len(result) == 1
        assert result[0].issue == 42
        assert result[0].title == "Fix widget"
        assert result[0].pr == 99
        assert result[0].prUrl == "https://github.com/org/repo/pull/99"
        assert result[0].branch == "agent/issue-42"

    @pytest.mark.asyncio
    async def test_fetch_hitl_raw_issues_uses_get_method(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        captured: list[tuple[str, ...]] = []

        async def mock_run_gh(*cmd, cwd=None):
            captured.append(cmd)
            return "[]"

        mgr._run_gh = mock_run_gh
        await mgr._fetch_hitl_raw_issues(["hydraflow-hitl"])

        assert len(captured) == 1
        cmd = captured[0]
        assert "--method" in cmd
        assert "GET" in cmd

    @pytest.mark.asyncio
    async def test_returns_zero_pr_when_no_pr_found(self, event_bus, tmp_path):
        import json

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        issues_json = json.dumps([{"number": 10, "title": "Broken thing", "url": ""}])

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = AsyncMock()
            if call_count == 1:
                mock_proc.returncode = 0
                mock_proc.communicate = AsyncMock(
                    return_value=(issues_json.encode(), b"")
                )
            else:
                mock_proc.returncode = 0
                mock_proc.communicate = AsyncMock(return_value=(b"[]", b""))
            mock_proc.wait = AsyncMock(return_value=0)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await mgr.list_hitl_items(["hydraflow-hitl"])

        assert len(result) == 1
        assert result[0].pr == 0
        assert result[0].prUrl == ""

    @pytest.mark.asyncio
    async def test_deduplicates_issues(self, event_bus, tmp_path):
        import json

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        issues_json = json.dumps([{"number": 42, "title": "Fix widget", "url": ""}])

        async def side_effect(*args, **kwargs):
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(issues_json.encode(), b""))
            mock_proc.wait = AsyncMock(return_value=0)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await mgr.list_hitl_items(["label-a", "label-b"])

        # Same issue from two labels, but only appears once
        assert len(result) == 1
        assert result[0].issue == 42

    @pytest.mark.asyncio
    async def test_returns_empty_on_subprocess_failure(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("error").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_hitl_items(["hydraflow-hitl"])

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_in_dry_run(self, dry_config, event_bus):
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_hitl_items(["hydraflow-hitl"])

        mock_create.assert_not_called()
        assert result == []

    @pytest.mark.asyncio
    async def test_concurrency_limits_simultaneous_pr_lookups(
        self, event_bus, tmp_path
    ):
        """concurrency kwarg caps how many _build_hitl_item calls run at once."""
        import json

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        # 5 issues, concurrency=2 — verify all 5 are still returned
        issues = [{"number": i, "title": f"Issue {i}", "url": ""} for i in range(1, 6)]
        issues_json = json.dumps(issues)
        pr_json = json.dumps([])  # no PRs found

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            if call_count == 1:
                mock_proc.communicate = AsyncMock(
                    return_value=(issues_json.encode(), b"")
                )
            else:
                mock_proc.communicate = AsyncMock(return_value=(pr_json.encode(), b""))
            mock_proc.wait = AsyncMock(return_value=0)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await mgr.list_hitl_items(["hydraflow-hitl"], concurrency=2)

        assert len(result) == 5
        # 1 issue-list call + 5 PR-lookup calls
        assert call_count == 6


# ---------------------------------------------------------------------------
# Retry wrapper usage verification
# ---------------------------------------------------------------------------


class TestRetryWrapperUsage:
    """Verify correct methods use retry vs plain run_subprocess."""

    @pytest.mark.asyncio
    async def test_push_branch_does_not_use_retry(self, config, event_bus, tmp_path):
        """push_branch must use run_subprocess (not retry) to avoid duplicate commits."""
        mgr = _make_manager(config, event_bus)
        with (
            patch("pr_manager.run_subprocess", new_callable=AsyncMock) as mock_plain,
            patch(
                "pr_manager.run_subprocess_with_retry", new_callable=AsyncMock
            ) as mock_retry,
        ):
            mock_plain.return_value = ""
            await mgr.push_branch(tmp_path, "agent/issue-42")

        mock_plain.assert_awaited_once()
        mock_retry.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_merge_pr_does_not_use_retry(self, config, event_bus):
        """merge_pr must use run_subprocess (not retry) to avoid race conditions."""
        mgr = _make_manager(config, event_bus)
        with (
            patch("pr_manager.run_subprocess", new_callable=AsyncMock) as mock_plain,
            patch(
                "pr_manager.run_subprocess_with_retry", new_callable=AsyncMock
            ) as mock_retry,
        ):
            mock_plain.return_value = ""
            await mgr.merge_pr(101)

        mock_plain.assert_awaited_once()
        mock_retry.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_labels_uses_retry(self, config, event_bus):
        """add_labels should use run_subprocess_with_retry."""
        mgr = _make_manager(config, event_bus)
        with patch(
            "pr_manager.run_subprocess_with_retry", new_callable=AsyncMock
        ) as mock_retry:
            mock_retry.return_value = ""
            await mgr.add_labels(42, ["bug"])

        mock_retry.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_pr_diff_uses_retry(self, config, event_bus):
        """get_pr_diff (read operation) should use run_subprocess_with_retry."""
        mgr = _make_manager(config, event_bus)
        with patch(
            "pr_manager.run_subprocess_with_retry", new_callable=AsyncMock
        ) as mock_retry:
            mock_retry.return_value = "diff content"
            await mgr.get_pr_diff(101)

        mock_retry.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_labels_uses_retry(self, event_bus, tmp_path):
        """ensure_labels_exist should use run_subprocess_with_retry via prep."""

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        with patch(
            "prep.run_subprocess_with_retry", new_callable=AsyncMock
        ) as mock_retry:
            mock_retry.return_value = "[]"
            await mgr.ensure_labels_exist()

        # 1 list call + 12 create calls = 13
        assert mock_retry.await_count == 1 + len(PRManager._HYDRAFLOW_LABELS)

    @pytest.mark.asyncio
    async def test_pull_main_uses_retry(self, config, event_bus):
        """pull_main should use run_subprocess_with_retry."""
        mgr = _make_manager(config, event_bus)
        with patch(
            "pr_manager.run_subprocess_with_retry", new_callable=AsyncMock
        ) as mock_retry:
            mock_retry.return_value = ""
            await mgr.pull_main()

        mock_retry.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_max_retries_from_config(self, event_bus, tmp_path):
        """PRManager should pass gh_max_retries from config to retry wrapper."""

        cfg = ConfigFactory.create(
            gh_max_retries=5,
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        with patch(
            "pr_manager.run_subprocess_with_retry", new_callable=AsyncMock
        ) as mock_retry:
            mock_retry.return_value = "diff content"
            await mgr.get_pr_diff(101)

        _, kwargs = mock_retry.call_args
        assert kwargs["max_retries"] == 5


# ---------------------------------------------------------------------------
# get_label_counts
# ---------------------------------------------------------------------------


class TestGetLabelCounts:
    """Tests for PRManager.get_label_counts."""

    @pytest.mark.asyncio
    async def test_returns_label_counts(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        # Mock _run_gh to return counts for each label query
        call_count = 0

        async def mock_run_gh(*cmd, cwd=None):
            nonlocal call_count
            call_count += 1
            # Return different counts for different calls
            if "issue" in cmd and "--state" in cmd:
                state_idx = list(cmd).index("--state") + 1
                state_val = cmd[state_idx]
                if state_val == "open":
                    return "3\n"
                elif state_val == "closed":
                    return "10\n"
            elif "pr" in cmd:
                return "8\n"
            return "0\n"

        mgr._run_gh = mock_run_gh

        result = await mgr.get_label_counts(cfg)

        assert "open_by_label" in result
        assert "total_closed" in result
        assert "total_merged" in result
        assert isinstance(result["open_by_label"], dict)

    @pytest.mark.asyncio
    async def test_caches_results_for_30_seconds(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        call_count = 0

        async def mock_run_gh(*cmd, cwd=None):
            nonlocal call_count
            call_count += 1
            return "5\n"

        mgr._run_gh = mock_run_gh

        # First call — should hit the gh CLI
        result1 = await mgr.get_label_counts(cfg)
        first_call_count = call_count

        # Second call — should return cached
        result2 = await mgr.get_label_counts(cfg)
        assert call_count == first_call_count  # No additional calls

        assert result1 == result2

    @pytest.mark.asyncio
    async def test_handles_errors_gracefully(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        async def mock_run_gh(*cmd, cwd=None):
            raise RuntimeError("network error")

        mgr._run_gh = mock_run_gh
        # Reset cache
        mgr._label_counts_cache = None
        mgr._label_counts_ts = 0.0

        result = await mgr.get_label_counts(cfg)

        # Should return zeros, not raise
        assert result["open_by_label"]["hydraflow-plan"] == 0
        assert result["total_closed"] == 0
        assert result["total_merged"] == 0


# ---------------------------------------------------------------------------
# Edge case tests for list_open_prs
# ---------------------------------------------------------------------------


class TestListOpenPrsEdgeCases:
    """Edge case tests for PRManager.list_open_prs."""

    @pytest.mark.asyncio
    async def test_list_open_prs_missing_headRefName_uses_empty_default(
        self, config, event_bus
    ) -> None:
        """PR JSON missing headRefName should use empty string fallback."""
        mgr = _make_manager(config, event_bus)

        # PR JSON with no headRefName field
        pr_json = json.dumps(
            [
                {
                    "number": 10,
                    "url": "https://github.com/org/repo/pull/10",
                    "isDraft": False,
                    "title": "Fix widget",
                },
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(pr_json).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_open_prs(["test-label"])

        assert len(result) == 1
        assert result[0].branch == ""
        assert result[0].issue == 0

    @pytest.mark.asyncio
    async def test_list_open_prs_skips_entry_missing_number(
        self, config, event_bus
    ) -> None:
        """PR JSON entry missing 'number' key should be skipped."""
        mgr = _make_manager(config, event_bus)

        pr_json = json.dumps(
            [
                {
                    "url": "https://github.com/org/repo/pull/10",
                    "headRefName": "agent/issue-10",
                    "isDraft": False,
                    "title": "Missing number field",
                },
                {
                    "number": 20,
                    "url": "https://github.com/org/repo/pull/20",
                    "headRefName": "agent/issue-20",
                    "isDraft": False,
                    "title": "Has number field",
                },
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(pr_json).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_open_prs(["test-label"])

        assert len(result) == 1
        assert result[0].pr == 20


# ---------------------------------------------------------------------------
# Narrowed exception handling (issue #879)
# ---------------------------------------------------------------------------


class TestListOpenPrsExceptionHandling:
    """Verify list_open_prs logs debug on per-item failures."""

    @pytest.mark.asyncio
    async def test_logs_debug_on_per_item_key_error(
        self, config, event_bus, caplog
    ) -> None:
        """A PR item missing 'number' key should be skipped with debug logging."""
        import logging

        mgr = _make_manager(config, event_bus)
        # JSON with one item missing the 'number' key
        pr_json = json.dumps([{"url": "...", "headRefName": "agent/issue-1"}])
        mock_create = SubprocessMockBuilder().with_stdout(pr_json).build()

        with (
            caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"),
            patch("asyncio.create_subprocess_exec", mock_create),
        ):
            result = await mgr.list_open_prs(["label"])

        assert result == []
        assert "Skipping PR in list_open_prs" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_debug_on_subprocess_failure(
        self, config, event_bus, caplog
    ) -> None:
        """Subprocess failure should be logged at debug and return empty."""
        import logging

        mgr = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("gh error").build()
        )

        with (
            caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"),
            patch("asyncio.create_subprocess_exec", mock_create),
        ):
            result = await mgr.list_open_prs(["label"])

        assert result == []
        assert "Skipping PR in list_open_prs" in caplog.text


class TestListHitlItemsExceptionHandling:
    """Verify list_hitl_items logs for various failure scenarios."""

    @pytest.mark.asyncio
    async def test_logs_warning_on_label_fetch_failure(
        self, config, event_bus, tmp_path, caplog
    ) -> None:
        """Label fetch failure should log a warning."""
        import logging

        from config import HydraFlowConfig

        cfg = HydraFlowConfig(
            ready_label=config.ready_label,
            repo=config.repo,
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("gh error").build()
        )

        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.pr_manager"),
            patch("asyncio.create_subprocess_exec", mock_create),
        ):
            result = await mgr.list_hitl_items(["hydraflow-hitl"])

        assert result == []
        assert "Failed to fetch HITL issues for label" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_debug_on_pr_lookup_failure(
        self, config, event_bus, tmp_path, caplog
    ) -> None:
        """PR lookup failure should log debug and set pr_number=0."""
        import logging

        from config import HydraFlowConfig

        cfg = HydraFlowConfig(
            ready_label=config.ready_label,
            repo=config.repo,
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        issues_json = json.dumps([{"number": 42, "title": "Test", "url": ""}])
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = AsyncMock()
            if call_count == 1:
                # Issue list succeeds
                mock_proc.returncode = 0
                mock_proc.communicate = AsyncMock(
                    return_value=(issues_json.encode(), b"")
                )
            else:
                # PR lookup fails
                mock_proc.returncode = 1
                mock_proc.communicate = AsyncMock(
                    return_value=(b"", b"pr lookup error")
                )
            mock_proc.wait = AsyncMock(return_value=mock_proc.returncode)
            return mock_proc

        with (
            caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"),
            patch("asyncio.create_subprocess_exec", side_effect=side_effect),
        ):
            result = await mgr.list_hitl_items(["hydraflow-hitl"])

        assert len(result) == 1
        assert result[0].pr == 0
        assert "PR lookup failed for branch" in caplog.text

    @pytest.mark.asyncio
    async def test_per_item_failure_logs_debug_and_filters_out(
        self, config, event_bus, tmp_path, caplog
    ) -> None:
        """Individual item build failures are logged at debug and excluded from result.

        With asyncio.gather(return_exceptions=True) each failed item is captured
        individually rather than propagating to the outer handler, so the remaining
        items are still returned.  A debug-level entry is emitted for each failure.
        """
        import logging

        from config import HydraFlowConfig

        cfg = HydraFlowConfig(
            ready_label=config.ready_label,
            repo=config.repo,
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)

        # Issue list succeeds, but branch_for_issue raises KeyError for every item.
        issues_json = json.dumps([{"number": 42, "title": "Test", "url": ""}])
        mock_create = SubprocessMockBuilder().with_stdout(issues_json).build()

        with (
            caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"),
            patch("asyncio.create_subprocess_exec", mock_create),
            patch(
                "config.HydraFlowConfig.branch_for_issue",
                side_effect=KeyError("bad"),
            ),
        ):
            result = await mgr.list_hitl_items(["hydraflow-hitl"])

        assert result == []
        assert "Failed to build HITL item" in caplog.text


# ---------------------------------------------------------------------------
# get_pr_head_sha (issue #853)
# ---------------------------------------------------------------------------


class TestGetPrHeadSha:
    """Tests for PRManager.get_pr_head_sha."""

    @pytest.mark.asyncio
    async def test_returns_sha_on_success(self, event_bus, tmp_path):
        """get_pr_head_sha should parse headRefOid from JSON response."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        response = '{"headRefOid":"abc123def456789"}'
        mock_create = SubprocessMockBuilder().with_stdout(response).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            sha = await mgr.get_pr_head_sha(101)

        assert sha == "abc123def456789"

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self, event_bus, tmp_path):
        """get_pr_head_sha should return empty string on subprocess failure."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("not found").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            sha = await mgr.get_pr_head_sha(999)

        assert sha == ""

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty(self, dry_config, event_bus):
        """In dry-run mode, get_pr_head_sha should return empty string."""
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            sha = await mgr.get_pr_head_sha(101)

        mock_create.assert_not_called()
        assert sha == ""


# ---------------------------------------------------------------------------
# get_pr_reviews (issue #853)
# ---------------------------------------------------------------------------


class TestGetPrReviews:
    """Tests for PRManager.get_pr_reviews."""

    @pytest.mark.asyncio
    async def test_returns_reviews_on_success(self, event_bus, tmp_path):
        """get_pr_reviews should parse review data from JSON response."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        response = json.dumps(
            [
                {
                    "author": "reviewer1",
                    "state": "APPROVED",
                    "submitted_at": "2025-01-01T00:00:00Z",
                    "commit_id": "abc123",
                }
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(response).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            reviews = await mgr.get_pr_reviews(101)

        assert len(reviews) == 1
        assert reviews[0]["author"] == "reviewer1"
        assert reviews[0]["state"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self, event_bus, tmp_path):
        """get_pr_reviews should return empty list on subprocess failure."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("not found").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            reviews = await mgr.get_pr_reviews(999)

        assert reviews == []

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty(self, dry_config, event_bus):
        """In dry-run mode, get_pr_reviews should return empty list."""
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            reviews = await mgr.get_pr_reviews(101)

        mock_create.assert_not_called()
        assert reviews == []


# ---------------------------------------------------------------------------
# get_pr_mergeable (issue #1608)
# ---------------------------------------------------------------------------


class TestGetPrMergeable:
    """Tests for PRManager.get_pr_mergeable."""

    @pytest.mark.asyncio
    async def test_returns_true_when_mergeable(self, event_bus, tmp_path):
        """get_pr_mergeable returns True when GitHub says 'true'."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("true\n").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.get_pr_mergeable(101)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_mergeable(self, event_bus, tmp_path):
        """get_pr_mergeable returns False when GitHub says 'false'."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("false\n").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.get_pr_mergeable(101)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_none_when_null(self, event_bus, tmp_path):
        """get_pr_mergeable returns None when GitHub says 'null'."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("null\n").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.get_pr_mergeable(101)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self, event_bus, tmp_path):
        """get_pr_mergeable returns None on API failure."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("not found").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.get_pr_mergeable(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_dry_run_returns_none(self, dry_config, event_bus):
        """In dry-run mode, get_pr_mergeable returns None."""
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.get_pr_mergeable(101)

        mock_create.assert_not_called()
        assert result is None


# ---------------------------------------------------------------------------
# get_pr_comments (issue #853)
# ---------------------------------------------------------------------------


class TestGetPrComments:
    """Tests for PRManager.get_pr_comments."""

    @pytest.mark.asyncio
    async def test_returns_comments_on_success(self, event_bus, tmp_path):
        """get_pr_comments should parse comment data from JSON response."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        response = json.dumps(
            [
                {
                    "author": "commenter1",
                    "created_at": "2025-01-01T12:00:00Z",
                }
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(response).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            comments = await mgr.get_pr_comments(101)

        assert len(comments) == 1
        assert comments[0]["author"] == "commenter1"
        assert comments[0]["created_at"] == "2025-01-01T12:00:00Z"

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self, event_bus, tmp_path):
        """get_pr_comments should return empty list on subprocess failure."""
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("not found").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            comments = await mgr.get_pr_comments(999)

        assert comments == []

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty(self, dry_config, event_bus):
        """In dry-run mode, get_pr_comments should return empty list."""
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            comments = await mgr.get_pr_comments(101)

        mock_create.assert_not_called()
        assert comments == []


# ---------------------------------------------------------------------------
# Decomposed get_label_counts helpers
# ---------------------------------------------------------------------------


class TestCountHelpers:
    """Tests for _count_open_issues_by_label, _count_closed_issues, _count_merged_prs."""

    @pytest.mark.asyncio
    async def test_count_open_issues_by_label(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=[5, 7])
        result = await mgr._count_open_issues_by_label(
            {
                "hydraflow-plan": ["hydraflow-plan"],
                "hydraflow-ready": ["hydraflow-ready"],
            }
        )
        assert result == {"hydraflow-plan": 5, "hydraflow-ready": 7}

    @pytest.mark.asyncio
    async def test_count_open_issues_by_label_handles_errors_returns_zero_count(
        self, event_bus, tmp_path
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=RuntimeError("network error"))
        result = await mgr._count_open_issues_by_label(
            {"hydraflow-plan": ["hydraflow-plan"]}
        )
        assert result == {"hydraflow-plan": 0}

    @pytest.mark.asyncio
    async def test_count_open_issues_by_label_handles_errors_logs_debug_message(
        self, event_bus, tmp_path, caplog
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=RuntimeError("network error"))
        with caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"):
            await mgr._count_open_issues_by_label(
                {"hydraflow-plan": ["hydraflow-plan"]}
            )
        assert "Could not count open issues for label" in caplog.text

    @pytest.mark.asyncio
    async def test_count_open_issues_by_label_handles_value_error_returns_zero_count(
        self, event_bus, tmp_path
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=ValueError("bad parse"))
        result = await mgr._count_open_issues_by_label(
            {"hydraflow-plan": ["hydraflow-plan"]}
        )
        assert result == {"hydraflow-plan": 0}

    @pytest.mark.asyncio
    async def test_count_closed_issues(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=[7, 8])
        result = await mgr._count_closed_issues(["hydraflow-fixed", "hf-fixed-alt"])
        assert result == 15

    @pytest.mark.asyncio
    async def test_count_closed_issues_handles_errors_returns_zero_count(
        self, event_bus, tmp_path
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=RuntimeError("network error"))
        result = await mgr._count_closed_issues(["hydraflow-fixed"])
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_closed_issues_handles_errors_logs_debug_message(
        self, event_bus, tmp_path, caplog
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=RuntimeError("network error"))
        with caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"):
            await mgr._count_closed_issues(["hydraflow-fixed"])
        assert "Could not count closed issues for label" in caplog.text

    @pytest.mark.asyncio
    async def test_count_closed_issues_handles_value_error_returns_zero_count(
        self, event_bus, tmp_path
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=ValueError("bad parse"))
        result = await mgr._count_closed_issues(["hydraflow-fixed"])
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_merged_prs(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(return_value=12)
        result = await mgr._count_merged_prs("hydraflow-fixed")
        assert result == 12

    @pytest.mark.asyncio
    async def test_count_merged_prs_handles_errors_returns_zero_count(
        self, event_bus, tmp_path
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=RuntimeError("network error"))
        result = await mgr._count_merged_prs("hydraflow-fixed")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_merged_prs_handles_errors_logs_debug_message(
        self, event_bus, tmp_path, caplog
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=RuntimeError("network error"))
        with caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"):
            await mgr._count_merged_prs("hydraflow-fixed")
        assert "Could not count merged PRs for label" in caplog.text

    @pytest.mark.asyncio
    async def test_count_merged_prs_handles_value_error_returns_zero_count(
        self, event_bus, tmp_path
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=ValueError("bad parse"))
        result = await mgr._count_merged_prs("hydraflow-fixed")
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_open_issues_by_label_uses_search_api(
        self, event_bus, tmp_path
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        captured_queries: list[str] = []

        async def mock_search(query: str) -> int:
            captured_queries.append(query)
            return 5

        mgr._search_github_count = mock_search
        result = await mgr._count_open_issues_by_label(
            {"hydraflow-plan": ["hydraflow-plan"]}
        )
        assert result == {"hydraflow-plan": 5}
        assert captured_queries == [
            'repo:test-org/test-repo is:issue is:open label:"hydraflow-plan"'
        ]

    @pytest.mark.asyncio
    async def test_count_closed_issues_uses_search_api(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        captured_queries: list[str] = []

        async def mock_search(query: str) -> int:
            captured_queries.append(query)
            return 7

        mgr._search_github_count = mock_search
        result = await mgr._count_closed_issues(["hydraflow-fixed"])
        assert result == 7
        assert captured_queries == [
            'repo:test-org/test-repo is:issue is:closed label:"hydraflow-fixed"'
        ]

    @pytest.mark.asyncio
    async def test_count_merged_prs_uses_search_api(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        captured_queries: list[str] = []

        async def mock_search(query: str) -> int:
            captured_queries.append(query)
            return 12

        mgr._search_github_count = mock_search
        result = await mgr._count_merged_prs("hydraflow-fixed")
        assert result == 12
        assert captured_queries == [
            'repo:test-org/test-repo is:pr is:merged label:"hydraflow-fixed"'
        ]
