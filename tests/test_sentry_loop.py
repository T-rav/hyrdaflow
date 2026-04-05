"""Tests for the Sentry issue ingestion background loop."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import ConfigFactory

_FAKE_TRANSCRIPT = "Created issue: https://github.com/T-rav/hydraflow/issues/999\nDone."


def _make_sentry_issue(
    issue_id: str = "12345",
    title: str = "TypeError: cannot read property 'foo'",
    culprit: str = "src/server.py in handle_request",
    count: str = "42",
    level: str = "error",
    is_unhandled: bool = True,
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
        "isUnhandled": is_unhandled,
    }


def _make_loop(config, prs, deps):
    from config import Credentials
    from sentry_loop import SentryLoop

    object.__setattr__(config, "sentry_org", "test-org")
    object.__setattr__(config, "sentry_project_filter", "")
    creds = Credentials(sentry_auth_token="sntryu_test")
    return SentryLoop(config=config, prs=prs, deps=deps, credentials=creds)


def _make_deps():
    from base_background_loop import LoopDeps

    deps = MagicMock(spec=LoopDeps)
    deps.event_bus = AsyncMock()
    deps.stop_event = MagicMock()
    deps.status_cb = MagicMock()
    deps.enabled_cb = MagicMock(return_value=True)
    deps.sleep_fn = AsyncMock()
    deps.interval_cb = None
    return deps


class TestSentryLoopDoWork:
    """Tests for the _do_work cycle."""

    @pytest.mark.asyncio
    async def test_skips_when_no_credentials(self, tmp_path: Path) -> None:
        from config import Credentials
        from sentry_loop import SentryLoop

        config = ConfigFactory.create(repo_root=tmp_path)
        # Ensure no credentials even if .env provides them
        object.__setattr__(config, "sentry_org", "")
        deps = _make_deps()
        prs = MagicMock()
        creds = Credentials(sentry_auth_token="")

        loop = SentryLoop(config=config, prs=prs, deps=deps, credentials=creds)
        result = await loop._do_work()

        assert result is not None
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_creates_github_issue_for_new_sentry_issue(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")  # no existing issue

        loop = _make_loop(config, prs, deps)

        sentry_issue = _make_sentry_issue()
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "myproject"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[sentry_issue]),
            patch.object(
                loop, "_create_github_issue", return_value=True
            ) as mock_create,
            patch.object(loop, "_resolve_sentry_issue", new_callable=AsyncMock),
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] == 1
        assert result["projects_polled"] == 1
        mock_create.assert_called_once_with(sentry_issue, "myproject")

    @pytest.mark.asyncio
    async def test_agent_invoked_with_hf_issue(self, tmp_path: Path) -> None:
        """_create_github_issue invokes stream_claude_process with /hf.issue prompt."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        sentry_issue = _make_sentry_issue()
        with (
            patch(
                "runner_utils.stream_claude_process",
                new_callable=AsyncMock,
                return_value=_FAKE_TRANSCRIPT,
            ),
            patch("agent_cli.build_agent_command", return_value=["claude"]),
            patch.object(
                loop, "_fetch_latest_event", new_callable=AsyncMock, return_value=None
            ),
        ):
            result = await loop._create_github_issue(sentry_issue, "myproject")

        assert result is True

    @pytest.mark.asyncio
    async def test_agent_failure_returns_false(self, tmp_path: Path) -> None:
        """_create_github_issue returns False when agent raises."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        sentry_issue = _make_sentry_issue()
        with (
            patch(
                "runner_utils.stream_claude_process",
                new_callable=AsyncMock,
                side_effect=RuntimeError("agent crash"),
            ),
            patch("agent_cli.build_agent_command", return_value=["claude"]),
            patch.object(
                loop, "_fetch_latest_event", new_callable=AsyncMock, return_value=None
            ),
        ):
            result = await loop._create_github_issue(sentry_issue, "myproject")

        assert result is False

    @pytest.mark.asyncio
    async def test_skips_already_filed_sentry_issue(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="1")  # already exists

        loop = _make_loop(config, prs, deps)

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

    @pytest.mark.asyncio
    async def test_dedup_cache_prevents_repeat_filing(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")

        loop = _make_loop(config, prs, deps)

        issue = _make_sentry_issue()
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[issue]),
            patch.object(loop, "_create_github_issue", return_value=True),
            patch.object(loop, "_resolve_sentry_issue", new_callable=AsyncMock),
        ):
            await loop._do_work()
            # Second run — same issue should be skipped via in-memory cache
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] == 0
        assert result["issues_skipped"] == 1

    @pytest.mark.asyncio
    async def test_config_has_sentry_max_creation_attempts(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        assert hasattr(config, "sentry_max_creation_attempts")
        assert config.sentry_max_creation_attempts == 3

    @pytest.mark.asyncio
    async def test_parks_after_max_creation_attempts(self, tmp_path: Path) -> None:
        """After N failed attempts, issue is parked and not retried."""
        from state import StateTracker

        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")
        state = StateTracker(tmp_path / "state.json")

        loop = _make_loop(config, prs, deps)
        loop._state = state
        object.__setattr__(config, "sentry_max_creation_attempts", 2)

        # Pre-load 2 failed attempts
        state.fail_sentry_creation("12345")
        state.fail_sentry_creation("12345")

        issue = _make_sentry_issue(issue_id="12345")
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[issue]),
            patch.object(
                loop, "_create_github_issue", return_value=True
            ) as mock_create,
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["issues_skipped"] == 1
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_tracks_failed_attempt(self, tmp_path: Path) -> None:
        """Failed creation increments the attempt counter in state."""
        from state import StateTracker

        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")
        state = StateTracker(tmp_path / "state.json")

        loop = _make_loop(config, prs, deps)
        loop._state = state

        issue = _make_sentry_issue(issue_id="55555")
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[issue]),
            patch.object(loop, "_create_github_issue", return_value=False),
        ):
            await loop._do_work()

        assert state.get_sentry_creation_attempts("55555") == 1

    @pytest.mark.asyncio
    async def test_dedup_persists_across_instances(self, tmp_path: Path) -> None:
        """Filed sentry IDs survive instance recreation (via DedupStore)."""
        from config import Credentials
        from dedup_store import DedupStore
        from sentry_loop import SentryLoop

        config = ConfigFactory.create(repo_root=tmp_path)
        object.__setattr__(config, "sentry_org", "test-org")
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")
        creds = Credentials(sentry_auth_token="sntryu_test")
        dedup = DedupStore("sentry_filed", tmp_path / "dedup" / "sentry_filed.json")

        loop1 = SentryLoop(
            config=config,
            prs=prs,
            deps=deps,
            credentials=creds,
            dedup=dedup,
        )

        issue = _make_sentry_issue()
        with (
            patch.object(loop1, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop1, "_fetch_unresolved", return_value=[issue]),
            patch.object(loop1, "_create_github_issue", return_value=True),
            patch.object(loop1, "_resolve_sentry_issue", new_callable=AsyncMock),
        ):
            await loop1._do_work()

        # New instance with same DedupStore — should skip the already-filed issue
        loop2 = SentryLoop(
            config=config,
            prs=prs,
            deps=deps,
            credentials=creds,
            dedup=dedup,
        )

        with (
            patch.object(loop2, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop2, "_fetch_unresolved", return_value=[issue]),
            patch.object(
                loop2, "_create_github_issue", return_value=True
            ) as mock_create,
        ):
            result = await loop2._do_work()

        assert result is not None
        assert result["issues_skipped"] == 1
        mock_create.assert_not_called()


class TestSentryLoopFiltering:
    """Tests for noise filtering (handled errors, low event count)."""

    @pytest.mark.asyncio
    async def test_skips_handled_exceptions(self, tmp_path: Path) -> None:
        """Handled exceptions (isUnhandled=False) should be skipped."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")

        loop = _make_loop(config, prs, deps)

        handled_issue = _make_sentry_issue(is_unhandled=False)
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[handled_issue]),
            patch.object(
                loop, "_create_github_issue", return_value=True
            ) as mock_create,
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] == 0
        assert result["issues_skipped"] == 1
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_passes_unhandled_exceptions(self, tmp_path: Path) -> None:
        """Unhandled exceptions (isUnhandled=True) should be filed."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")

        loop = _make_loop(config, prs, deps)

        unhandled_issue = _make_sentry_issue(is_unhandled=True)
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[unhandled_issue]),
            patch.object(loop, "_create_github_issue", return_value=True),
            patch.object(loop, "_resolve_sentry_issue", new_callable=AsyncMock),
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] == 1

    @pytest.mark.asyncio
    async def test_skips_low_event_count(self, tmp_path: Path) -> None:
        """Issues with fewer events than sentry_min_events should be skipped."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)
        object.__setattr__(config, "sentry_min_events", 5)

        low_count_issue = _make_sentry_issue(count="2")
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[low_count_issue]),
            patch.object(
                loop, "_create_github_issue", return_value=True
            ) as mock_create,
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] == 0
        assert result["issues_skipped"] == 1
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_passes_high_event_count(self, tmp_path: Path) -> None:
        """Issues meeting the min event threshold should be filed."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")

        loop = _make_loop(config, prs, deps)
        object.__setattr__(config, "sentry_min_events", 5)

        high_count_issue = _make_sentry_issue(count="10")
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[high_count_issue]),
            patch.object(loop, "_create_github_issue", return_value=True),
            patch.object(loop, "_resolve_sentry_issue", new_callable=AsyncMock),
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] == 1

    @pytest.mark.asyncio
    async def test_defaults_to_unhandled_when_field_missing(
        self, tmp_path: Path
    ) -> None:
        """If isUnhandled is missing from the API response, treat as unhandled (file it)."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")

        loop = _make_loop(config, prs, deps)

        # Issue without isUnhandled field
        issue = _make_sentry_issue()
        del issue["isUnhandled"]
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[issue]),
            patch.object(loop, "_create_github_issue", return_value=True),
            patch.object(loop, "_resolve_sentry_issue", new_callable=AsyncMock),
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] == 1


