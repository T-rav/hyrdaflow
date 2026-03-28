"""Tests for the Sentry issue ingestion background loop."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import ConfigFactory


def _make_sentry_issue(
    issue_id: str = "12345",
    title: str = "TypeError: cannot read property 'foo'",
    culprit: str = "src/server.py in handle_request",
    count: str = "42",
    level: str = "error",
) -> dict:
    return {
        "id": issue_id,
        "title": title,
        "culprit": culprit,
        "count": count,
        "firstSeen": "2026-03-20T10:00:00Z",
        "lastSeen": "2026-03-27T18:00:00Z",
        "level": level,
        "permalink": f"https://sentry.io/issues/{issue_id}/",
        "shortId": f"HYDRA-{issue_id}",
    }


class TestSentryLoopDoWork:
    """Tests for the _do_work cycle."""

    @pytest.mark.asyncio
    async def test_skips_when_no_credentials(self, tmp_path: Path) -> None:
        from base_background_loop import LoopDeps
        from sentry_loop import SentryLoop

        config = ConfigFactory.create(repo_root=tmp_path)
        deps = MagicMock(spec=LoopDeps)
        deps.event_bus = MagicMock()
        deps.stop_event = MagicMock()
        deps.status_cb = MagicMock()
        deps.enabled_cb = MagicMock(return_value=True)
        deps.sleep_fn = AsyncMock()
        deps.interval_cb = None
        prs = MagicMock()

        loop = SentryLoop(config=config, prs=prs, deps=deps)
        result = await loop._do_work()

        assert result is not None
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_creates_github_issue_for_new_sentry_issue(
        self, tmp_path: Path
    ) -> None:
        from base_background_loop import LoopDeps
        from sentry_loop import SentryLoop

        config = ConfigFactory.create(
            repo_root=tmp_path,
        )
        # Set sentry config via object attribute since ConfigFactory doesn't expose them
        object.__setattr__(config, "sentry_auth_token", "sntryu_test")
        object.__setattr__(config, "sentry_org", "test-org")
        object.__setattr__(config, "sentry_project_filter", "")

        deps = MagicMock(spec=LoopDeps)
        deps.event_bus = MagicMock()
        deps.stop_event = MagicMock()
        deps.status_cb = MagicMock()
        deps.enabled_cb = MagicMock(return_value=True)
        deps.sleep_fn = AsyncMock()
        deps.interval_cb = None

        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")  # no existing issue
        prs.create_issue = AsyncMock(return_value=100)

        loop = SentryLoop(config=config, prs=prs, deps=deps)

        sentry_issue = _make_sentry_issue()
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "myproject"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[sentry_issue]),
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] == 1
        assert result["projects_polled"] == 1
        prs.create_issue.assert_called_once()
        call_args = prs.create_issue.call_args
        assert "[Sentry]" in call_args[0][0]
        assert "sentry:12345" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_skips_already_filed_sentry_issue(self, tmp_path: Path) -> None:
        from base_background_loop import LoopDeps
        from sentry_loop import SentryLoop

        config = ConfigFactory.create(repo_root=tmp_path)
        object.__setattr__(config, "sentry_auth_token", "sntryu_test")
        object.__setattr__(config, "sentry_org", "test-org")
        object.__setattr__(config, "sentry_project_filter", "")

        deps = MagicMock(spec=LoopDeps)
        deps.event_bus = MagicMock()
        deps.stop_event = MagicMock()
        deps.status_cb = MagicMock()
        deps.enabled_cb = MagicMock(return_value=True)
        deps.sleep_fn = AsyncMock()
        deps.interval_cb = None

        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="1")  # already exists
        prs.create_issue = AsyncMock()

        loop = SentryLoop(config=config, prs=prs, deps=deps)

        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "myproject"}]),
            patch.object(
                loop, "_fetch_unresolved", return_value=[_make_sentry_issue()]
            ),
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] == 0
        assert result["issues_skipped"] == 1
        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_cache_prevents_repeat_filing(self, tmp_path: Path) -> None:
        from base_background_loop import LoopDeps
        from sentry_loop import SentryLoop

        config = ConfigFactory.create(repo_root=tmp_path)
        object.__setattr__(config, "sentry_auth_token", "sntryu_test")
        object.__setattr__(config, "sentry_org", "test-org")
        object.__setattr__(config, "sentry_project_filter", "")

        deps = MagicMock(spec=LoopDeps)
        deps.event_bus = MagicMock()
        deps.stop_event = MagicMock()
        deps.status_cb = MagicMock()
        deps.enabled_cb = MagicMock(return_value=True)
        deps.sleep_fn = AsyncMock()
        deps.interval_cb = None

        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")
        prs.create_issue = AsyncMock(return_value=100)

        loop = SentryLoop(config=config, prs=prs, deps=deps)

        issue = _make_sentry_issue()
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[issue]),
        ):
            await loop._do_work()
            # Second run — same issue should be skipped via in-memory cache
            prs.create_issue.reset_mock()
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] == 0
        assert result["issues_skipped"] == 1
        prs.create_issue.assert_not_called()


class TestSentryLoopProjectFilter:
    """Tests for project filtering."""

    @pytest.mark.asyncio
    async def test_filters_projects_by_config(self, tmp_path: Path) -> None:
        from base_background_loop import LoopDeps
        from sentry_loop import SentryLoop

        config = ConfigFactory.create(repo_root=tmp_path)
        object.__setattr__(config, "sentry_auth_token", "sntryu_test")
        object.__setattr__(config, "sentry_org", "test-org")
        object.__setattr__(config, "sentry_project_filter", "proj-a,proj-c")

        deps = MagicMock(spec=LoopDeps)
        deps.event_bus = MagicMock()
        deps.stop_event = MagicMock()
        deps.status_cb = MagicMock()
        deps.enabled_cb = MagicMock(return_value=True)
        deps.sleep_fn = AsyncMock()
        deps.interval_cb = None

        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")
        prs.create_issue = AsyncMock(return_value=100)

        loop = SentryLoop(config=config, prs=prs, deps=deps)

        all_projects = [
            {"slug": "proj-a"},
            {"slug": "proj-b"},
            {"slug": "proj-c"},
        ]

        with (
            patch("sentry_loop.httpx.AsyncClient") as mock_client_cls,
            patch.object(loop, "_fetch_unresolved", return_value=[]),
        ):
            mock_resp = MagicMock()
            mock_resp.json.return_value = all_projects
            mock_resp.raise_for_status = MagicMock()
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_resp))
            )
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            result = await loop._do_work()

        assert result is not None
        assert result["projects_polled"] == 2  # proj-a and proj-c, not proj-b
