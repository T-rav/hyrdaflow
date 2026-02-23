"""Tests for issue_fetcher.py - IssueFetcher class."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from issue_fetcher import IssueFetcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RAW_ISSUE_JSON = json.dumps(
    [
        {
            "number": 42,
            "title": "Fix bug",
            "body": "Details",
            "labels": [{"name": "ready"}],
            "comments": [],
            "url": "https://github.com/test-org/test-repo/issues/42",
        }
    ]
)


# ---------------------------------------------------------------------------
# fetch_ready_issues
# ---------------------------------------------------------------------------


class TestFetchReadyIssues:
    """Tests for the fetch_ready_issues method."""

    @pytest.mark.asyncio
    async def test_returns_parsed_issues_from_gh_output(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(RAW_ISSUE_JSON.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(set())

        assert len(issues) == 1
        assert issues[0].number == 42
        assert issues[0].title == "Fix bug"
        assert issues[0].body == "Details"
        assert issues[0].labels == ["ready"]

    @pytest.mark.asyncio
    async def test_parses_label_dict_and_string(self, config: HydraFlowConfig) -> None:
        raw = json.dumps(
            [
                {
                    "number": 10,
                    "title": "Test",
                    "body": "",
                    "labels": [{"name": "alpha"}, "beta"],
                    "comments": [],
                    "url": "",
                }
            ]
        )
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(raw.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(set())

        assert "alpha" in issues[0].labels
        assert "beta" in issues[0].labels

    @pytest.mark.asyncio
    async def test_parses_comment_dict_and_string(
        self, config: HydraFlowConfig
    ) -> None:
        raw = json.dumps(
            [
                {
                    "number": 11,
                    "title": "T",
                    "body": "",
                    "labels": [],
                    "comments": [{"body": "hello"}, "world"],
                    "url": "",
                }
            ]
        )
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(raw.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(set())

        assert "hello" in issues[0].comments
        assert "world" in issues[0].comments

    @pytest.mark.asyncio
    async def test_skips_active_issues(self, config: HydraFlowConfig) -> None:
        """Issues already active in this run should be skipped."""
        fetcher = IssueFetcher(config)
        active_issues: set[int] = {42}

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(RAW_ISSUE_JSON.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(active_issues)

        assert issues == []

    @pytest.mark.asyncio
    async def test_does_not_skip_failed_issues_on_restart(
        self, config: HydraFlowConfig
    ) -> None:
        """Failed issues with hydraflow-ready label should be retried (no state filter)."""
        fetcher = IssueFetcher(config)
        # NOT in active_issues → should be picked up

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(RAW_ISSUE_JSON.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(set())

        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_gh_fails(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error: not found"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(set())

        assert issues == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_json_decode_error(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"not-json", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(set())

        assert issues == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_gh_not_found(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("gh not found"),
        ):
            issues = await fetcher.fetch_ready_issues(set())

        assert issues == []

    @pytest.mark.asyncio
    async def test_respects_queue_size_limit(self, config: HydraFlowConfig) -> None:
        """Result list is truncated to 2 * max_workers."""
        raw = json.dumps(
            [
                {
                    "number": i,
                    "title": f"Issue {i}",
                    "body": "",
                    "labels": [],
                    "comments": [],
                    "url": "",
                }
                for i in range(1, 10)
            ]
        )
        fetcher = IssueFetcher(config)
        # config has max_workers=2 from conftest → queue_size = 4
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(raw.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(set())

        assert len(issues) <= 2 * config.max_workers

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty_list(self, config: HydraFlowConfig) -> None:
        from config import HydraFlowConfig

        dry_config = HydraFlowConfig(**{**config.model_dump(), "dry_run": True})
        fetcher = IssueFetcher(dry_config)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            issues = await fetcher.fetch_ready_issues(set())

        assert issues == []
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_label_includes_created_asc_sort(
        self, config: HydraFlowConfig
    ) -> None:
        """_query_label passes --search sort:created-asc to gh issue list."""
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(RAW_ISSUE_JSON.encode(), b""))

        with patch(
            "asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            await fetcher.fetch_ready_issues(set())

        cmd = list(mock_exec.call_args_list[0].args)
        assert "--search" in cmd
        search_idx = cmd.index("--search")
        assert cmd[search_idx + 1] == "sort:created-asc"


# ---------------------------------------------------------------------------
# fetch_reviewable_prs
# ---------------------------------------------------------------------------


class TestFetchReviewablePrs:
    """Tests for fetch_reviewable_prs: skip logic, parsing, and error handling."""

    @pytest.mark.asyncio
    async def test_skips_active_issues(self, config: HydraFlowConfig) -> None:
        """Issues already active in this run should be skipped."""
        fetcher = IssueFetcher(config)
        active_issues: set[int] = {42}

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(RAW_ISSUE_JSON.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            prs, issues = await fetcher.fetch_reviewable_prs(active_issues)

        assert prs == []
        assert issues == []

    @pytest.mark.asyncio
    async def test_picks_up_previously_reviewed_issues(
        self, config: HydraFlowConfig
    ) -> None:
        """Issues reviewed in a prior run should be picked up again."""
        fetcher = IssueFetcher(config)
        # NOT in active_issues → should be picked up

        pr_json = json.dumps(
            [
                {
                    "number": 200,
                    "url": "https://github.com/o/r/pull/200",
                    "isDraft": False,
                }
            ]
        )

        async def fake_run(*args: str, **kwargs: Any) -> str:
            if "issue" in args:
                return RAW_ISSUE_JSON
            return pr_json

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_parses_pr_json_into_pr_info(self, config: HydraFlowConfig) -> None:
        """Successfully parses PR JSON and maps to PRInfo objects."""
        fetcher = IssueFetcher(config)

        pr_json = json.dumps(
            [
                {
                    "number": 200,
                    "url": "https://github.com/o/r/pull/200",
                    "isDraft": False,
                }
            ]
        )

        async def fake_run(*args: str, **kwargs: Any) -> str:
            if "issue" in args:
                return RAW_ISSUE_JSON
            return pr_json

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert len(prs) == 1
        assert prs[0].number == 200
        assert prs[0].issue_number == 42
        assert prs[0].branch == "agent/issue-42"
        assert prs[0].url == "https://github.com/o/r/pull/200"
        assert prs[0].draft is False
        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_gh_cli_failure_skips_pr_for_that_issue(
        self, config: HydraFlowConfig
    ) -> None:
        """gh CLI failure (RuntimeError) skips that issue's PR but preserves issues."""
        fetcher = IssueFetcher(config)

        async def fake_run(*args: str, **kwargs: Any) -> str:
            if "issue" in args:
                return RAW_ISSUE_JSON
            raise RuntimeError("Command failed (rc=1): some error")

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert prs == []
        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_json_decode_error_skips_pr_for_that_issue(
        self, config: HydraFlowConfig
    ) -> None:
        """Invalid JSON from gh CLI skips that issue's PR but preserves issues."""
        fetcher = IssueFetcher(config)

        async def fake_run(*args: str, **kwargs: Any) -> str:
            if "issue" in args:
                return RAW_ISSUE_JSON
            return "not-valid-json"

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert prs == []
        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_draft_prs_excluded_from_results(
        self, config: HydraFlowConfig
    ) -> None:
        """Draft PRs are filtered out of the returned PR list."""
        fetcher = IssueFetcher(config)

        pr_json = json.dumps(
            [
                {
                    "number": 200,
                    "url": "https://github.com/o/r/pull/200",
                    "isDraft": True,
                }
            ]
        )

        async def fake_run(*args: str, **kwargs: Any) -> str:
            if "issue" in args:
                return RAW_ISSUE_JSON
            return pr_json

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert prs == []
        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_no_matching_pr_returns_empty_pr_list(
        self, config: HydraFlowConfig
    ) -> None:
        """Empty JSON array from PR lookup means no PRInfo is created."""
        fetcher = IssueFetcher(config)

        async def fake_run(*args: str, **kwargs: Any) -> str:
            if "issue" in args:
                return RAW_ISSUE_JSON
            return "[]"

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert prs == []
        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_file_not_found_error_when_gh_missing(
        self, config: HydraFlowConfig
    ) -> None:
        """FileNotFoundError during issue fetch returns ([], []) early."""
        fetcher = IssueFetcher(config)

        mock_create = AsyncMock(side_effect=FileNotFoundError("No such file: 'gh'"))

        with patch("asyncio.create_subprocess_exec", mock_create):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert prs == []
        assert issues == []

    @pytest.mark.asyncio
    async def test_missing_number_key_in_pr_json_skips_pr(
        self, config: HydraFlowConfig
    ) -> None:
        """PR JSON missing 'number' key should be caught by KeyError handler and PR skipped."""
        fetcher = IssueFetcher(config)

        # PR data is missing the "number" key
        pr_json_missing_number = json.dumps(
            [
                {
                    "url": "https://github.com/o/r/pull/200",
                    "isDraft": False,
                }
            ]
        )

        async def fake_run(*args: str, **kwargs: Any) -> str:
            if "issue" in args:
                return RAW_ISSUE_JSON
            return pr_json_missing_number

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        # PR should be skipped due to KeyError on "number"
        assert prs == []
        # Issue should still be returned
        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty_tuple(
        self, dry_config: HydraFlowConfig
    ) -> None:
        """Dry-run mode returns ([], []) without making subprocess calls."""
        fetcher = IssueFetcher(dry_config)

        mock_create = AsyncMock()

        with patch("asyncio.create_subprocess_exec", mock_create):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert prs == []
        assert issues == []
        mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_plan_issues
