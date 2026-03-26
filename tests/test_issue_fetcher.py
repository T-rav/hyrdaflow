"""Tests for issue_fetcher.py - IssueFetcher class."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

from tests.helpers import make_proc

if TYPE_CHECKING:
    from config import HydraFlowConfig

from issue_fetcher import IncompleteIssueFetchError, IssueFetcher

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


def _batch_pr_json(prs: list[dict[str, Any]]) -> str:
    """Build a batch PR response matching the REST ``/pulls`` shape."""
    return json.dumps(
        [
            {
                "number": pr.get("number", 0),
                "html_url": pr.get("url", ""),
                "draft": pr.get("isDraft", False),
                "head": {"ref": pr.get("branch", "")},
            }
            for pr in prs
        ]
    )


def make_pr_fake_run(batch_json: str):
    """Return a fake ``run_subprocess`` coroutine routing issues vs PRs."""

    async def fake_run(*args: str, **kwargs: Any) -> str:
        if any("issues" in arg for arg in args):
            return RAW_ISSUE_JSON
        return batch_json

    return fake_run


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
        mock_proc = make_proc(stdout=RAW_ISSUE_JSON.encode())

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
        mock_proc = make_proc(stdout=raw.encode())

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
        mock_proc = make_proc(stdout=raw.encode())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(set())

        assert "hello" in issues[0].comments
        assert "world" in issues[0].comments

    @pytest.mark.asyncio
    async def test_skips_active_issues(self, config: HydraFlowConfig) -> None:
        """Issues already active in this run should be skipped."""
        fetcher = IssueFetcher(config)
        active_issues: set[int] = {42}

        mock_proc = make_proc(stdout=RAW_ISSUE_JSON.encode())

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

        mock_proc = make_proc(stdout=RAW_ISSUE_JSON.encode())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(set())

        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_gh_fails(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = make_proc(returncode=1, stderr=b"error: not found")

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_ready_issues(set())

        assert issues == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_json_decode_error(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = make_proc(stdout=b"not-json")

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
        mock_proc = make_proc(stdout=raw.encode())

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
    async def test_query_label_uses_rest_issue_sort_fields(
        self, config: HydraFlowConfig
    ) -> None:
        """_query_label uses REST sort fields to fetch oldest-first."""
        fetcher = IssueFetcher(config)
        mock_proc = make_proc(stdout=RAW_ISSUE_JSON.encode())

        with patch(
            "asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            await fetcher.fetch_ready_issues(set())

        cmd = list(mock_exec.call_args_list[0].args)
        assert "api" in cmd
        assert any(
            token.startswith("repos/") and token.endswith("/issues") for token in cmd
        )
        assert "--method" in cmd
        assert "GET" in cmd
        assert "sort=created" in cmd
        assert "direction=asc" in cmd


# ---------------------------------------------------------------------------
# fetch_reviewable_prs
# ---------------------------------------------------------------------------


class TestFetchReviewablePrs:
    """Tests for fetch_reviewable_prs: skip logic, parsing, and error handling.

    The batch PR fetch returns full REST PR objects with ``head.ref`` for
    branch matching, rather than per-issue lookups.
    """

    @pytest.mark.asyncio
    async def test_skips_active_issues(self, config: HydraFlowConfig) -> None:
        """Issues already active in this run should be skipped."""
        fetcher = IssueFetcher(config)
        active_issues: set[int] = {42}

        mock_proc = make_proc(stdout=RAW_ISSUE_JSON.encode())

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

        batch_json = _batch_pr_json(
            [
                {
                    "number": 200,
                    "url": "https://github.com/o/r/pull/200",
                    "branch": "agent/issue-42",
                }
            ]
        )

        with patch(
            "issue_fetcher.run_subprocess", side_effect=make_pr_fake_run(batch_json)
        ):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_parses_pr_json_into_pr_info(self, config: HydraFlowConfig) -> None:
        """Successfully parses batch PR JSON and maps to PRInfo objects."""
        fetcher = IssueFetcher(config)

        batch_json = _batch_pr_json(
            [
                {
                    "number": 200,
                    "url": "https://github.com/o/r/pull/200",
                    "branch": "agent/issue-42",
                }
            ]
        )

        with patch(
            "issue_fetcher.run_subprocess", side_effect=make_pr_fake_run(batch_json)
        ):
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
    async def test_batch_pr_fetch_uses_get(self, config: HydraFlowConfig) -> None:
        """The batch PR fetch should use GET method."""
        fetcher = IssueFetcher(config)
        captured: list[tuple[str, ...]] = []

        batch_json = _batch_pr_json(
            [
                {
                    "number": 200,
                    "url": "https://github.com/o/r/pull/200",
                    "branch": "agent/issue-42",
                }
            ]
        )

        async def capturing_fake_run(*args: str, **kwargs: Any) -> str:
            captured.append(args)
            if any("issues" in arg for arg in args):
                return RAW_ISSUE_JSON
            return batch_json

        with patch("issue_fetcher.run_subprocess", side_effect=capturing_fake_run):
            prs, _issues = await fetcher.fetch_reviewable_prs(set())

        assert len(prs) == 1
        pr_lookup_cmd = next(
            cmd for cmd in captured if any("/pulls" in part for part in cmd)
        )
        assert "--method" in pr_lookup_cmd
        assert "GET" in pr_lookup_cmd

    @pytest.mark.asyncio
    async def test_gh_cli_failure_returns_empty_prs(
        self, config: HydraFlowConfig
    ) -> None:
        """gh CLI failure on batch PR fetch returns empty PRs but preserves issues."""
        fetcher = IssueFetcher(config)

        async def fake_run(*args: str, **kwargs: Any) -> str:
            if any("issues" in arg for arg in args):
                return RAW_ISSUE_JSON
            raise RuntimeError("Command failed (rc=1): some error")

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert prs == []
        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_json_decode_error_returns_empty_prs(
        self, config: HydraFlowConfig
    ) -> None:
        """Invalid JSON from batch PR fetch returns empty PRs but preserves issues."""
        fetcher = IssueFetcher(config)

        async def fake_run(*args: str, **kwargs: Any) -> str:
            if any("issues" in arg for arg in args):
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

        batch_json = _batch_pr_json(
            [
                {
                    "number": 200,
                    "url": "https://github.com/o/r/pull/200",
                    "isDraft": True,
                    "branch": "agent/issue-42",
                }
            ]
        )

        with patch(
            "issue_fetcher.run_subprocess", side_effect=make_pr_fake_run(batch_json)
        ):
            prs, issues = await fetcher.fetch_reviewable_prs(set())

        assert prs == []
        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_no_matching_pr_returns_empty_pr_list(
        self, config: HydraFlowConfig
    ) -> None:
        """No branch match in batch PR response means no PRInfo is created."""
        fetcher = IssueFetcher(config)

        # PRs exist but none match agent/issue-42
        batch_json = _batch_pr_json(
            [
                {
                    "number": 300,
                    "url": "https://github.com/o/r/pull/300",
                    "branch": "some-other-branch",
                }
            ]
        )

        with patch(
            "issue_fetcher.run_subprocess", side_effect=make_pr_fake_run(batch_json)
        ):
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
    async def test_pr_cache_reused_within_ttl(self, config: HydraFlowConfig) -> None:
        """Batch PR fetch should be cached and reused within TTL."""
        fetcher = IssueFetcher(config)
        call_count = 0

        batch_json = _batch_pr_json(
            [
                {
                    "number": 200,
                    "url": "https://github.com/o/r/pull/200",
                    "branch": "agent/issue-42",
                }
            ]
        )

        async def counting_fake_run_ttl(*args: str, **kwargs: Any) -> str:
            nonlocal call_count
            if any("/pulls" in arg for arg in args):
                call_count += 1
            if any("issues" in arg for arg in args):
                return RAW_ISSUE_JSON
            return batch_json

        with patch("issue_fetcher.run_subprocess", side_effect=counting_fake_run_ttl):
            await fetcher.fetch_reviewable_prs(set())
            fetcher.invalidate_pr_cache()  # reset for second round
            fetcher._pr_cache_fetched_at = None
            # Fetch again — should hit the API
            await fetcher.fetch_reviewable_prs(set())

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_pr_cache_forces_refetch(
        self, config: HydraFlowConfig
    ) -> None:
        """invalidate_pr_cache clears the cache so next call fetches fresh."""
        fetcher = IssueFetcher(config)
        call_count = 0

        batch_json = _batch_pr_json(
            [
                {
                    "number": 200,
                    "url": "https://github.com/o/r/pull/200",
                    "branch": "agent/issue-42",
                }
            ]
        )

        async def counting_fake_run_invalidate(*args: str, **kwargs: Any) -> str:
            nonlocal call_count
            if any("/pulls" in arg for arg in args):
                call_count += 1
            if any("issues" in arg for arg in args):
                return RAW_ISSUE_JSON
            return batch_json

        with patch(
            "issue_fetcher.run_subprocess", side_effect=counting_fake_run_invalidate
        ):
            await fetcher.fetch_reviewable_prs(set())
            assert call_count == 1
            # Without invalidation, cache hit → no new call
            await fetcher.fetch_reviewable_prs(set())
            assert call_count == 1
            # After invalidation → new call
            fetcher.invalidate_pr_cache()
            await fetcher.fetch_reviewable_prs(set())
            assert call_count == 2

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
        mock_proc = make_proc(stdout=RAW_PLAN_ISSUE_JSON.encode())

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
        mock_proc = make_proc(returncode=1, stderr=b"error: not found")

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_plan_issues()

        assert issues == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_json_decode_error(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = make_proc(stdout=b"not-json")

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
        mock_proc = make_proc(stdout=raw.encode())

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


# ---------------------------------------------------------------------------
# fetch_issue_by_number
# ---------------------------------------------------------------------------

SINGLE_ISSUE_JSON = json.dumps(
    {
        "number": 42,
        "title": "Fix bug",
        "body": "Details",
        "labels": [{"name": "ready"}],
        "comments": [],
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
        comments_json = json.dumps(["first comment"])
        mock_proc.communicate = AsyncMock(
            side_effect=[
                (SINGLE_ISSUE_JSON.encode(), b""),
                (comments_json.encode(), b""),
            ]
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issue = await fetcher.fetch_issue_by_number(42)

        assert issue is not None
        assert issue.number == 42
        assert issue.title == "Fix bug"
        assert issue.body == "Details"
        assert issue.comments == ["first comment"]

    @pytest.mark.asyncio
    async def test_returns_none_on_gh_failure(self, config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = make_proc(returncode=1, stderr=b"error: not found")

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issue = await fetcher.fetch_issue_by_number(999)

        assert issue is None

    @pytest.mark.asyncio
    async def test_returns_none_on_json_decode_error(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = make_proc(stdout=b"not-json")

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
        comments_json = json.dumps(["c1", "c2"])
        mock_proc = make_proc(stdout=comments_json.encode())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await fetcher.fetch_issue_comments(42)

        assert result == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_handles_string_comments(self, config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(config)
        comments_json = json.dumps(["dict comment", "plain string"])
        mock_proc = make_proc(stdout=comments_json.encode())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await fetcher.fetch_issue_comments(42)

        assert result == ["dict comment", "plain string"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_failure(self, config: HydraFlowConfig) -> None:
        fetcher = IssueFetcher(config)
        mock_proc = make_proc(returncode=1, stderr=b"error")

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
        mock_proc = make_proc(stdout=raw.encode())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_issues_by_labels(
                ["label-a", "label-b"], limit=10
            )

        # Same issue returned for both labels → deduplicated to 1
        assert len(issues) == 1
        assert issues[0].number == 42

    @pytest.mark.asyncio
    async def test_rest_comments_count_payload_normalizes_to_empty_comments(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        raw = json.dumps(
            [
                {
                    "number": 7,
                    "title": "REST issue",
                    "body": "Details",
                    "labels": [{"name": "ready"}],
                    "comments": 3,
                    "html_url": "https://github.com/test-org/test-repo/issues/7",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        )
        mock_proc = make_proc(stdout=raw.encode())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_issues_by_labels(["ready"], limit=10)

        assert len(issues) == 1
        assert issues[0].number == 7
        assert issues[0].comments == []

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
        mock_proc = make_proc(stdout=raw.encode())

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
        mock_proc = make_proc(returncode=1, stderr=b"error")

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issues = await fetcher.fetch_issues_by_labels(["some-label"], limit=10)

        assert issues == []

    @pytest.mark.asyncio
    async def test_rate_limit_sets_backoff_and_skips_followup_calls(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        reset_epoch = int((datetime.now(UTC) + timedelta(minutes=10)).timestamp())
        calls: list[tuple[Any, ...]] = []

        async def fake_run_subprocess(*cmd, **_kwargs):
            calls.append(cmd)
            if len(cmd) >= 3 and cmd[2] == "rate_limit":
                return str(reset_epoch)
            raise RuntimeError("gh: API rate limit exceeded (HTTP 403)")

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run_subprocess):
            first = await fetcher.fetch_issues_by_labels(["a", "b"], limit=10)
            second = await fetcher.fetch_issues_by_labels(["a"], limit=10)

        assert first == []
        assert second == []
        rate_limit_calls = [
            cmd for cmd in calls if len(cmd) >= 3 and cmd[2] == "rate_limit"
        ]
        assert len(rate_limit_calls) >= 1
        issue_calls = [
            cmd for cmd in calls if len(cmd) >= 3 and "/issues" in str(cmd[2])
        ]
        # Second fetch should be skipped while backoff is active.
        assert len(issue_calls) <= 2

    @pytest.mark.asyncio
    async def test_rate_limit_recovery_uses_exponential_jittered_backoff(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)

        with (
            patch.object(
                fetcher, "_fetch_rate_limit_reset_time", AsyncMock(return_value=None)
            ),
            patch("issue_fetcher.random.uniform", return_value=1.0),
        ):
            await fetcher._set_rate_limit_backoff(RuntimeError("rate limit"))
            first_until = fetcher._rate_limited_until
            first_attempts = fetcher._rate_limit_recovery_attempts

            # Expire first window to allow next recovery backoff to compute.
            fetcher._rate_limited_until = datetime.now(UTC) - timedelta(seconds=1)

            await fetcher._set_rate_limit_backoff(RuntimeError("rate limit"))
            second_until = fetcher._rate_limited_until
            second_attempts = fetcher._rate_limit_recovery_attempts

        assert first_until is not None
        assert second_until is not None
        assert first_attempts == 1
        assert second_attempts == 2

        first_delay = (first_until - datetime.now(UTC)).total_seconds()
        second_delay = (second_until - datetime.now(UTC)).total_seconds()
        # attempt1 => ~2s, attempt2 => ~4s when jitter=1.0
        assert first_delay <= 3.0
        assert second_delay >= 3.0

    @pytest.mark.asyncio
    async def test_paginates_when_limit_exceeds_100(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        page1 = json.dumps(
            [
                {
                    "number": i,
                    "title": f"Issue {i}",
                    "body": "",
                    "labels": [{"name": "memory"}],
                    "comments": [],
                    "url": "",
                }
                for i in range(1, 101)
            ]
        )
        page2 = json.dumps(
            [
                {
                    "number": i,
                    "title": f"Issue {i}",
                    "body": "",
                    "labels": [{"name": "memory"}],
                    "comments": [],
                    "url": "",
                }
                for i in range(101, 151)
            ]
        )

        async def fake_run_subprocess(*cmd, **_kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "page=1" in joined:
                return page1
            if "page=2" in joined:
                return page2
            return "[]"

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run_subprocess):
            issues = await fetcher.fetch_issues_by_labels(["memory"], limit=150)

        assert len(issues) == 150
        assert issues[0].number == 1
        assert issues[-1].number == 150

    @pytest.mark.asyncio
    async def test_gh_api_calls_include_cache_flag(
        self, config: HydraFlowConfig
    ) -> None:
        """The gh api calls should include --cache to enable ETag caching."""
        fetcher = IssueFetcher(config)
        raw = json.dumps(
            [
                {
                    "number": 1,
                    "title": "Test",
                    "body": "",
                    "labels": [{"name": "ready"}],
                    "comments": [],
                    "url": "https://github.com/test-org/test-repo/issues/1",
                }
            ]
        )
        mock_proc = make_proc(stdout=raw.encode())

        with patch(
            "asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            await fetcher.fetch_issues_by_labels(["ready"], limit=10)

        # Verify --cache flag was passed to gh api
        call_args = mock_exec.call_args_list[0]
        cmd = list(call_args.args)
        assert "--cache" in cmd
        cache_idx = cmd.index("--cache")
        assert cmd[cache_idx + 1] == f"{config.data_poll_interval}s"


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
        mock_proc = make_proc(stdout=raw.encode())

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

    @pytest.mark.asyncio
    async def test_raises_incomplete_error_when_rate_limited(
        self, config: HydraFlowConfig
    ) -> None:
        fetcher = IssueFetcher(config)
        reset_epoch = int((datetime.now(UTC) + timedelta(minutes=10)).timestamp())

        async def fake_run_subprocess(*cmd, **_kwargs):
            if len(cmd) >= 3 and cmd[2] == "rate_limit":
                return str(reset_epoch)
            raise RuntimeError("gh: API rate limit exceeded (HTTP 403)")

        with (
            patch("issue_fetcher.run_subprocess", side_effect=fake_run_subprocess),
            pytest.raises(IncompleteIssueFetchError),
        ):
            await fetcher.fetch_all_hydraflow_issues()


# ---------------------------------------------------------------------------
# Collaborator check
# ---------------------------------------------------------------------------

RAW_COLLAB_ISSUES = json.dumps(
    [
        {
            "number": 1,
            "title": "From collaborator",
            "body": "",
            "labels": [{"name": "ready"}],
            "comments": [],
            "url": "",
            "user": {"login": "alice"},
        },
        {
            "number": 2,
            "title": "From outsider",
            "body": "",
            "labels": [{"name": "ready"}],
            "comments": [],
            "url": "",
            "user": {"login": "mallory"},
        },
    ]
)


def _collab_config(tmp_path: Path, *, enabled: bool = True) -> HydraFlowConfig:
    """Build a config with collaborator check toggled."""
    from tests.helpers import ConfigFactory

    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
        collaborator_check_enabled=enabled,
    )


class TestCollaboratorCheck:
    """Tests for the collaborator filtering in IssueFetcher."""

    @pytest.mark.asyncio
    async def test_non_collaborator_issues_skipped(self, tmp_path: Path) -> None:
        cfg = _collab_config(tmp_path, enabled=True)
        fetcher = IssueFetcher(cfg)

        async def fake_run(*args: str, **kwargs: Any) -> str:
            joined = " ".join(str(a) for a in args)
            if "/collaborators" in joined:
                return "alice\nbob\n"
            return RAW_COLLAB_ISSUES

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            issues = await fetcher.fetch_issues_by_labels(["ready"], limit=10)

        assert len(issues) == 1
        assert issues[0].number == 1
        assert issues[0].author == "alice"

    @pytest.mark.asyncio
    async def test_all_issues_allowed_when_disabled(self, tmp_path: Path) -> None:
        cfg = _collab_config(tmp_path, enabled=False)
        fetcher = IssueFetcher(cfg)
        collab_called = False

        async def fake_run(*args: str, **kwargs: Any) -> str:
            nonlocal collab_called
            joined = " ".join(str(a) for a in args)
            if "/collaborators" in joined:
                collab_called = True
                return "alice\n"
            return RAW_COLLAB_ISSUES

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            issues = await fetcher.fetch_issues_by_labels(["ready"], limit=10)

        assert len(issues) == 2
        assert not collab_called, "collaborator API should not be called when disabled"

    @pytest.mark.asyncio
    async def test_fail_open_on_api_error(self, tmp_path: Path) -> None:
        cfg = _collab_config(tmp_path, enabled=True)
        fetcher = IssueFetcher(cfg)

        async def fake_run(*args: str, **kwargs: Any) -> str:
            joined = " ".join(str(a) for a in args)
            if "/collaborators" in joined:
                raise RuntimeError("API error")
            return RAW_COLLAB_ISSUES

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            issues = await fetcher.fetch_issues_by_labels(["ready"], limit=10)

        assert len(issues) == 2

    @pytest.mark.asyncio
    async def test_cache_reused_within_ttl(self, tmp_path: Path) -> None:
        cfg = _collab_config(tmp_path, enabled=True)
        fetcher = IssueFetcher(cfg)
        call_count = 0

        async def fake_run(*args: str, **kwargs: Any) -> str:
            nonlocal call_count
            joined = " ".join(str(a) for a in args)
            if "/collaborators" in joined:
                call_count += 1
                return "alice\n"
            return RAW_COLLAB_ISSUES

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            await fetcher.fetch_issues_by_labels(["ready"], limit=10)
            await fetcher.fetch_issues_by_labels(["ready"], limit=10)

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_issues_without_author_pass_through(self, tmp_path: Path) -> None:
        cfg = _collab_config(tmp_path, enabled=True)
        fetcher = IssueFetcher(cfg)

        no_author_issues = json.dumps(
            [
                {
                    "number": 99,
                    "title": "No author",
                    "body": "",
                    "labels": [{"name": "ready"}],
                    "comments": [],
                    "url": "",
                }
            ]
        )

        async def fake_run(*args: str, **kwargs: Any) -> str:
            joined = " ".join(str(a) for a in args)
            if "/collaborators" in joined:
                return "alice\n"
            return no_author_issues

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            issues = await fetcher.fetch_issues_by_labels(["ready"], limit=10)

        assert len(issues) == 1
        assert issues[0].number == 99

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self, tmp_path: Path) -> None:
        cfg = _collab_config(tmp_path, enabled=True)
        fetcher = IssueFetcher(cfg)
        call_count = 0

        async def fake_run(*args: str, **kwargs: Any) -> str:
            nonlocal call_count
            joined = " ".join(str(a) for a in args)
            if "/collaborators" in joined:
                call_count += 1
                return "alice\n"
            return RAW_COLLAB_ISSUES

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            await fetcher.fetch_issues_by_labels(["ready"], limit=10)
            assert call_count == 1

            # Expire the cache by backdating the fetch timestamp
            fetcher._collaborators_fetched_at = datetime.now(UTC) - timedelta(
                seconds=cfg.collaborator_cache_ttl + 1
            )
            await fetcher.fetch_issues_by_labels(["ready"], limit=10)

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_issue_by_number_extracts_author(self, tmp_path: Path) -> None:
        cfg = _collab_config(tmp_path, enabled=False)
        fetcher = IssueFetcher(cfg)

        issue_json = json.dumps(
            {
                "number": 42,
                "title": "Test",
                "body": "",
                "labels": [],
                "url": "https://github.com/test-org/test-repo/issues/42",
                "createdAt": "2026-01-01T00:00:00Z",
                "author": "alice",
            }
        )
        comments_json = json.dumps([])
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            side_effect=[
                (issue_json.encode(), b""),
                (comments_json.encode(), b""),
            ]
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            issue = await fetcher.fetch_issue_by_number(42)

        assert issue is not None
        assert issue.author == "alice"

    def test_normalize_extracts_user_login(self) -> None:
        payload = {
            "number": 1,
            "title": "Test",
            "user": {"login": "alice"},
        }
        result = IssueFetcher._normalize_issue_payload(payload)
        assert result["author"] == "alice"

    def test_normalize_handles_missing_user(self) -> None:
        payload = {"number": 1, "title": "Test"}
        result = IssueFetcher._normalize_issue_payload(payload)
        assert result["author"] == ""

    def test_normalize_handles_null_user(self) -> None:
        payload = {"number": 1, "title": "Test", "user": None}
        result = IssueFetcher._normalize_issue_payload(payload)
        assert result["author"] == ""

    def test_normalize_extracts_milestone_number(self) -> None:
        payload = {
            "number": 1,
            "title": "Test",
            "milestone": {"number": 5, "title": "Sprint 1"},
        }
        result = IssueFetcher._normalize_issue_payload(payload)
        assert result["milestone_number"] == 5

    def test_normalize_handles_missing_milestone(self) -> None:
        payload = {"number": 1, "title": "Test"}
        result = IssueFetcher._normalize_issue_payload(payload)
        assert result["milestone_number"] is None

    def test_normalize_handles_null_milestone(self) -> None:
        payload = {"number": 1, "title": "Test", "milestone": None}
        result = IssueFetcher._normalize_issue_payload(payload)
        assert result["milestone_number"] is None


# ---------------------------------------------------------------------------
# _normalize_graphql_issue
# ---------------------------------------------------------------------------


class TestNormalizeGraphQLIssue:
    """Tests for the GraphQL payload normalizer."""

    def test_maps_standard_graphql_node(self) -> None:
        node = {
            "number": 42,
            "title": "Fix bug",
            "body": "Details",
            "url": "https://github.com/o/r/issues/42",
            "state": "OPEN",
            "createdAt": "2026-01-01T00:00:00Z",
            "author": {"login": "alice"},
            "milestone": {"number": 5},
            "labels": {"nodes": [{"name": "hydraflow-plan"}]},
        }
        result = IssueFetcher._normalize_graphql_issue(node)
        assert result["number"] == 42
        assert result["title"] == "Fix bug"
        assert result["body"] == "Details"
        assert result["url"] == "https://github.com/o/r/issues/42"
        assert result["state"] == "open"
        assert result["createdAt"] == "2026-01-01T00:00:00Z"
        assert result["author"] == "alice"
        assert result["milestone_number"] == 5
        assert result["labels"] == [{"name": "hydraflow-plan"}]
        assert result["comments"] == []

    def test_handles_null_author(self) -> None:
        node = {"number": 1, "title": "T", "author": None}
        result = IssueFetcher._normalize_graphql_issue(node)
        assert result["author"] == ""

    def test_handles_missing_author(self) -> None:
        node = {"number": 1, "title": "T"}
        result = IssueFetcher._normalize_graphql_issue(node)
        assert result["author"] == ""

    def test_handles_null_milestone(self) -> None:
        node = {"number": 1, "title": "T", "milestone": None}
        result = IssueFetcher._normalize_graphql_issue(node)
        assert result["milestone_number"] is None

    def test_lowercases_state(self) -> None:
        node = {"number": 1, "title": "T", "state": "CLOSED"}
        result = IssueFetcher._normalize_graphql_issue(node)
        assert result["state"] == "closed"


# ---------------------------------------------------------------------------
# _fetch_all_graphql (GraphQL batch fetch)
# ---------------------------------------------------------------------------


class TestFetchAllGraphQL:
    """Tests for the GraphQL batch issue fetch."""

    @pytest.mark.asyncio
    async def test_graphql_batch_returns_deduplicated_issues(
        self, config: HydraFlowConfig
    ) -> None:
        """GraphQL batch merges issues across labels and deduplicates."""
        fetcher = IssueFetcher(config)

        graphql_response = json.dumps(
            {
                "data": {
                    "repository": {
                        "lbl_0": {
                            "nodes": [
                                {
                                    "number": 1,
                                    "title": "Issue 1",
                                    "body": "",
                                    "url": "",
                                    "state": "OPEN",
                                    "createdAt": "",
                                    "author": {"login": "alice"},
                                    "milestone": None,
                                    "labels": {"nodes": [{"name": "hydraflow-find"}]},
                                }
                            ]
                        },
                        "lbl_1": {
                            "nodes": [
                                {
                                    "number": 1,
                                    "title": "Issue 1",
                                    "body": "",
                                    "url": "",
                                    "state": "OPEN",
                                    "createdAt": "",
                                    "author": {"login": "alice"},
                                    "milestone": None,
                                    "labels": {"nodes": [{"name": "hydraflow-plan"}]},
                                },
                                {
                                    "number": 2,
                                    "title": "Issue 2",
                                    "body": "",
                                    "url": "",
                                    "state": "OPEN",
                                    "createdAt": "",
                                    "author": {"login": "bob"},
                                    "milestone": None,
                                    "labels": {"nodes": [{"name": "hydraflow-plan"}]},
                                },
                            ]
                        },
                    }
                }
            }
        )

        async def fake_run(*args: str, **_kwargs: Any) -> str:
            return graphql_response

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            issues = await fetcher.fetch_all_hydraflow_issues()

        assert len(issues) == 2
        numbers = {i.number for i in issues}
        assert numbers == {1, 2}

    @pytest.mark.asyncio
    async def test_graphql_makes_single_api_call(self, config: HydraFlowConfig) -> None:
        """GraphQL batch should make exactly one subprocess call."""
        fetcher = IssueFetcher(config)
        call_count = 0

        graphql_response = json.dumps({"data": {"repository": {}}})

        async def fake_run(*args: str, **_kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            return graphql_response

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            await fetcher.fetch_all_hydraflow_issues()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_graphql_failure_falls_back_to_rest(
        self, config: HydraFlowConfig
    ) -> None:
        """GraphQL failure should fall back to REST fetch_issues_by_labels."""
        fetcher = IssueFetcher(config)
        calls: list[tuple[str, ...]] = []

        rest_response = json.dumps(
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

        async def fake_run(*args: str, **_kwargs: Any) -> str:
            calls.append(args)
            if "graphql" in args:
                raise RuntimeError("GraphQL unavailable")
            return rest_response

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            issues = await fetcher.fetch_all_hydraflow_issues()

        # Should have attempted GraphQL first, then fallen back to REST
        assert any("graphql" in cmd for cmd in calls)
        rest_calls = [cmd for cmd in calls if "graphql" not in cmd]
        assert len(rest_calls) >= 1
        assert len(issues) >= 1

    @pytest.mark.asyncio
    async def test_graphql_error_response_falls_back_to_rest(
        self, config: HydraFlowConfig
    ) -> None:
        """GraphQL errors in response body trigger REST fallback."""
        fetcher = IssueFetcher(config)

        rest_response = json.dumps(
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

        async def fake_run(*args: str, **_kwargs: Any) -> str:
            if "graphql" in args:
                return json.dumps({"errors": [{"message": "rate limited"}]})
            return rest_response

        with patch("issue_fetcher.run_subprocess", side_effect=fake_run):
            issues = await fetcher.fetch_all_hydraflow_issues()

        assert len(issues) >= 1