class TestSentryLoopProjectFilter:
    """Tests for project filtering."""

    @pytest.mark.asyncio
    async def test_filters_projects_by_config(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)
        object.__setattr__(config, "sentry_project_filter", "proj-a,proj-c")

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


class TestSentryStateMixin:
    """Tests for sentry state persistence."""

    def _make_tracker(self, tmp_path: Path):  # type: ignore[return]
        from state import StateTracker

        return StateTracker(tmp_path / "state.json")

    def test_fail_sentry_creation_increments(self, tmp_path: Path) -> None:
        tracker = self._make_tracker(tmp_path)
        assert tracker.fail_sentry_creation("12345") == 1
        assert tracker.fail_sentry_creation("12345") == 2
        assert tracker.fail_sentry_creation("99999") == 1

    def test_get_sentry_creation_attempts_default(self, tmp_path: Path) -> None:
        tracker = self._make_tracker(tmp_path)
        assert tracker.get_sentry_creation_attempts("12345") == 0

    def test_clear_sentry_creation_attempts(self, tmp_path: Path) -> None:
        tracker = self._make_tracker(tmp_path)
        tracker.fail_sentry_creation("12345")
        tracker.fail_sentry_creation("12345")
        tracker.clear_sentry_creation_attempts("12345")
        assert tracker.get_sentry_creation_attempts("12345") == 0

    def test_state_persists_across_reload(self, tmp_path: Path) -> None:
        tracker = self._make_tracker(tmp_path)
        tracker.fail_sentry_creation("12345")
        tracker.fail_sentry_creation("12345")

        tracker2 = self._make_tracker(tmp_path)
        assert tracker2.get_sentry_creation_attempts("12345") == 2