# ---------------------------------------------------------------------------


RAW_PLAN_ISSUE_JSON = json.dumps(
    [
        {
            "number": 42,
            "title": "Fix bug",
            "body": "Details",
            "labels": [{"name": "hydraflow-plan"}],
            "comments": [],
            "url": "https://github.com/test-org/test-repo/issues/42",
        }
    ]
)


class TestFetchPlanIssues:
    """Tests for the fetch_plan_issues method."""

    @pytest.mark.asyncio
    async def test_returns_parsed_issues_from_gh_output(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(RAW_PLAN_ISSUE_JSON.encode(), b"")
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_plan_issues()

        assert len(issues) == 1
        assert issues[0].number == 42
        assert issues[0].title == "Fix bug"
        assert issues[0].labels == ["hydraflow-plan"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_gh_fails(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error: not found"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_plan_issues()

        assert issues == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_json_decode_error(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"not-json", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_plan_issues()

        assert issues == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_gh_not_found(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("gh not found"),
        ):
            issues = await fetcher.fetch_plan_issues()

        assert issues == []

    @pytest.mark.asyncio
    async def test_respects_batch_size_limit(self, config: HydraFlowConfig) -> None:
        """Result list is truncated to batch_size."""
        raw = json.dumps(
            [
                {
                    "number": i,
                    "title": f"Issue {i}",
                    "body": "",
                    "labels": [{"name": "hydraflow-plan"}],
                    "comments": [],
                    "url": "",
                }
                for i in range(1, 10)
            ]
        )
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(raw.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_plan_issues()

        assert len(issues) <= config.batch_size

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty_list(self, config: HydraFlowConfig) -> None:
        from config import HydraFlowConfig as HC

        dry_config = HC(**{**config.model_dump(), "dry_run": True})
        fetcher = IssueFetcher(dry_config)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            issues = await fetcher.fetch_plan_issues()

        assert issues == []
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_planner_label_fetches_all_excluding_downstream(
        self, config: HydraFlowConfig
    ) -> None:
        """When planner_label is empty, fetch all open issues excluding downstream labels."""
        from config import HydraFlowConfig as HC

        no_plan_config = HC(**{**config.model_dump(), "planner_label": []})
        fetcher = IssueFetcher(no_plan_config)

        raw = json.dumps(
            [
                {
                    "number": 1,
                    "title": "Unlabeled issue",
                    "body": "Body",
                    "labels": [],
                    "comments": [],
                    "url": "",
                },
                {
                    "number": 2,
                    "title": "Ready issue",
                    "body": "Body",
                    "labels": [{"name": "test-label"}],
                    "comments": [],
                    "url": "",
                },
            ]
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(raw.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_plan_issues()

        # Issue #2 has ready_label ("test-label") so it should be filtered out
        assert len(issues) == 1
        assert issues[0].number == 1


# ---------------------------------------------------------------------------
# fetch_issue_by_number
# ---------------------------------------------------------------------------

SINGLE_ISSUE_JSON = json.dumps(
    {
        "number": 42,
        "title": "Fix bug",
        "body": "Details",
        "labels": [{"name": "ready"}],
        "comments": [{"body": "first comment"}],
        "url": "https://github.com/test-org/test-repo/issues/42",
        "createdAt": "2026-01-01T00:00:00Z",
    }
)


class TestFetchIssueByNumber:
    """Tests for IssueFetcher.fetch_issue_by_number."""

    @pytest.mark.asyncio
    async def test_returns_parsed_issue_on_success(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(SINGLE_ISSUE_JSON.encode(), b"")
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issue = await fetcher.fetch_issue_by_number(42)

        assert issue is not None
        assert issue.number == 42
        assert issue.title == "Fix bug"
        assert issue.body == "Details"

    @pytest.mark.asyncio
    async def test_returns_none_on_gh_failure(self, config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error: not found"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issue = await fetcher.fetch_issue_by_number(999)

        assert issue is None

    @pytest.mark.asyncio
    async def test_returns_none_on_json_decode_error(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"not-json", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issue = await fetcher.fetch_issue_by_number(42)

        assert issue is None

    @pytest.mark.asyncio
    async def test_dry_run_returns_none(self, dry_config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(dry_config)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            issue = await fetcher.fetch_issue_by_number(42)

        assert issue is None
        mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_issue_comments
# ---------------------------------------------------------------------------


class TestFetchIssueComments:
    """Tests for IssueFetcher.fetch_issue_comments."""

    @pytest.mark.asyncio
    async def test_returns_comment_bodies(self, config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(config)
        comments_json = json.dumps({"comments": [{"body": "c1"}, {"body": "c2"}]})
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(comments_json.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await fetcher.fetch_issue_comments(42)

        assert result == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_handles_string_comments(self, config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(config)
        comments_json = json.dumps(
            {"comments": [{"body": "dict comment"}, "plain string"]}
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(comments_json.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await fetcher.fetch_issue_comments(42)

        assert result == ["dict comment", "plain string"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_failure(self, config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await fetcher.fetch_issue_comments(42)

        assert result == []

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty_list(
        self, dry_config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(dry_config)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await fetcher.fetch_issue_comments(42)

        assert result == []
        mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_issues_by_labels
# ---------------------------------------------------------------------------


class TestFetchIssuesByLabels:
    """Tests for IssueFetcher.fetch_issues_by_labels."""

    @pytest.mark.asyncio
    async def test_fetches_and_deduplicates_by_number(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        # Both labels return the same issue #42
        raw = json.dumps(
            [
                {
                    "number": 42,
                    "title": "Fix bug",
                    "body": "Details",
                    "labels": [{"name": "label-a"}, {"name": "label-b"}],
                    "comments": [],
                    "url": "https://github.com/test-org/test-repo/issues/42",
                }
            ]
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(raw.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_issues_by_labels(
                ["label-a", "label-b"], limit=10
            )

        # Same issue returned for both labels → deduplicated to 1
        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_exclude_labels_filter_correctly(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        raw = json.dumps(
            [
                {
                    "number": 1,
                    "title": "Keep me",
                    "body": "",
                    "labels": [],
                    "comments": [],
                    "url": "",
                },
                {
                    "number": 2,
                    "title": "Exclude me",
                    "body": "",
                    "labels": [{"name": "hydraflow-review"}],
                    "comments": [],
                    "url": "",
                },
            ]
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(raw.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_issues_by_labels(
                [], limit=10, exclude_labels=["hydraflow-review"]
            )

        assert len(issues) == 1
        assert issues[0].number == 1

    @pytest.mark.asyncio
    async def test_empty_labels_and_no_exclude_returns_empty(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            issues = await fetcher.fetch_issues_by_labels([], limit=10)

        assert issues == []
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_gh_failure_returns_empty_list(self, config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_issues_by_labels(["some-label"], limit=10)

        assert issues == []


# ---------------------------------------------------------------------------
# fetch_all_hydraflow_issues
# ---------------------------------------------------------------------------


class TestFetchAllHydraFlowIssues:
    """Tests for IssueFetcher.fetch_all_hydraflow_issues."""

    @pytest.mark.asyncio
    async def test_collects_all_pipeline_labels(self, config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(config)
        raw = json.dumps(
            [
                {
                    "number": 1,
                    "title": "Issue 1",
                    "body": "",
                    "labels": [{"name": "hydraflow-find"}],
                    "comments": [],
                    "url": "",
                }
            ]
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(raw.encode(), b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_all_hydraflow_issues()

        assert len(issues) >= 1
        assert issues[0].number == 1

    @pytest.mark.asyncio
    async def test_returns_empty_on_dry_run(self, dry_config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(dry_config)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            issues = await fetcher.fetch_all_hydraflow_issues()

        assert issues == []
        mock_exec.assert_not_called()
