"""Tests for the pre-merge preview verification phase."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from preview_phase import (
    PreviewPhase,
    _APPROVAL_KEYWORDS,
    _PREVIEW_COMMENT_MARKER,
    _REJECTION_KEYWORDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    """Build a minimal config mock for preview phase tests."""
    cfg = MagicMock()
    cfg.preview_enabled = True
    cfg.preview_interval = 300
    cfg.preview_timeout_hours = 72
    cfg.preview_deploy_poll_minutes = 30
    cfg.preview_timeout_action = "hitl"
    cfg.preview_label = ["hydraflow-preview"]
    cfg.review_label = ["hydraflow-review"]
    cfg.ready_label = ["hydraflow-ready"]
    cfg.hitl_label = ["hydraflow-hitl"]
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_task(issue_number: int = 42):
    """Build a minimal Task mock."""
    task = MagicMock()
    task.id = issue_number
    return task


def _make_phase(**overrides):
    """Build a PreviewPhase with mocked dependencies."""
    config = overrides.pop("config", _make_config())
    state = overrides.pop("state", MagicMock())
    prs = overrides.pop("prs", MagicMock())
    store = overrides.pop("store", MagicMock())
    event_bus = overrides.pop("event_bus", MagicMock())
    post_merge = overrides.pop("post_merge", MagicMock())

    # Set up async mocks
    prs.find_pr_for_issue = AsyncMock(return_value=100)
    prs.get_deployment_url = AsyncMock(return_value=None)
    prs.post_comment = AsyncMock()
    prs.get_issue_comments_with_body = AsyncMock(return_value=[])
    prs.swap_pipeline_labels = AsyncMock()
    event_bus.publish = AsyncMock()

    # State defaults
    state.get_preview_started = MagicMock(return_value=None)
    state.set_preview_started = MagicMock()
    state.is_preview_url_posted = MagicMock(return_value=False)
    state.mark_preview_url_posted = MagicMock()
    state.clear_preview = MagicMock()

    # Store defaults
    store.get_previewable = MagicMock(return_value=[])
    store.mark_active = MagicMock()
    store.mark_done = MagicMock()

    phase = PreviewPhase(
        config=config,
        state=state,
        prs=prs,
        store=store,
        event_bus=event_bus,
        post_merge=post_merge,
    )
    return phase, config, state, prs, store, event_bus


# ---------------------------------------------------------------------------
# Tests — process_preview_issues
# ---------------------------------------------------------------------------


class TestProcessPreviewIssues:
    """Tests for the top-level process_preview_issues method."""

    @pytest.mark.asyncio
    async def test_returns_false_when_disabled(self):
        phase, config, *_ = _make_phase()
        config.preview_enabled = False
        assert await phase.process_preview_issues() is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_tasks(self):
        phase, *_ = _make_phase()
        assert await phase.process_preview_issues() is False

    @pytest.mark.asyncio
    async def test_processes_tasks_and_returns_true(self):
        phase, _, state, prs, store, _ = _make_phase()
        task = _make_task(42)
        store.get_previewable.return_value = [task]

        result = await phase.process_preview_issues()

        assert result is True
        store.mark_active.assert_called_once()
        store.mark_done.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — first seen (no deployment yet)
# ---------------------------------------------------------------------------


class TestFirstSeen:
    """Tests for issues seen for the first time in preview stage."""

    @pytest.mark.asyncio
    async def test_no_deployment_records_start_time(self):
        phase, _, state, prs, *_ = _make_phase()
        prs.get_deployment_url.return_value = None

        await phase._process_single(_make_task(42))

        state.set_preview_started.assert_called_once()
        state.mark_preview_url_posted.assert_not_called()

    @pytest.mark.asyncio
    async def test_deployment_found_posts_url(self):
        phase, _, state, prs, _, bus = _make_phase()
        prs.get_deployment_url.return_value = "https://preview.example.com"

        await phase._process_single(_make_task(42))

        state.set_preview_started.assert_called_once()
        prs.post_comment.assert_called_once()
        comment_body = prs.post_comment.call_args[0][1]
        assert "https://preview.example.com" in comment_body
        assert _PREVIEW_COMMENT_MARKER in comment_body
        state.mark_preview_url_posted.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — deployment polling
# ---------------------------------------------------------------------------


class TestDeploymentPolling:
    """Tests for polling for deployment URL after preview started."""

    @pytest.mark.asyncio
    async def test_deployment_found_on_poll(self):
        phase, _, state, prs, _, bus = _make_phase()
        started = datetime.now(UTC).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = False
        prs.get_deployment_url.return_value = "https://deploy.example.com"

        await phase._process_single(_make_task(42))

        prs.post_comment.assert_called_once()
        state.mark_preview_url_posted.assert_called_once()

    @pytest.mark.asyncio
    async def test_deployment_timeout_merges_without_preview(self):
        phase, config, state, prs, *_ = _make_phase()
        config.preview_deploy_poll_minutes = 30
        started = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = False
        prs.get_deployment_url.return_value = None

        await phase._process_single(_make_task(42))

        prs.post_comment.assert_called_once()
        assert "No preview deployment" in prs.post_comment.call_args[0][1]
        prs.swap_pipeline_labels.assert_called_once()
        state.clear_preview.assert_called_once()

    @pytest.mark.asyncio
    async def test_still_polling_no_action(self):
        phase, config, state, prs, *_ = _make_phase()
        config.preview_deploy_poll_minutes = 30
        started = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = False
        prs.get_deployment_url.return_value = None

        await phase._process_single(_make_task(42))

        prs.post_comment.assert_not_called()
        prs.swap_pipeline_labels.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — reporter feedback
# ---------------------------------------------------------------------------


class TestReporterFeedback:
    """Tests for detecting reporter approval/rejection in comments."""

    @pytest.mark.asyncio
    async def test_approval_triggers_merge(self):
        phase, _, state, prs, _, bus = _make_phase()
        started = datetime.now(UTC).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = True
        prs.get_issue_comments_with_body.return_value = [
            {"author": "bot", "body": _PREVIEW_COMMENT_MARKER, "created_at": "t1"},
            {"author": "reporter", "body": "Looks good to me!", "created_at": "t2"},
        ]

        await phase._process_single(_make_task(42))

        prs.swap_pipeline_labels.assert_called_once_with(42, "hydraflow-review")
        state.clear_preview.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejection_routes_back_to_implementation(self):
        phase, _, state, prs, *_ = _make_phase()
        started = datetime.now(UTC).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = True
        prs.get_issue_comments_with_body.return_value = [
            {"author": "bot", "body": _PREVIEW_COMMENT_MARKER, "created_at": "t1"},
            {
                "author": "reporter",
                "body": "Still broken, the button is misaligned",
                "created_at": "t2",
            },
        ]

        await phase._process_single(_make_task(42))

        prs.swap_pipeline_labels.assert_called_once_with(42, "hydraflow-ready")
        state.clear_preview.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_feedback_no_action(self):
        phase, _, state, prs, *_ = _make_phase()
        started = datetime.now(UTC).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = True
        prs.get_issue_comments_with_body.return_value = [
            {"author": "bot", "body": _PREVIEW_COMMENT_MARKER, "created_at": "t1"},
        ]

        await phase._process_single(_make_task(42))

        prs.swap_pipeline_labels.assert_not_called()
        state.clear_preview.assert_not_called()

    @pytest.mark.asyncio
    async def test_comments_before_preview_marker_ignored(self):
        phase, _, state, prs, *_ = _make_phase()
        started = datetime.now(UTC).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = True
        prs.get_issue_comments_with_body.return_value = [
            {"author": "reporter", "body": "looks good", "created_at": "t0"},
            {"author": "bot", "body": _PREVIEW_COMMENT_MARKER, "created_at": "t1"},
        ]

        await phase._process_single(_make_task(42))

        # "looks good" was before the marker, so should be ignored
        prs.swap_pipeline_labels.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — timeout
# ---------------------------------------------------------------------------


class TestPreviewTimeout:
    """Tests for preview timeout handling."""

    @pytest.mark.asyncio
    async def test_timeout_hitl_escalation(self):
        phase, config, state, prs, *_ = _make_phase()
        config.preview_timeout_hours = 72
        config.preview_timeout_action = "hitl"
        started = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = True
        prs.get_issue_comments_with_body.return_value = [
            {"author": "bot", "body": _PREVIEW_COMMENT_MARKER, "created_at": "t1"},
        ]

        await phase._process_single(_make_task(42))

        prs.swap_pipeline_labels.assert_called_once_with(42, "hydraflow-hitl")
        state.clear_preview.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_auto_merge(self):
        phase, config, state, prs, *_ = _make_phase()
        config.preview_timeout_hours = 72
        config.preview_timeout_action = "merge"
        started = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = True
        prs.get_issue_comments_with_body.return_value = [
            {"author": "bot", "body": _PREVIEW_COMMENT_MARKER, "created_at": "t1"},
        ]

        await phase._process_single(_make_task(42))

        prs.swap_pipeline_labels.assert_called_once_with(42, "hydraflow-review")
        state.clear_preview.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — no PR found
# ---------------------------------------------------------------------------


class TestNoPR:
    @pytest.mark.asyncio
    async def test_no_pr_skips(self):
        phase, _, state, prs, *_ = _make_phase()
        prs.find_pr_for_issue.return_value = 0

        await phase._process_single(_make_task(42))

        prs.get_deployment_url.assert_not_called()
        state.set_preview_started.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — keyword matching
# ---------------------------------------------------------------------------


class TestKeywordMatching:
    """Verify approval and rejection keywords are sensible."""

    def test_approval_keywords_exist(self):
        assert len(_APPROVAL_KEYWORDS) > 0
        assert "lgtm" in _APPROVAL_KEYWORDS

    def test_rejection_keywords_exist(self):
        assert len(_REJECTION_KEYWORDS) > 0
        assert "still broken" in _REJECTION_KEYWORDS

    @pytest.mark.asyncio
    @pytest.mark.parametrize("keyword", _APPROVAL_KEYWORDS)
    async def test_each_approval_keyword_detected(self, keyword):
        phase, _, state, prs, _, bus = _make_phase()
        started = datetime.now(UTC).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = True
        prs.get_issue_comments_with_body.return_value = [
            {"author": "bot", "body": _PREVIEW_COMMENT_MARKER, "created_at": "t1"},
            {"author": "user", "body": keyword, "created_at": "t2"},
        ]

        await phase._process_single(_make_task(42))

        prs.swap_pipeline_labels.assert_called_once_with(42, "hydraflow-review")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("keyword", _REJECTION_KEYWORDS)
    async def test_each_rejection_keyword_detected(self, keyword):
        phase, _, state, prs, *_ = _make_phase()
        started = datetime.now(UTC).isoformat()
        state.get_preview_started.return_value = started
        state.is_preview_url_posted.return_value = True
        prs.get_issue_comments_with_body.return_value = [
            {"author": "bot", "body": _PREVIEW_COMMENT_MARKER, "created_at": "t1"},
            {"author": "user", "body": keyword, "created_at": "t2"},
        ]

        await phase._process_single(_make_task(42))

        prs.swap_pipeline_labels.assert_called_once_with(42, "hydraflow-ready")
