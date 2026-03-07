"""Tests for dx/hydraflow/pr_manager.py."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, patch

import pytest

from events import EventType
from models import ReviewVerdict
from pr_manager import PRManager
from tests.conftest import PRInfoFactory, SubprocessMockBuilder
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# _chunk_body (static method)
# ---------------------------------------------------------------------------


class TestChunkBody:
    """Tests for PRManager._chunk_body."""

    def test_short_body_returns_single_chunk(self):
        result = PRManager._chunk_body("hello world", limit=100)
        assert result == ["hello world"]

    def test_body_at_limit_returns_single_chunk(self):
        body = "x" * 100
        result = PRManager._chunk_body(body, limit=100)
        assert result == [body]

    def test_body_splits_at_newline(self):
        body = "line1\nline2\nline3"
        result = PRManager._chunk_body(body, limit=12)
        assert len(result) == 2
        assert result[0] == "line1\nline2"
        assert result[1] == "line3"

    def test_body_splits_without_newline(self):
        body = "a" * 200
        result = PRManager._chunk_body(body, limit=100)
        assert len(result) == 2
        assert result[0] == "a" * 100
        assert result[1] == "a" * 100

    def test_empty_body_returns_single_chunk(self):
        result = PRManager._chunk_body("", limit=100)
        assert result == [""]

    def test_default_limit_uses_github_comment_limit(self):
        body = "x" * (PRManager._GITHUB_COMMENT_LIMIT - 1)
        result = PRManager._chunk_body(body)
        assert result == [body]


# ---------------------------------------------------------------------------
# _cap_body (class method)
# ---------------------------------------------------------------------------


class TestCapBody:
    """Tests for PRManager._cap_body."""

    def test_short_body_unchanged(self):
        result = PRManager._cap_body("hello", limit=100)
        assert result == "hello"

    def test_default_limit_uses_github_comment_limit(self):
        body = "x" * (PRManager._GITHUB_COMMENT_LIMIT - 1)
        result = PRManager._cap_body(body)
        assert result == body

    def test_body_at_limit_unchanged(self):
        body = "x" * 100
        result = PRManager._cap_body(body, limit=100)
        assert result == body

    def test_body_over_limit_truncated_with_marker(self):
        body = "x" * 200
        result = PRManager._cap_body(body, limit=100)
        assert len(result) == 100
        assert result.endswith(PRManager._TRUNCATION_MARKER)

    def test_truncated_body_contains_original_prefix(self):
        body = "ABCDEF" * 20_000
        result = PRManager._cap_body(body, limit=1000)
        marker_len = len(PRManager._TRUNCATION_MARKER)
        assert result[: 1000 - marker_len] == body[: 1000 - marker_len]


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
# post_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_comment_calls_gh_issue_comment(event_bus, tmp_path):
    """post_comment should call gh issue comment with --body-file."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await mgr.post_comment(42, "This is a plan comment")

    mock_create.assert_awaited_once()
    call_args = mock_create.call_args
    cmd = call_args.args if call_args.args else call_args[0]
    assert "gh" in cmd
    assert "issue" in cmd
    assert "comment" in cmd
    assert "42" in cmd
    assert "--body-file" in cmd
    # Body should NOT be passed inline
    assert "This is a plan comment" not in cmd


@pytest.mark.asyncio
async def test_post_comment_dry_run(dry_config, event_bus):
    """In dry-run mode, post_comment should not call subprocess."""
    mgr = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await mgr.post_comment(42, "This is a plan comment")

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_post_comment_handles_error(event_bus, tmp_path):
    """post_comment should log warning on failure without raising."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = (
        SubprocessMockBuilder()
        .with_returncode(1)
        .with_stderr("permission denied")
        .build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        # Should not raise
        await mgr.post_comment(42, "comment body")


# ---------------------------------------------------------------------------
# post_pr_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_pr_comment_calls_gh_pr_comment(event_bus, tmp_path):
    """post_pr_comment should call gh pr comment with --body-file."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await mgr.post_pr_comment(101, "Review summary here")

    mock_create.assert_awaited_once()
    call_args = mock_create.call_args
    cmd = call_args.args if call_args.args else call_args[0]
    assert "gh" in cmd
    assert "pr" in cmd
    assert "comment" in cmd
    assert "101" in cmd
    assert "--body-file" in cmd
    assert "Review summary here" not in cmd


@pytest.mark.asyncio
async def test_post_pr_comment_dry_run(dry_config, event_bus):
    """In dry-run mode, post_pr_comment should not call subprocess."""
    mgr = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await mgr.post_pr_comment(101, "Review summary here")

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_post_pr_comment_handles_error(event_bus, tmp_path):
    """post_pr_comment should log warning on failure without raising."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = (
        SubprocessMockBuilder()
        .with_returncode(1)
        .with_stderr("permission denied")
        .build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        # Should not raise
        await mgr.post_pr_comment(101, "comment body")


# ---------------------------------------------------------------------------
# submit_review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_review_approve_calls_correct_flag(event_bus, tmp_path):
    """submit_review with 'approve' should pass --approve flag and --body-file."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.submit_review(101, ReviewVerdict.APPROVE, "Looks good")

    assert result is True
    cmd = (
        mock_create.call_args.args
        if mock_create.call_args.args
        else mock_create.call_args[0]
    )
    assert "gh" in cmd
    assert "pr" in cmd
    assert "review" in cmd
    assert "101" in cmd
    assert "--approve" in cmd
    assert "--body-file" in cmd
    assert "Looks good" not in cmd


@pytest.mark.asyncio
async def test_submit_review_request_changes_calls_correct_flag(event_bus, tmp_path):
    """submit_review with 'request-changes' should pass --request-changes."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.submit_review(
            101, ReviewVerdict.REQUEST_CHANGES, "Needs work"
        )

    assert result is True
    cmd = (
        mock_create.call_args.args
        if mock_create.call_args.args
        else mock_create.call_args[0]
    )
    assert "--request-changes" in cmd


@pytest.mark.asyncio
async def test_submit_review_comment_calls_correct_flag(event_bus, tmp_path):
    """submit_review with 'comment' should pass --comment."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.submit_review(101, ReviewVerdict.COMMENT, "FYI note")

    assert result is True
    cmd = (
        mock_create.call_args.args
        if mock_create.call_args.args
        else mock_create.call_args[0]
    )
    assert "--comment" in cmd


@pytest.mark.asyncio
async def test_submit_review_dry_run(dry_config, event_bus):
    """In dry-run mode, submit_review should not call subprocess."""
    mgr = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.submit_review(101, ReviewVerdict.APPROVE, "LGTM")

    mock_create.assert_not_called()
    assert result is True