class TestSentryLoopWiring:
    """Tests for sentry loop wiring completeness."""

    def test_interval_bounds_includes_sentry_ingest(self) -> None:
        from dashboard_routes._common import _INTERVAL_BOUNDS

        assert "sentry_ingest" in _INTERVAL_BOUNDS
        lo, hi = _INTERVAL_BOUNDS["sentry_ingest"]
        assert lo == 60
        assert hi == 86400


class TestSentryLoopErrorClassification:
    """Tests for proper error classification in catch-all handlers."""

    @pytest.mark.asyncio
    async def test_reraises_type_error(self, tmp_path: Path) -> None:
        """TypeError (likely bug) should propagate, not be swallowed."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        sentry_issue = _make_sentry_issue()
        with (
            patch(
                "runner_utils.stream_claude_process",
                new_callable=AsyncMock,
                side_effect=TypeError("bad code"),
            ),
            patch("agent_cli.build_agent_command", return_value=["claude"]),
            patch.object(
                loop, "_fetch_latest_event", new_callable=AsyncMock, return_value=None
            ),
            pytest.raises(TypeError, match="bad code"),
        ):
            await loop._create_github_issue(sentry_issue, "myproject")

    @pytest.mark.asyncio
    async def test_swallows_runtime_error(self, tmp_path: Path) -> None:
        """RuntimeError (transient) should be caught and return False."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        sentry_issue = _make_sentry_issue()
        with (
            patch(
                "runner_utils.stream_claude_process",
                new_callable=AsyncMock,
                side_effect=RuntimeError("agent crash"),
            ),
            patch("agent_cli.build_agent_command", return_value=["claude"]),
            patch.object(
                loop, "_fetch_latest_event", new_callable=AsyncMock, return_value=None
            ),
        ):
            result = await loop._create_github_issue(sentry_issue, "myproject")

        assert result is False