@pytest.mark.asyncio
async def test_submit_review_failure_returns_false(event_bus, tmp_path):
    """submit_review should return False on subprocess failure."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("review failed").build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.submit_review(101, ReviewVerdict.APPROVE, "LGTM")

    assert result is False


# ---------------------------------------------------------------------------
# submit_review — SelfReviewError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_review_raises_self_review_error_on_request_changes_own_pr(
    event_bus, tmp_path
):
    """submit_review should raise SelfReviewError when request-changes hits own PR."""
    from pr_manager import SelfReviewError

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = (
        SubprocessMockBuilder()
        .with_returncode(1)
        .with_stderr(
            "GraphQL: Review Can not request changes on your own pull request (addPullRequestReview)"
        )
        .build()
    )

    with (
        patch("asyncio.create_subprocess_exec", mock_create),
        pytest.raises(SelfReviewError),
    ):
        await mgr.submit_review(101, ReviewVerdict.REQUEST_CHANGES, "Needs work")


@pytest.mark.asyncio
async def test_submit_review_raises_self_review_error_on_approve_own_pr(
    event_bus, tmp_path
):
    """submit_review should raise SelfReviewError when approve hits own PR."""
    from pr_manager import SelfReviewError

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = (
        SubprocessMockBuilder()
        .with_returncode(1)
        .with_stderr(
            "GraphQL: Cannot approve your own pull request (addPullRequestReview)"
        )
        .build()
    )

    with (
        patch("asyncio.create_subprocess_exec", mock_create),
        pytest.raises(SelfReviewError),
    ):
        await mgr.submit_review(101, ReviewVerdict.APPROVE, "LGTM")


@pytest.mark.asyncio
async def test_submit_review_returns_false_on_generic_error(event_bus, tmp_path):
    """submit_review should return False on a generic (non-self-review) error."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = (
        SubprocessMockBuilder()
        .with_returncode(1)
        .with_stderr("GraphQL: Something else went wrong")
        .build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr.submit_review(
            101, ReviewVerdict.REQUEST_CHANGES, "Needs work"
        )

    assert result is False


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_issue_calls_gh_issue_create(event_bus, tmp_path):
    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    issue_url = "https://github.com/test-org/test-repo/issues/99"
    mock_create = SubprocessMockBuilder().with_stdout(issue_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        number = await mgr.create_issue("Bug found", "Details here", ["bug"])

    assert number == 99


@pytest.mark.asyncio
async def test_create_issue_passes_correct_gh_args(config, event_bus, tmp_path):
    from config import HydraFlowConfig

    cfg = HydraFlowConfig(
        ready_label=config.ready_label,
        repo=config.repo,
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    issue_url = "https://github.com/test-org/test-repo/issues/99"
    mock_create = SubprocessMockBuilder().with_stdout(issue_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await mgr.create_issue("Bug found", "Details here", ["bug"])

    args = mock_create.call_args[0]
    assert "gh" in args
    assert "issue" in args
    assert "create" in args
    assert "--title" in args
    assert "Bug found" in args
    assert "--label" in args
    assert "bug" in args


@pytest.mark.asyncio
async def test_create_issue_publishes_event(event_bus, tmp_path):
    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    issue_url = "https://github.com/test-org/test-repo/issues/55"
    mock_create = SubprocessMockBuilder().with_stdout(issue_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await mgr.create_issue("Tech debt", "Needs refactor", ["tech-debt"])

    events = event_bus.get_history()
    from events import EventType

    issue_events = [e for e in events if e.type == EventType.ISSUE_CREATED]
    assert len(issue_events) == 1
    assert issue_events[0].data["number"] == 55
    assert issue_events[0].data["title"] == "Tech debt"


@pytest.mark.asyncio
async def test_create_issue_dry_run(dry_config, event_bus):
    mgr = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        number = await mgr.create_issue("Bug", "Details")

    mock_create.assert_not_called()
    assert number == 0


@pytest.mark.asyncio
async def test_create_issue_failure_returns_zero(event_bus, tmp_path):
    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = (
        SubprocessMockBuilder()
        .with_returncode(1)
        .with_stderr("permission denied")
        .build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        number = await mgr.create_issue("Bug", "Details")

    assert number == 0


@pytest.mark.asyncio
async def test_create_issue_no_labels(event_bus, tmp_path):
    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    issue_url = "https://github.com/test-org/test-repo/issues/10"
    mock_create = SubprocessMockBuilder().with_stdout(issue_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        number = await mgr.create_issue("Bug", "Details")

    assert number == 10
    args = mock_create.call_args[0]
    assert "--label" not in args


# ---------------------------------------------------------------------------
# upload_screenshot_gist
# ---------------------------------------------------------------------------


class TestUploadScreenshotGist:
    """Tests for PRManager.upload_screenshot_gist."""

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty_string(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            dry_run=True,
        )
        mgr = _make_manager(cfg, event_bus)
        result = await mgr.upload_screenshot_gist("aGVsbG8=")
        assert result == ""

    @pytest.mark.asyncio
    async def test_valid_base64_uploads_and_returns_raw_url(self, event_bus, tmp_path):
        import base64

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        gist_url = "https://gist.github.com/testuser/abc123"
        mock_exec = SubprocessMockBuilder().with_stdout(gist_url).build()

        png_b64 = base64.b64encode(b"\x89PNG fake data").decode()
        with patch("asyncio.create_subprocess_exec", mock_exec):
            result = await mgr.upload_screenshot_gist(png_b64)

        expected = (
            "https://gist.githubusercontent.com/testuser/abc123/raw/screenshot.png"
        )
        assert result == expected

    @pytest.mark.asyncio
    async def test_data_uri_prefix_stripped(self, event_bus, tmp_path):
        import base64

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        gist_url = "https://gist.github.com/user/def456"
        mock_exec = SubprocessMockBuilder().with_stdout(gist_url).build()

        raw_bytes = b"\x89PNG prefix test"
        png_with_prefix = (
            "data:image/png;base64," + base64.b64encode(raw_bytes).decode()
        )
        with patch("asyncio.create_subprocess_exec", mock_exec):
            result = await mgr.upload_screenshot_gist(png_with_prefix)

        assert result == (
            "https://gist.githubusercontent.com/user/def456/raw/screenshot.png"
        )

    @pytest.mark.asyncio
    async def test_failure_returns_empty_string(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_exec = SubprocessMockBuilder().with_returncode(1).build()

        with patch("asyncio.create_subprocess_exec", mock_exec):
            result = await mgr.upload_screenshot_gist("aGVsbG8=")

        assert result == ""

    @pytest.mark.asyncio
    async def test_unexpected_output_returns_empty_string(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_exec = SubprocessMockBuilder().with_stdout("unexpected output").build()

        with patch("asyncio.create_subprocess_exec", mock_exec):
            result = await mgr.upload_screenshot_gist("aGVsbG8=")

        assert result == ""

    @pytest.mark.asyncio
    async def test_default_gist_visibility_is_secret(self, event_bus, tmp_path):
        """By default (screenshot_gist_public=False), --public flag is omitted."""
        import base64

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            screenshot_gist_public=False,
        )
        mgr = _make_manager(cfg, event_bus)
        gist_url = "https://gist.github.com/testuser/abc123"
        mock_exec = SubprocessMockBuilder().with_stdout(gist_url).build()

        png_b64 = base64.b64encode(b"\x89PNG fake data").decode()
        with patch("asyncio.create_subprocess_exec", mock_exec):
            await mgr.upload_screenshot_gist(png_b64)

        args = mock_exec.call_args[0]
        assert "--public" not in args

    @pytest.mark.asyncio
    async def test_public_gist_visibility(self, event_bus, tmp_path):
        """When screenshot_gist_public=True, --public flag is included."""
        import base64

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            screenshot_gist_public=True,
        )
        mgr = _make_manager(cfg, event_bus)
        gist_url = "https://gist.github.com/testuser/abc123"
        mock_exec = SubprocessMockBuilder().with_stdout(gist_url).build()

        png_b64 = base64.b64encode(b"\x89PNG fake data").decode()
        with patch("asyncio.create_subprocess_exec", mock_exec):
            await mgr.upload_screenshot_gist(png_b64)

        args = mock_exec.call_args[0]
        assert "--public" in args

    @pytest.mark.asyncio
    async def test_binary_upload_does_not_fall_back_to_svg_gist(
        self, event_bus, tmp_path
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
        binary_error = RuntimeError(
            "Command ('gh', 'gist', 'create', ...) failed (rc=1): "
            "failed to upload file: binary file not supported"
        )
        mgr._run_gh = AsyncMock(side_effect=[binary_error])

        result = await mgr.upload_screenshot_gist(png_b64)

        assert result == ""
        assert mgr._run_gh.await_count == 1
        first_call = mgr._run_gh.await_args_list[0].args
        assert "--filename" in first_call and "screenshot.png" in first_call

    @pytest.mark.asyncio
    async def test_invalid_base64_returns_empty_string(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._run_gh = AsyncMock()

        result = await mgr.upload_screenshot_gist("!!!invalid-base64!!!")

        assert result == ""
        mgr._run_gh.assert_not_awaited()


# ---------------------------------------------------------------------------
# _gh_json_query
# ---------------------------------------------------------------------------


class TestGhJsonQuery:
    """Unit tests for the shared JSON gh helper."""

    @pytest.mark.asyncio
    async def test_successful_query_returns_parsed_payload(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._run_gh = AsyncMock(return_value='{"value": 42}')

        result = await mgr._gh_json_query(
            "gh",
            "api",
            "/test",
            dry_run_return={},
            error_log="unused",
        )

        assert result == {"value": 42}
        mgr._run_gh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dry_run_short_circuits_and_logs(self, dry_config, event_bus, caplog):
        mgr = _make_manager(dry_config, event_bus)
        mgr._run_gh = AsyncMock()

        with caplog.at_level(logging.INFO, logger="hydraflow.pr_manager"):
            result = await mgr._gh_json_query(
                "gh",
                "api",
                "/test",
                dry_run_return=[],
                dry_run_log="[dry-run] Would fetch data",
                error_log="unused",
            )

        assert result == []
        assert "[dry-run] Would fetch data" in caplog.text
        mgr._run_gh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_errors_log_warning_and_return_default(
        self, event_bus, tmp_path, caplog
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._run_gh = AsyncMock(side_effect=RuntimeError("boom"))

        with caplog.at_level(logging.WARNING, logger="hydraflow.pr_manager"):
            result = await mgr._gh_json_query(
                "gh",
                "api",
                "/test",
                dry_run_return=[],
                error_log="Failed to fetch test payload",
            )

        assert result == []
        assert "Failed to fetch test payload" in caplog.text

    @pytest.mark.asyncio
    async def test_log_exc_info_true_passes_exc_info_to_logger(
        self, event_bus, tmp_path, caplog
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._run_gh = AsyncMock(side_effect=RuntimeError("traceable error"))

        with caplog.at_level(logging.WARNING, logger="hydraflow.pr_manager"):
            result = await mgr._gh_json_query(
                "gh",
                "api",
                "/test",
                dry_run_return={},
                error_log="Fetch failed",
                log_exc_info=True,
            )

        assert result == {}
        assert "Fetch failed" in caplog.text
        # exc_info=True causes traceback to appear in log record
        assert any(r.exc_info is not None for r in caplog.records)

    @pytest.mark.asyncio
    async def test_error_level_debug_uses_debug_logger(
        self, event_bus, tmp_path, caplog
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._run_gh = AsyncMock(side_effect=RuntimeError("minor error"))

        with caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"):
            result = await mgr._gh_json_query(
                "gh",
                "api",
                "/test",
                dry_run_return=[],
                error_log="Minor fetch failure",
                error_level="debug",
            )

        assert result == []
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("Minor fetch failure" in r.message for r in debug_records)


# ---------------------------------------------------------------------------
# push_branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_branch_calls_git_push(config, event_bus, tmp_path):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await manager.push_branch(tmp_path, "agent/issue-42")

    assert result is True
    args = mock_create.call_args[0]
    assert args[0] == "git"
    assert args[1] == "push"
    assert "--no-verify" in args
    assert "-u" in args
    assert "origin" in args
    assert "agent/issue-42" in args
    assert "--force-with-lease" not in args


@pytest.mark.asyncio
async def test_push_branch_failure_returns_false(config, event_bus, tmp_path):
    manager = _make_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder()
        .with_returncode(1)
        .with_stderr("error: failed to push")
        .build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await manager.push_branch(tmp_path, "agent/issue-99")

    assert result is False


@pytest.mark.asyncio
async def test_push_branch_force_true_adds_force_with_lease(
    config, event_bus, tmp_path
):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await manager.push_branch(tmp_path, "agent/issue-42", force=True)

    assert result is True
    args = mock_create.call_args[0]
    assert "--force-with-lease" in args


@pytest.mark.asyncio
async def test_push_branch_force_true_dry_run(dry_config, event_bus, tmp_path):
    manager = _make_manager(dry_config, event_bus)
    result = await manager.push_branch(tmp_path, "agent/issue-42", force=True)
    assert result is True


# ---------------------------------------------------------------------------
# create_pr
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_pr_calls_gh_pr_create(config, event_bus, issue):
    manager = _make_manager(config, event_bus)
    pr_url = "https://github.com/test-org/test-repo/pull/55"
    mock_create = SubprocessMockBuilder().with_stdout(pr_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.create_pr(issue, "agent/issue-42")

    args = mock_create.call_args[0]
    assert args[0] == "gh"
    assert "pr" in args
    assert "create" in args


@pytest.mark.asyncio
async def test_create_pr_includes_required_flags(config, event_bus, issue):
    manager = _make_manager(config, event_bus)
    pr_url = "https://github.com/test-org/test-repo/pull/55"
    mock_create = SubprocessMockBuilder().with_stdout(pr_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.create_pr(issue, "agent/issue-42")

    args = mock_create.call_args[0]
    assert "--repo" in args
    assert config.repo in args
    assert "--head" in args
    assert "agent/issue-42" in args
    assert "--title" in args
    assert "--body-file" in args


@pytest.mark.asyncio
async def test_create_pr_parses_pr_number_from_url(config, event_bus, issue):
    manager = _make_manager(config, event_bus)
    pr_url = "https://github.com/test-org/test-repo/pull/123"
    mock_create = SubprocessMockBuilder().with_stdout(pr_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        pr_info = await manager.create_pr(issue, "agent/issue-42")

    assert pr_info.number == 123
    assert pr_info.url == pr_url
    assert pr_info.issue_number == issue.number
    assert pr_info.branch == "agent/issue-42"


@pytest.mark.asyncio
async def test_create_pr_with_draft_flag(config, event_bus, issue):
    manager = _make_manager(config, event_bus)
    pr_url = "https://github.com/test-org/test-repo/pull/77"
    mock_create = SubprocessMockBuilder().with_stdout(pr_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        pr_info = await manager.create_pr(issue, "agent/issue-42", draft=True)

    args = mock_create.call_args[0]
    assert "--draft" in args
    assert pr_info.draft is True


@pytest.mark.asyncio
async def test_create_pr_title_not_truncated_when_short(config, event_bus):
    from models import GitHubIssue

    short_issue = GitHubIssue(
        number=1,
        title="Fix it",
        body="Short issue",
        labels=["ready"],
        url="https://github.com/test-org/test-repo/issues/1",
    )
    manager = _make_manager(config, event_bus)
    pr_url = "https://github.com/test-org/test-repo/pull/10"
    mock_create = SubprocessMockBuilder().with_stdout(pr_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.create_pr(short_issue, "agent/issue-1")

    args = mock_create.call_args[0]
    title_idx = list(args).index("--title") + 1
    title = args[title_idx]
    # "Fixes #1: Fix it" is well under 70 chars
    assert len(title) <= 70
    assert "Fix it" in title
    assert not title.endswith("...")


@pytest.mark.asyncio
async def test_create_pr_title_truncated_at_70_chars(config, event_bus):
    from models import GitHubIssue

    long_title = "A" * 80
    long_issue = GitHubIssue(
        number=99,
        title=long_title,
        body="Some body text",
        labels=["ready"],
        url="https://github.com/test-org/test-repo/issues/99",
    )
    manager = _make_manager(config, event_bus)
    pr_url = "https://github.com/test-org/test-repo/pull/200"
    mock_create = SubprocessMockBuilder().with_stdout(pr_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.create_pr(long_issue, "agent/issue-99")

    args = mock_create.call_args[0]
    title_idx = list(args).index("--title") + 1
    title = args[title_idx]
    assert len(title) <= 70
    assert title.endswith("...")


@pytest.mark.asyncio
async def test_create_pr_failure_returns_pr_info_with_number_zero(
    config, event_bus, issue
):
    manager = _make_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("gh: error").build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        pr_info = await manager.create_pr(issue, "agent/issue-42")

    assert pr_info.number == 0
    assert pr_info.issue_number == issue.number
    assert pr_info.branch == "agent/issue-42"


@pytest.mark.asyncio
async def test_create_pr_failure_recovers_existing_open_pr(config, event_bus, issue):
    manager = _make_manager(config, event_bus)
    manager.find_open_pr_for_branch = AsyncMock(
        return_value=PRInfoFactory.create(
            number=222,
            issue_number=issue.number,
            branch="agent/issue-42",
            url="https://github.com/test-org/test-repo/pull/222",
        )
    )
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("gh: error").build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        pr_info = await manager.create_pr(issue, "agent/issue-42")

    assert pr_info.number == 222
    manager.find_open_pr_for_branch.assert_awaited_once_with(
        "agent/issue-42", issue_number=issue.number
    )


@pytest.mark.asyncio
async def test_branch_has_diff_from_main_false_when_not_ahead(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout('{"ahead_by":0}').build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        has_diff = await manager.branch_has_diff_from_main("agent/issue-42")

    assert has_diff is False


@pytest.mark.asyncio
async def test_branch_has_diff_from_main_true_when_ahead(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout('{"ahead_by":3}').build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        has_diff = await manager.branch_has_diff_from_main("agent/issue-42")

    assert has_diff is True


@pytest.mark.asyncio
async def test_create_pr_publishes_pr_created_event(config, event_bus, issue):
    manager = _make_manager(config, event_bus)
    pr_url = "https://github.com/test-org/test-repo/pull/55"
    mock_create = SubprocessMockBuilder().with_stdout(pr_url).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.create_pr(issue, "agent/issue-42")

    events = event_bus.get_history()
    pr_created_events = [e for e in events if e.type == EventType.PR_CREATED]
    assert len(pr_created_events) == 1
    event_data = pr_created_events[0].data
    assert event_data["pr"] == 55
    assert event_data["issue"] == issue.number
    assert event_data["branch"] == "agent/issue-42"
    assert event_data["url"] == pr_url


@pytest.mark.asyncio
async def test_create_pr_dry_run_skips_command(dry_config, event_bus, issue):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        pr_info = await manager.create_pr(issue, "agent/issue-42")

    mock_create.assert_not_called()
    assert pr_info.number == 0
    assert pr_info.issue_number == issue.number


# ---------------------------------------------------------------------------
# merge_pr
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_pr_calls_gh_pr_merge(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await manager.merge_pr(101)

    assert result is True
    args = mock_create.call_args[0]
    assert args[0] == "gh"
    assert "pr" in args
    assert "merge" in args
    assert "101" in args


@pytest.mark.asyncio
async def test_merge_pr_uses_squash_and_delete_branch(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.merge_pr(101)

    args = mock_create.call_args[0]
    assert "--squash" in args
    assert "--auto" not in args
    assert "--delete-branch" in args


@pytest.mark.asyncio
async def test_merge_pr_failure_returns_false(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("merge failed").build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await manager.merge_pr(101)

    assert result is False


@pytest.mark.asyncio
async def test_merge_pr_dry_run_skips_command(dry_config, event_bus):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await manager.merge_pr(101)

    mock_create.assert_not_called()
    assert result is True


# ---------------------------------------------------------------------------
# add_labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_labels_calls_issue_labels_api_for_each_label(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_labels(42, ["bug", "enhancement"])

    assert mock_create.call_count == 2

    first_args = mock_create.call_args_list[0][0]
    assert first_args[0] == "gh"
    assert "api" in first_args
    assert "repos/test-org/test-repo/issues/42/labels" in first_args
    assert "POST" in first_args
    assert "labels[]=bug" in first_args

    second_args = mock_create.call_args_list[1][0]
    assert "labels[]=enhancement" in second_args


@pytest.mark.asyncio
async def test_add_labels_dry_run_skips_command(dry_config, event_bus):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_labels(42, ["bug"])

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_add_labels_empty_list_skips_command(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_labels(42, [])

    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# remove_label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_label_calls_issue_labels_api(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.remove_label(42, "ready")

    assert mock_create.call_count == 1
    args = mock_create.call_args[0]
    assert args[0] == "gh"
    assert "api" in args
    assert "repos/test-org/test-repo/issues/42/labels/ready" in args
    assert "DELETE" in args


@pytest.mark.asyncio
async def test_remove_label_dry_run_skips_command(dry_config, event_bus):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.remove_label(42, "ready")

    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# add_pr_labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_pr_labels_calls_issue_labels_api_for_each_label(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_pr_labels(101, ["bug", "enhancement"])

    assert mock_create.call_count == 2

    first_args = mock_create.call_args_list[0][0]
    assert first_args[0] == "gh"
    assert "api" in first_args
    assert "repos/test-org/test-repo/issues/101/labels" in first_args
    assert "POST" in first_args
    assert "labels[]=bug" in first_args

    second_args = mock_create.call_args_list[1][0]
    assert "labels[]=enhancement" in second_args


@pytest.mark.asyncio
async def test_add_pr_labels_dry_run_skips_command(dry_config, event_bus):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_pr_labels(101, ["bug"])

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_add_pr_labels_empty_list_skips_command(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_pr_labels(101, [])

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_add_pr_labels_subprocess_error_does_not_raise(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("label error").build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        # Should not raise
        await manager.add_pr_labels(101, ["bug"])


# ---------------------------------------------------------------------------
# remove_pr_label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_pr_label_calls_issue_labels_api(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.remove_pr_label(101, "hydraflow-review")

    args = mock_create.call_args[0]
    assert "api" in args
    assert "repos/test-org/test-repo/issues/101/labels/hydraflow-review" in args
    assert "DELETE" in args


@pytest.mark.asyncio
async def test_remove_pr_label_dry_run_skips_command(dry_config, event_bus):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.remove_pr_label(101, "hydraflow-review")

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_remove_pr_label_subprocess_error_does_not_raise(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("label error").build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        # Should not raise
        await manager.remove_pr_label(101, "hydraflow-review")


# ---------------------------------------------------------------------------
# get_pr_diff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pr_diff_returns_diff_content(config, event_bus):
    manager = _make_manager(config, event_bus)
    expected_diff = "diff --git a/foo.py b/foo.py\n+added line"
    mock_create = SubprocessMockBuilder().with_stdout(expected_diff).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        diff = await manager.get_pr_diff(101)

    assert diff == expected_diff

    args = mock_create.call_args[0]
    assert args[0] == "gh"
    assert "pr" in args
    assert "diff" in args
    assert "101" in args


@pytest.mark.asyncio
async def test_get_pr_diff_failure_returns_empty_string(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("not found").build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        diff = await manager.get_pr_diff(999)

    assert diff == ""


# ---------------------------------------------------------------------------
# pull_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_main_calls_git_pull(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("Already up to date.").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await manager.pull_main()

    assert result is True
    args = mock_create.call_args[0]
    assert args[0] == "git"
    assert args[1] == "pull"
    assert "origin" in args
    assert config.main_branch in args


@pytest.mark.asyncio
async def test_pull_main_failure_returns_false(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder()
        .with_returncode(1)
        .with_stderr("fatal: pull failed")
        .build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await manager.pull_main()

    assert result is False


@pytest.mark.asyncio
async def test_pull_main_dry_run_skips_command(dry_config, event_bus):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await manager.pull_main()

    mock_create.assert_not_called()
    assert result is True


# NOTE: Tests for the subprocess helper (stdout parsing, error handling,
# GH_TOKEN injection, CLAUDECODE stripping) are now in test_subprocess_util.py
# since the logic was extracted into subprocess_util.run_subprocess.


# ---------------------------------------------------------------------------
# get_pr_checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pr_checks_returns_parsed_json(event_bus, tmp_path):
    """get_pr_checks should return parsed check results."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    checks_json = '[{"name":"ci","state":"SUCCESS"}]'
    mock_create = SubprocessMockBuilder().with_stdout(checks_json).build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        checks = await mgr.get_pr_checks(101)

    assert len(checks) == 1
    assert checks[0]["name"] == "ci"
    assert checks[0]["state"] == "SUCCESS"


@pytest.mark.asyncio
async def test_get_pr_checks_returns_empty_on_failure(event_bus, tmp_path):
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
        checks = await mgr.get_pr_checks(999)

    assert checks == []


@pytest.mark.asyncio
async def test_get_pr_checks_dry_run_returns_empty(dry_config, event_bus):
    mgr = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        checks = await mgr.get_pr_checks(101)

    mock_create.assert_not_called()
    assert checks == []


# ---------------------------------------------------------------------------
# wait_for_ci
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_ci_passes_when_all_succeed(event_bus, tmp_path):
    """wait_for_ci should return (True, ...) when all checks pass."""
    import asyncio

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    stop = asyncio.Event()

    checks = [
        {"name": "ci", "state": "SUCCESS"},
        {"name": "lint", "state": "SUCCESS"},
    ]
    mgr.get_pr_checks = AsyncMock(return_value=checks)

    passed, summary = await mgr.wait_for_ci(
        101, timeout=60, poll_interval=5, stop_event=stop
    )

    assert passed is True
    assert "2 checks passed" in summary


@pytest.mark.asyncio
async def test_wait_for_ci_fails_on_failure(event_bus, tmp_path):
    """wait_for_ci should return (False, ...) when checks fail."""
    import asyncio

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    stop = asyncio.Event()

    checks = [
        {"name": "ci", "state": "FAILURE"},
        {"name": "lint", "state": "SUCCESS"},
    ]
    mgr.get_pr_checks = AsyncMock(return_value=checks)

    passed, summary = await mgr.wait_for_ci(
        101, timeout=60, poll_interval=5, stop_event=stop
    )

    assert passed is False
    assert "ci" in summary


@pytest.mark.asyncio
async def test_wait_for_ci_passes_when_no_checks(event_bus, tmp_path):
    """wait_for_ci should return (True, ...) when no CI checks exist."""
    import asyncio

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    stop = asyncio.Event()

    mgr.get_pr_checks = AsyncMock(return_value=[])

    passed, summary = await mgr.wait_for_ci(
        101, timeout=60, poll_interval=5, stop_event=stop
    )

    assert passed is True
    assert "No CI checks found" in summary


@pytest.mark.asyncio
async def test_wait_for_ci_respects_stop_event(event_bus, tmp_path):
    """wait_for_ci should return (False, 'Stopped') when stop_event is set."""
    import asyncio

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    stop = asyncio.Event()
    stop.set()  # Already stopped

    passed, summary = await mgr.wait_for_ci(
        101, timeout=60, poll_interval=5, stop_event=stop
    )

    assert passed is False
    assert summary == "Stopped"


@pytest.mark.asyncio
async def test_wait_for_ci_dry_run_returns_success(dry_config, event_bus):
    """In dry-run mode, wait_for_ci should return (True, ...)."""
    import asyncio

    mgr = _make_manager(dry_config, event_bus)
    stop = asyncio.Event()

    passed, summary = await mgr.wait_for_ci(
        101, timeout=60, poll_interval=5, stop_event=stop
    )

    assert passed is True
    assert "Dry-run" in summary


@pytest.mark.asyncio
async def test_wait_for_ci_already_complete_returns_immediately(event_bus, tmp_path):
    """When checks are already complete, should return without sleeping."""
    import asyncio

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    stop = asyncio.Event()

    checks = [{"name": "ci", "state": "SUCCESS"}]
    mgr.get_pr_checks = AsyncMock(return_value=checks)

    passed, _ = await mgr.wait_for_ci(101, timeout=60, poll_interval=5, stop_event=stop)

    assert passed is True
    mgr.get_pr_checks.assert_awaited_once()


@pytest.mark.asyncio
async def test_wait_for_ci_publishes_ci_check_events(event_bus, tmp_path):
    """wait_for_ci should publish CI_CHECK events."""
    import asyncio

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    stop = asyncio.Event()

    checks = [{"name": "ci", "state": "SUCCESS"}]
    mgr.get_pr_checks = AsyncMock(return_value=checks)

    await mgr.wait_for_ci(101, timeout=60, poll_interval=5, stop_event=stop)

    events = event_bus.get_history()
    ci_events = [e for e in events if e.type == EventType.CI_CHECK]
    assert len(ci_events) >= 1
    assert ci_events[0].data["pr"] == 101
    assert ci_events[0].data["status"] == "passed"


# ---------------------------------------------------------------------------
# _sum_label_counts
# ---------------------------------------------------------------------------


class TestSumLabelCounts:
    """Unit tests for the _sum_label_counts helper."""

    @pytest.mark.asyncio
    async def test_sums_counts_for_each_label(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(side_effect=[3, 7])

        result = await mgr._sum_label_counts(
            ["label-a", "label-b"],
            query_builder=lambda label: f"repo:org/repo label:{label}",
            log_context="count test labels",
        )

        assert result == 10
        assert mgr._search_github_count.await_count == 2

    @pytest.mark.asyncio
    async def test_skips_failed_label_and_continues(
        self, event_bus, tmp_path, caplog
    ):
        """Errors from _search_github_count should be swallowed and logged at debug."""
        import logging

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(
            side_effect=[RuntimeError("API rate limit"), 5]
        )

        with caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"):
            result = await mgr._sum_label_counts(
                ["label-a", "label-b"],
                query_builder=lambda label: f"repo:org/repo label:{label}",
                log_context="count test labels",
            )

        assert result == 5
        assert "count test labels" in caplog.text

    @pytest.mark.asyncio
    async def test_returns_zero_when_all_fail(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock(
            side_effect=RuntimeError("network error")
        )

        result = await mgr._sum_label_counts(
            ["label-a", "label-b"],
            query_builder=lambda label: f"repo:org/repo label:{label}",
            log_context="count test labels",
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_and_makes_no_calls_for_empty_label_list(
        self, event_bus, tmp_path
    ):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mgr._search_github_count = AsyncMock()

        result = await mgr._sum_label_counts(
            [],
            query_builder=lambda label: f"repo:org/repo label:{label}",
            log_context="count empty labels",
        )

        assert result == 0
        mgr._search_github_count.assert_not_awaited()


# ---------------------------------------------------------------------------
# ensure_labels_exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_labels_exist_creates_all_hydraflow_labels(event_bus, tmp_path):
    """ensure_labels_exist should call gh label create --force for each label."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)

    async def side_effect(*args, **_kwargs):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock(return_value=0)
        if args[1] == "label" and args[2] == "list":
            mock_proc.communicate = AsyncMock(return_value=(b"[]", b""))
        else:
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        return mock_proc

    mock_create = AsyncMock(side_effect=side_effect)

    with patch("asyncio.create_subprocess_exec", mock_create):
        await mgr.ensure_labels_exist()

    # 1 list call + 1 create per label
    assert mock_create.call_count == 1 + len(PRManager._HYDRAFLOW_LABELS)

    # Verify create calls use gh label create --force
    create_calls = [c for c in mock_create.call_args_list if "create" in c[0]]
    assert len(create_calls) == len(PRManager._HYDRAFLOW_LABELS)
    for call in create_calls:
        args = call[0]
        assert args[0] == "gh"
        assert "--force" in args
        assert "--color" in args
        assert "--description" in args


@pytest.mark.asyncio
async def test_ensure_labels_exist_uses_config_label_names(config, event_bus, tmp_path):
    """ensure_labels_exist should use label names from config (not hardcoded defaults)."""

    cfg = ConfigFactory.create(
        find_label=["custom-find"],
        ready_label=["custom-ready"],
        planner_label=["custom-plan"],
        review_label=["custom-review"],
        hitl_label=["custom-hitl"],
        hitl_active_label=["custom-hitl-active"],
        fixed_label=["custom-fixed"],
        improve_label=["custom-improve"],
        memory_label=["custom-memory"],
        transcript_label=["custom-transcript"],
        manifest_label=["custom-manifest"],
        metrics_label=["custom-metrics"],
        dup_label=["custom-dup"],
        epic_label=["custom-epic"],
        epic_child_label=["custom-epic-child"],
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)

    async def side_effect(*args, **_kwargs):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock(return_value=0)
        if args[1] == "label" and args[2] == "list":
            mock_proc.communicate = AsyncMock(return_value=(b"[]", b""))
        else:
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        return mock_proc

    mock_create = AsyncMock(side_effect=side_effect)

    with patch("asyncio.create_subprocess_exec", mock_create):
        await mgr.ensure_labels_exist()

    # Collect all label names passed to gh label create
    created_labels = set()
    for call in mock_create.call_args_list:
        args = call[0]
        if "create" not in args:
            continue
        # Label name is the arg after "create"
        create_idx = list(args).index("create")
        created_labels.add(args[create_idx + 1])

    assert created_labels == {
        "custom-find",
        "custom-plan",
        "custom-ready",
        "custom-review",
        "custom-hitl",
        "custom-hitl-active",
        "custom-fixed",
        "custom-improve",
        "custom-memory",
        "custom-transcript",
        "custom-manifest",
        "custom-metrics",
        "custom-dup",
        "custom-epic",
        "custom-epic-child",
    }


@pytest.mark.asyncio
async def test_ensure_labels_exist_dry_run_skips(dry_config, event_bus):
    """In dry-run mode, ensure_labels_exist should not call subprocess."""
    mgr = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await mgr.ensure_labels_exist()

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_labels_exist_handles_individual_failures(event_bus, tmp_path):
    """If one label creation fails, others should still be attempted."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)

    create_count = 0

    async def side_effect(*args, **_kwargs):
        nonlocal create_count
        mock_proc = AsyncMock()
        if args[1] == "label" and args[2] == "list":
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"[]", b""))
        elif args[1] == "label" and args[2] == "create":
            create_count += 1
            if create_count == 1:
                mock_proc.returncode = 1
                mock_proc.communicate = AsyncMock(
                    return_value=(b"", b"permission denied")
                )
            else:
                mock_proc.returncode = 0
                mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.wait = AsyncMock(return_value=mock_proc.returncode)
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
        # Should not raise
        await mgr.ensure_labels_exist()

    # All labels should be attempted even though first one failed
    assert create_count == len(PRManager._HYDRAFLOW_LABELS)


def test_makefile_ensure_labels_runs_cli_prep() -> None:
    """Makefile ensure-labels target should call ``cli.py --ensure-labels`` directly."""
    from pathlib import Path

    makefile = Path(__file__).resolve().parent.parent / "Makefile"
    content = makefile.read_text()

    import re

    match = re.search(r"^ensure-labels:[^\n]*\n((?:\t.*\n)+)", content, re.MULTILINE)
    assert match is not None, "ensure-labels target block not found in Makefile"
    assert "--ensure-labels" in match.group(1), (
        "ensure-labels target must call cli.py --ensure-labels"
    )


def test_makefile_prep_runs_cli_scaffold() -> None:
    """Makefile prep target should call ``cli.py --prep``."""
    from pathlib import Path

    makefile = Path(__file__).resolve().parent.parent / "Makefile"
    content = makefile.read_text()

    import re

    match = re.search(r"^prep:[^\n]*\n((?:\t.*\n)+)", content, re.MULTILINE)
    assert match is not None, "prep target block not found in Makefile"
    assert "$(MAKE) setup" in match.group(1), (
        "prep target must run setup first to bootstrap agent assets"
    )
    assert "--prep" in match.group(1), "prep target must call cli.py --prep"


def test_makefile_setup_runs_label_bootstrap() -> None:
    """Makefile setup target should run ``cli.py --ensure-labels`` to ensure labels."""
    from pathlib import Path

    makefile = Path(__file__).resolve().parent.parent / "Makefile"
    content = makefile.read_text()

    import re

    match = re.search(r"^setup:[^\n]*\n((?:\t.*\n)+)", content, re.MULTILINE)
    assert match is not None, "setup target block not found in Makefile"
    assert "--ensure-labels" in match.group(1), (
        "setup target must ensure labels via cli.py --ensure-labels"
    )
    assert "python -m hf_cli init --target" in match.group(1), (
        "setup target must bootstrap .claude/.codex/.pi/.githooks via hf init"
    )
    assert ".hydraflow-managed" in match.group(1), (
        "setup target should mark managed Codex skills to enable safe stale-skill pruning"
    )


def test_makefile_setup_bootstraps_env_from_sample() -> None:
    """make setup should create .env from .env.sample when .env is missing."""
    from pathlib import Path

    makefile = Path(__file__).resolve().parent.parent / "Makefile"
    content = makefile.read_text()

    assert ".env.sample" in content, "setup target must reference .env.sample"
    assert 'cp "$(PROJECT_ROOT)/.env.sample" "$(PROJECT_ROOT)/.env"' in content


def test_makefile_setup_ignores_prep_scratch_dir() -> None:
    """make setup should ensure .hydraflow/prep is ignored in the target repo."""
    from pathlib import Path

    makefile = Path(__file__).resolve().parent.parent / "Makefile"
    content = makefile.read_text()

    assert '.gitignore"' in content, "setup target must touch/update .gitignore"
    assert "\\.hydraflow/prep" in content, (
        "setup target must add .hydraflow/prep to .gitignore"
    )


# ---------------------------------------------------------------------------
# _run_with_body_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_body_file_writes_temp_file(event_bus, tmp_path):
    """_run_with_body_file should write body to a temp .md file and pass --body-file."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("ok").build()
    body_content = None

    original_mock = mock_create

    async def capture_body_file(*args, **kwargs):
        nonlocal body_content
        cmd = args
        for i, arg in enumerate(cmd):
            if arg == "--body-file" and i + 1 < len(cmd):
                body_content = Path(cmd[i + 1]).read_text()
                break
        return await original_mock(*args, **kwargs)

    with patch("asyncio.create_subprocess_exec", side_effect=capture_body_file):
        await mgr._run_with_body_file(
            "gh", "issue", "comment", "1", body="Large plan content", cwd=tmp_path
        )

    assert body_content == "Large plan content"


@pytest.mark.asyncio
async def test_run_with_body_file_cleans_up_temp_file(event_bus, tmp_path):
    """_run_with_body_file should delete the temp file after completion."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("ok").build()
    temp_file_path = None

    original_mock = mock_create

    async def capture_path(*args, **kwargs):
        nonlocal temp_file_path
        cmd = args
        for i, arg in enumerate(cmd):
            if arg == "--body-file" and i + 1 < len(cmd):
                temp_file_path = cmd[i + 1]
                break
        return await original_mock(*args, **kwargs)

    with patch("asyncio.create_subprocess_exec", side_effect=capture_path):
        await mgr._run_with_body_file(
            "gh", "issue", "comment", "1", body="content", cwd=tmp_path
        )

    assert temp_file_path is not None
    assert not Path(temp_file_path).exists(), "Temp file should be cleaned up"


@pytest.mark.asyncio
async def test_run_with_body_file_cleans_up_on_error(event_bus, tmp_path):
    """_run_with_body_file should delete the temp file even on failure."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = SubprocessMockBuilder().with_returncode(1).with_stderr("fail").build()
    temp_file_path = None

    original_mock = mock_create

    async def capture_path(*args, **kwargs):
        nonlocal temp_file_path
        cmd = args
        for i, arg in enumerate(cmd):
            if arg == "--body-file" and i + 1 < len(cmd):
                temp_file_path = cmd[i + 1]
                break
        return await original_mock(*args, **kwargs)

    with (
        patch("asyncio.create_subprocess_exec", side_effect=capture_path),
        pytest.raises(RuntimeError),
    ):
        await mgr._run_with_body_file(
            "gh", "issue", "comment", "1", body="content", cwd=tmp_path
        )

    assert temp_file_path is not None
    assert not Path(temp_file_path).exists(), "Temp file should be cleaned up on error"


# ---------------------------------------------------------------------------
# post_comment chunking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_comment_chunks_large_body(event_bus, tmp_path):
    """post_comment should split oversized bodies into multiple comments."""

    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    mgr = _make_manager(cfg, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    # Body larger than the GitHub comment limit
    large_body = "x" * (PRManager._GITHUB_COMMENT_LIMIT + 1000)

    with patch("asyncio.create_subprocess_exec", mock_create):
        await mgr.post_comment(42, large_body)

    # Should have been split into 2 comments
    assert mock_create.call_count == 2


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
# Edge case tests for create_pr, wait_for_ci, list_open_prs
# ---------------------------------------------------------------------------


class TestCreatePrEdgeCases:
    """Edge case tests for PRManager.create_pr."""

    @pytest.mark.asyncio
    async def test_create_pr_unparseable_url_returns_zero_pr(
        self, config, event_bus, issue
    ) -> None:
        """create_pr should return PRInfo(number=0) when gh output is not a parseable URL."""
        manager = _make_manager(config, event_bus)
        # gh pr create returns non-URL text (unparseable)
        mock_create = (
            SubprocessMockBuilder()
            .with_stdout("Created pull request successfully")
            .build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.create_pr(issue, "agent/issue-42")

        assert result.number == 0
        assert result.issue_number == issue.number
        assert result.branch == "agent/issue-42"

    @pytest.mark.asyncio
    async def test_create_pr_empty_output_returns_zero_pr(
        self, config, event_bus, issue
    ) -> None:
        """create_pr should return PRInfo(number=0) when gh output is empty."""
        manager = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.create_pr(issue, "agent/issue-42")

        assert result.number == 0
        assert result.issue_number == issue.number
        assert result.branch == "agent/issue-42"


class TestCreateIssueEdgeCases:
    """Edge case tests for PRManager.create_issue."""

    @pytest.mark.asyncio
    async def test_create_issue_malformed_output_returns_zero(
        self, config, event_bus
    ) -> None:
        """create_issue should return 0 when gh output is not a valid URL."""
        mgr = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_stdout("Error: something went wrong").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.create_issue("Bug found", "Details here", ["bug"])

        assert result == 0

    @pytest.mark.asyncio
    async def test_create_issue_empty_output_returns_zero(
        self, config, event_bus
    ) -> None:
        """create_issue should return 0 when gh output is empty."""
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.create_issue("Bug found", "Details here", ["bug"])

        assert result == 0


class TestWaitForCiEdgeCases:
    """Edge case tests for PRManager.wait_for_ci."""

    @pytest.mark.asyncio
    async def test_wait_for_ci_partial_completion_keeps_polling(
        self, config, event_bus
    ) -> None:
        """When some checks pass and some are pending, should poll again."""
        mgr = _make_manager(config, event_bus)
        stop = asyncio.Event()

        # First call: mix of SUCCESS and PENDING; second call: all SUCCESS
        call_count = 0

        async def fake_checks(_pr_num: int) -> list[dict[str, str]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    {"name": "ci", "state": "SUCCESS"},
                    {"name": "lint", "state": "PENDING"},
                ]
            return [
                {"name": "ci", "state": "SUCCESS"},
                {"name": "lint", "state": "SUCCESS"},
            ]

        mgr.get_pr_checks = fake_checks  # type: ignore[assignment]

        passed, summary = await mgr.wait_for_ci(
            101, timeout=60, poll_interval=0, stop_event=stop
        )

        assert passed is True
        assert summary == "All 2 checks passed"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_wait_for_ci_cancelled_check_treated_as_failure(
        self, config, event_bus
    ) -> None:
        """CANCELLED check state should be treated as failure (not in _PASSING_STATES)."""
        mgr = _make_manager(config, event_bus)
        stop = asyncio.Event()

        checks = [
            {"name": "ci", "state": "SUCCESS"},
            {"name": "deploy", "state": "CANCELLED"},
        ]
        mgr.get_pr_checks = AsyncMock(return_value=checks)

        passed, summary = await mgr.wait_for_ci(
            101, timeout=60, poll_interval=5, stop_event=stop
        )

        assert passed is False
        assert "deploy" in summary


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
# Private helper: _comment
# ---------------------------------------------------------------------------


class TestCommentHelper:
    """Tests for the unified _comment() helper."""

    @pytest.mark.asyncio
    async def test_comment_issue_target(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._comment("issue", 42, "test body")

        cmd = mock_create.call_args[0]
        assert "issue" in cmd
        assert "comment" in cmd
        assert "42" in cmd

    @pytest.mark.asyncio
    async def test_comment_pr_target(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._comment("pr", 101, "test body")

        cmd = mock_create.call_args[0]
        assert "pr" in cmd
        assert "comment" in cmd
        assert "101" in cmd

    @pytest.mark.asyncio
    async def test_comment_dry_run(self, dry_config, event_bus):
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._comment("issue", 42, "body")

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_comment_error_does_not_raise(self, event_bus, tmp_path):
        """_comment should log a warning on failure without propagating the error."""

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = (
            SubprocessMockBuilder()
            .with_returncode(1)
            .with_stderr("permission denied")
            .build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            # Should not raise even on subprocess failure
            await mgr._comment("pr", 99, "body")


# ---------------------------------------------------------------------------
# Private helper: _add_labels
# ---------------------------------------------------------------------------


class TestAddLabelsHelper:
    """Tests for the unified _add_labels() helper."""

    @pytest.mark.asyncio
    async def test_add_labels_issue_target(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._add_labels("issue", 42, ["bug"])

        cmd = mock_create.call_args[0]
        assert "api" in cmd
        assert "repos/test-org/test-repo/issues/42/labels" in cmd
        assert "POST" in cmd
        assert "labels[]=bug" in cmd

    @pytest.mark.asyncio
    async def test_add_labels_pr_target(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._add_labels("pr", 101, ["enhancement"])

        cmd = mock_create.call_args[0]
        assert "api" in cmd
        assert "repos/test-org/test-repo/issues/101/labels" in cmd
        assert "POST" in cmd
        assert "labels[]=enhancement" in cmd

    @pytest.mark.asyncio
    async def test_add_labels_dry_run(self, dry_config, event_bus):
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._add_labels("issue", 42, ["bug"])

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_labels_empty_list(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._add_labels("pr", 101, [])

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_labels_error_does_not_raise(self, config, event_bus):
        """_add_labels should log a warning on failure without propagating the error."""
        mgr = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder()
            .with_returncode(1)
            .with_stderr("label not found")
            .build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            # Should not raise even on subprocess failure
            await mgr._add_labels("issue", 42, ["missing-label"])


# ---------------------------------------------------------------------------
# Private helper: _remove_label
# ---------------------------------------------------------------------------


class TestRemoveLabelHelper:
    """Tests for the unified _remove_label() helper."""

    @pytest.mark.asyncio
    async def test_remove_label_issue_target(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._remove_label("issue", 42, "ready")

        cmd = mock_create.call_args[0]
        assert "api" in cmd
        assert "repos/test-org/test-repo/issues/42/labels/ready" in cmd
        assert "DELETE" in cmd

    @pytest.mark.asyncio
    async def test_remove_label_pr_target(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._remove_label("pr", 101, "hydraflow-review")

        cmd = mock_create.call_args[0]
        assert "api" in cmd
        assert "repos/test-org/test-repo/issues/101/labels/hydraflow-review" in cmd
        assert "DELETE" in cmd

    @pytest.mark.asyncio
    async def test_remove_label_dry_run(self, dry_config, event_bus):
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._remove_label("pr", 101, "label")

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_label_error_does_not_raise(self, config, event_bus):
        """_remove_label should log a warning on failure without propagating the error."""
        mgr = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder()
            .with_returncode(1)
            .with_stderr("label not found")
            .build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            # Should not raise even on subprocess failure
            await mgr._remove_label("issue", 42, "missing-label")

    @pytest.mark.asyncio
    async def test_remove_label_missing_label_404_is_noop(
        self, config, event_bus, caplog
    ):
        """Missing-label 404 should be treated as expected no-op (not warning)."""
        mgr = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder()
            .with_returncode(1)
            .with_stderr("gh: Label does not exist (HTTP 404)")
            .build()
        )

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"),
        ):
            await mgr._remove_label("issue", 42, "missing-label")

        assert "Could not remove label" not in caplog.text
        assert "skipping remove" in caplog.text


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



# ---------------------------------------------------------------------------
# close_issue
# ---------------------------------------------------------------------------


class TestCloseIssue:
    """Tests for PRManager.close_issue."""

    @pytest.mark.asyncio
    async def test_close_issue_calls_gh_issue_close(self, config, event_bus):
        manager = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await manager.close_issue(42)

        assert mock_create.call_count == 1
        args = mock_create.call_args[0]
        assert args[0] == "gh"
        assert "issue" in args
        assert "close" in args
        assert "42" in args
        assert "--repo" in args
        assert config.repo in args

    @pytest.mark.asyncio
    async def test_close_issue_dry_run_skips_command(self, dry_config, event_bus):
        manager = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await manager.close_issue(42)

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_issue_handles_error_gracefully(self, config, event_bus):
        manager = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("not found").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            # Should not raise
            await manager.close_issue(999)


# ---------------------------------------------------------------------------
# get_pr_diff_names
# ---------------------------------------------------------------------------


class TestGetPrDiffNames:
    """Tests for PRManager.get_pr_diff_names."""

    @pytest.mark.asyncio
    async def test_get_pr_diff_names_returns_file_list(self, config, event_bus):
        manager = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("foo.py\nbar.py\n").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.get_pr_diff_names(101)

        assert result == ["foo.py", "bar.py"]
        args = mock_create.call_args[0]
        assert args[0] == "gh"
        assert "pr" in args
        assert "diff" in args
        assert "101" in args
        assert "--name-only" in args

    @pytest.mark.asyncio
    async def test_get_pr_diff_names_returns_empty_on_failure(self, config, event_bus):
        manager = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("not found").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.get_pr_diff_names(999)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_pr_diff_names_empty_diff_returns_empty_list(
        self, config, event_bus
    ):
        manager = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.get_pr_diff_names(101)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_pr_diff_names_strips_whitespace(self, config, event_bus):
        manager = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_stdout("  foo.py  \n\n  bar.py \n  \n").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.get_pr_diff_names(101)

        assert result == ["foo.py", "bar.py"]


# ---------------------------------------------------------------------------
# fetch_ci_failure_logs
# ---------------------------------------------------------------------------


class TestFetchCiFailureLogs:
    """Tests for PRManager.fetch_ci_failure_logs."""

    @pytest.mark.asyncio
    async def test_returns_empty_in_dry_run(self, dry_config, event_bus):
        """Dry-run mode returns empty string."""
        manager = _make_manager(dry_config, event_bus)
        result = await manager.fetch_ci_failure_logs(101)
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_failed_checks(self, config, event_bus):
        """All passing checks returns empty string."""
        manager = _make_manager(config, event_bus)
        checks_json = json.dumps(
            [
                {"name": "Build", "state": "SUCCESS", "detailsUrl": ""},
                {"name": "Lint", "state": "SUCCESS", "detailsUrl": ""},
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(checks_json).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.fetch_ci_failure_logs(101)

        assert result == ""

    @pytest.mark.asyncio
    async def test_fetches_log_for_failed_check(self, config, event_bus):
        """Fetches log output for a failed check with a valid detailsUrl."""
        manager = _make_manager(config, event_bus)
        checks_json = json.dumps(
            [
                {
                    "name": "Build & Test",
                    "state": "FAILURE",
                    "detailsUrl": "https://github.com/org/repo/actions/runs/12345/job/67890",
                },
            ]
        )

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = AsyncMock()
            mock_proc.wait = AsyncMock(return_value=0)
            mock_proc.returncode = 0
            if call_count == 1:
                # First call: gh pr checks
                stdout = checks_json.encode()
            else:
                # Second call: gh run view --log-failed
                stdout = (
                    b"Error in test_foo.py line 42\nAssertionError: expected 1 got 2\n"
                )
            mock_proc.communicate = AsyncMock(return_value=(stdout, b""))
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await manager.fetch_ci_failure_logs(101)

        assert "Build & Test" in result
        assert "12345" in result

    @pytest.mark.asyncio
    async def test_handles_missing_details_url(self, config, event_bus):
        """Check without detailsUrl is skipped gracefully."""
        manager = _make_manager(config, event_bus)
        checks_json = json.dumps(
            [
                {"name": "External", "state": "FAILURE", "detailsUrl": ""},
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(checks_json).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.fetch_ci_failure_logs(101)

        assert result == ""

    @pytest.mark.asyncio
    async def test_handles_gh_error_gracefully(self, config, event_bus):
        """RuntimeError from gh returns empty string."""
        manager = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("not found").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.fetch_ci_failure_logs(101)

        assert result == ""

    @pytest.mark.asyncio
    async def test_deduplicates_run_ids(self, config, event_bus):
        """Multiple failed checks sharing a run ID result in one gh run view call."""
        manager = _make_manager(config, event_bus)
        # Two checks with different job URLs but the same run ID (12345)
        checks_json = json.dumps(
            [
                {
                    "name": "Test (py3.11)",
                    "state": "FAILURE",
                    "detailsUrl": "https://github.com/org/repo/actions/runs/12345/job/111",
                },
                {
                    "name": "Test (py3.12)",
                    "state": "FAILURE",
                    "detailsUrl": "https://github.com/org/repo/actions/runs/12345/job/222",
                },
            ]
        )

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = AsyncMock()
            mock_proc.wait = AsyncMock(return_value=0)
            mock_proc.returncode = 0
            if call_count == 1:
                stdout = checks_json.encode()
            else:
                stdout = b"failure log output\n"
            mock_proc.communicate = AsyncMock(return_value=(stdout, b""))
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await manager.fetch_ci_failure_logs(101)

        # Only one gh run view call despite two failed checks sharing the run ID
        assert call_count == 2  # 1 for gh pr checks + 1 for gh run view
        assert "12345" in result

    @pytest.mark.asyncio
    async def test_skips_check_with_non_matching_details_url(self, config, event_bus):
        """A failed check whose detailsUrl has no run ID is skipped."""
        manager = _make_manager(config, event_bus)
        checks_json = json.dumps(
            [
                {
                    "name": "External",
                    "state": "FAILURE",
                    "detailsUrl": "https://external-ci.example.com/builds/42",
                },
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(checks_json).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.fetch_ci_failure_logs(101)

        assert result == ""

    @pytest.mark.asyncio
    async def test_skips_run_with_empty_log_output(self, config, event_bus):
        """A run whose log output is empty or whitespace-only is not included."""
        manager = _make_manager(config, event_bus)
        checks_json = json.dumps(
            [
                {
                    "name": "Build",
                    "state": "FAILURE",
                    "detailsUrl": "https://github.com/org/repo/actions/runs/99999/job/1",
                },
            ]
        )

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = AsyncMock()
            mock_proc.wait = AsyncMock(return_value=0)
            mock_proc.returncode = 0
            stdout = checks_json.encode() if call_count == 1 else b"   \n  \n"
            mock_proc.communicate = AsyncMock(return_value=(stdout, b""))
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await manager.fetch_ci_failure_logs(101)

        assert result == ""


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
# TaskTransitioner protocol compliance
# ---------------------------------------------------------------------------


class TestTaskTransitionerProtocol:
    """PRManager satisfies the TaskTransitioner protocol."""

    def _make_mgr(self):
        from unittest.mock import MagicMock

        from pr_manager import PRManager
        from tests.helpers import ConfigFactory

        return PRManager(ConfigFactory.create(), event_bus=MagicMock())

    def test_pr_manager_is_task_transitioner(self) -> None:
        """PRManager should be recognised as TaskTransitioner at runtime."""
        from task_source import TaskTransitioner

        assert isinstance(self._make_mgr(), TaskTransitioner)

    def test_pr_manager_has_transition_method(self) -> None:
        mgr = self._make_mgr()
        assert hasattr(mgr, "transition")
        assert callable(mgr.transition)

    def test_pr_manager_has_close_task_method(self) -> None:
        mgr = self._make_mgr()
        assert hasattr(mgr, "close_task")
        assert callable(mgr.close_task)

    def test_pr_manager_has_create_task_method(self) -> None:
        mgr = self._make_mgr()
        assert hasattr(mgr, "create_task")
        assert callable(mgr.create_task)


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


# --- swap_pipeline_labels ---


class TestSwapPipelineLabels:
    """Tests for PRManager.swap_pipeline_labels."""

    @pytest.mark.asyncio
    async def test_removes_all_other_pipeline_labels_from_issue(
        self, config, event_bus
    ) -> None:
        mgr = _make_manager(config, event_bus)
        mgr._remove_label = AsyncMock()
        mgr._add_labels = AsyncMock()

        await mgr.swap_pipeline_labels(42, config.ready_label[0])

        # All pipeline labels except the target should be removed
        removed = [call.args[2] for call in mgr._remove_label.call_args_list]
        assert config.ready_label[0] not in removed
        # At least some labels should be removed
        assert len(removed) > 0

    @pytest.mark.asyncio
    async def test_adds_new_label_to_issue(self, config, event_bus) -> None:
        mgr = _make_manager(config, event_bus)
        mgr._remove_label = AsyncMock()
        mgr._add_labels = AsyncMock()

        await mgr.swap_pipeline_labels(42, "hydraflow-review")

        mgr._add_labels.assert_any_call("issue", 42, ["hydraflow-review"])

    @pytest.mark.asyncio
    async def test_also_removes_from_pr_when_pr_number_given(
        self, config, event_bus
    ) -> None:
        mgr = _make_manager(config, event_bus)
        mgr._remove_label = AsyncMock()
        mgr._add_labels = AsyncMock()

        await mgr.swap_pipeline_labels(42, "hydraflow-review", pr_number=101)

        # Should have remove calls for both issue and pr
        targets = [call.args[0] for call in mgr._remove_label.call_args_list]
        assert "issue" in targets
        assert "pr" in targets
        # Should add to both issue and pr
        mgr._add_labels.assert_any_call("issue", 42, ["hydraflow-review"])
        mgr._add_labels.assert_any_call("pr", 101, ["hydraflow-review"])

    @pytest.mark.asyncio
    async def test_no_pr_label_ops_when_pr_number_none(self, config, event_bus) -> None:
        mgr = _make_manager(config, event_bus)
        mgr._remove_label = AsyncMock()
        mgr._add_labels = AsyncMock()

        await mgr.swap_pipeline_labels(42, "hydraflow-review")

        targets = [call.args[0] for call in mgr._remove_label.call_args_list]
        assert "pr" not in targets
        # Only one add_labels call (for issue)
        assert mgr._add_labels.call_count == 1


# --- update_issue_body ---


class TestUpdateIssueBody:
    """Tests for PRManager.update_issue_body."""

    @pytest.mark.asyncio
    async def test_calls_gh_issue_edit_with_body_file(self, config, event_bus) -> None:
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr.update_issue_body(42, "New body content")

        mock_create.assert_called_once()
        cmd = mock_create.call_args[0]
        assert "issue" in cmd
        assert "edit" in cmd
        assert "--body-file" in cmd

    @pytest.mark.asyncio
    async def test_cleans_up_temp_file(self, config, event_bus) -> None:
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr.update_issue_body(42, "body")

        # The temp file should have been cleaned up
        cmd = mock_create.call_args[0]
        body_file_idx = list(cmd).index("--body-file") + 1
        tmp_file = Path(cmd[body_file_idx])
        assert not tmp_file.exists()

    @pytest.mark.asyncio
    async def test_dry_run_skips(self, dry_config, event_bus) -> None:
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr.update_issue_body(42, "body")

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_warning_on_failure(self, config, event_bus, caplog) -> None:
        mgr = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("not found").build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr.update_issue_body(42, "body")

        assert "Could not update body" in caplog.text


# ---------------------------------------------------------------------------
# fetch_code_scanning_alerts
# ---------------------------------------------------------------------------


class TestFetchCodeScanningAlerts:
    """Tests for PRManager.fetch_code_scanning_alerts."""

    @pytest.mark.asyncio
    async def test_returns_empty_in_dry_run(self, dry_config, event_bus):
        """Dry-run mode returns empty list."""
        manager = _make_manager(dry_config, event_bus)
        result = await manager.fetch_code_scanning_alerts("feature-branch")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_alerts_on_success(self, config, event_bus):
        """Successful API call returns parsed alert list."""
        manager = _make_manager(config, event_bus)
        alerts = [
            {
                "number": 1,
                "rule": "js/sql-injection",
                "severity": "error",
                "security_severity": "high",
                "path": "src/db.js",
                "start_line": 42,
                "message": "SQL injection vulnerability",
            }
        ]
        mock_create = SubprocessMockBuilder().with_stdout(json.dumps(alerts)).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.fetch_code_scanning_alerts("feature-branch")

        assert len(result) == 1
        assert result[0]["number"] == 1
        assert result[0]["path"] == "src/db.js"

    @pytest.mark.asyncio
    async def test_returns_empty_on_404(self, config, event_bus):
        """404 (no code scanning configured) returns empty list."""
        manager = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder()
            .with_returncode(1)
            .with_stderr("HTTP 404: Not Found")
            .build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.fetch_code_scanning_alerts("feature-branch")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_json_error(self, config, event_bus):
        """Malformed JSON returns empty list."""
        manager = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("not-json{").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.fetch_code_scanning_alerts("feature-branch")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_empty_stdout(self, config, event_bus):
        """Empty stdout returns empty list."""
        manager = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("  ").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await manager.fetch_code_scanning_alerts("feature-branch")

        assert result == []
