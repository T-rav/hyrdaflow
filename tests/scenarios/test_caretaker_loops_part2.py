"""Background loop scenario tests — L14-L23 (Tier 3 expansion).

Covers 10 additional caretaker loops. Created on a branch where Tier 2's
``test_caretaker_loops.py`` has NOT yet merged, so this file is standalone.
Cross-reference: Tier 2 covers L9-L13 in test_caretaker_loops.py.

Pattern A (most loops): seed a MockWorld, optionally pre-seed
``world._loop_ports`` with AsyncMock/MagicMock delegates, run the real
BaseBackgroundLoop via ``world.run_with_loops()``, assert on returned stats.

Pattern B (loops needing config overrides or special prs):
Use ``_make_loop_deps`` + direct loop instantiation for full control over
the config and dependencies. This avoids the ``run_with_loops`` limitation
that always resets the ``github`` port from ``self._github``.

Smoke tests (marked with "smoke" in docstrings) verify the loop executes
without raising rather than asserting specific observable side-effects —
used when the loop's ``_do_work`` path requires state that is too
expensive to reconstruct in the scenario harness.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


# ---------------------------------------------------------------------------
# Helper: pre-seed loop ports before run_with_loops
# ---------------------------------------------------------------------------


def _seed_ports(world: MockWorld, **kwargs: object) -> None:
    """Pre-seed world._loop_ports with mock variants before run_with_loops.

    Ensures loop instantiation picks up the mocks we control rather than
    the generic ones created on first call.  Note: ``github`` and
    ``workspace`` are always reset by ``run_with_loops``; use Pattern B
    (direct instantiation) if you need a custom prs mock.
    """
    if not hasattr(world, "_loop_ports"):
        world._loop_ports = {}
    for key, value in kwargs.items():
        world._loop_ports[key] = value


def _make_loop_deps(tmp_path, **config_overrides):
    """Return (config, loop_deps) using ConfigFactory with overrides.

    Use this for Pattern B tests that need fine-grained config control.
    """
    from base_background_loop import LoopDeps  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from tests.helpers import ConfigFactory  # noqa: PLC0415

    config = ConfigFactory.create(repo_root=tmp_path / "repo", **config_overrides)
    bus = EventBus()
    stop_event = asyncio.Event()
    stop_event.set()  # not used in direct _do_work calls

    loop_deps = LoopDeps(
        event_bus=bus,
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )
    return config, loop_deps


# ---------------------------------------------------------------------------
# L14: code_grooming — disabled path and dry-run path
# ---------------------------------------------------------------------------


class TestL14CodeGrooming:
    """L14: CodeGroomingLoop returns expected stats when disabled or dry-run.

    Pattern B: direct loop instantiation so we can control config flags
    (code_grooming_enabled, dry_run) without fighting run_with_loops' config.
    """

    async def test_disabled_returns_skipped(self, tmp_path):
        """When code_grooming_enabled is False, loop returns {"skipped": "disabled"}."""
        from code_grooming_loop import CodeGroomingLoop  # noqa: PLC0415

        config, deps = _make_loop_deps(tmp_path, code_grooming_enabled=False)
        prs = MagicMock()
        loop = CodeGroomingLoop(config=config, pr_manager=prs, deps=deps)

        result = await loop._do_work()

        assert result == {"skipped": "disabled"}

    async def test_dry_run_returns_none(self, tmp_path):
        """When dry_run is True, _do_work short-circuits and returns None."""
        from code_grooming_loop import CodeGroomingLoop  # noqa: PLC0415

        config, deps = _make_loop_deps(tmp_path, dry_run=True)
        prs = MagicMock()
        loop = CodeGroomingLoop(config=config, pr_manager=prs, deps=deps)

        result = await loop._do_work()

        assert result is None

    async def test_enabled_no_findings_returns_stats_shape(self, tmp_path):
        """When enabled but audit subprocess fails, stats still have the right keys.

        Smoke: _run_audit calls stream_claude_process which is not wired; the
        exception is caught and returns {"filed": 0, "error": True}.
        We assert on the stats shape rather than exact values.
        """
        from code_grooming_loop import CodeGroomingLoop  # noqa: PLC0415

        config, deps = _make_loop_deps(tmp_path, code_grooming_enabled=True)
        prs = MagicMock()
        loop = CodeGroomingLoop(config=config, pr_manager=prs, deps=deps)

        result = await loop._do_work()

        # Either {"filed": 0, "error": True} (subprocess missing) or real stats —
        # in both cases the "filed" key must exist and be an int.
        assert result is not None
        assert "filed" in result
        assert isinstance(result["filed"], int)


# ---------------------------------------------------------------------------
# L15: diagnostic — no issues and one-issue paths
# ---------------------------------------------------------------------------


class TestL15DiagnosticLoop:
    """L15: DiagnosticLoop polls for hydraflow-diagnose issues and processes them."""

    async def test_no_diagnose_issues_returns_zero_counts(self, tmp_path):
        """When no hydraflow-diagnose issues exist, all counters are zero."""
        world = MockWorld(tmp_path)

        stats = await world.run_with_loops(["diagnostic"], cycles=1)

        result = stats["diagnostic"]
        assert result is not None
        assert result["processed"] == 0
        assert result["fixed"] == 0
        assert result["escalated"] == 0
        assert result["retried"] == 0

    async def test_diagnose_issue_without_context_escalates(self, tmp_path):
        """An issue labelled hydraflow-diagnose with no escalation context → escalated.

        The state mock returns None for get_escalation_context, causing the
        loop to escalate the issue to HITL.
        """
        world = MockWorld(tmp_path)

        # Add a diagnose-labelled issue to FakeGitHub
        world.github.add_issue(
            55, "Broken widget", "Widget crashes on load", labels=["hydraflow-diagnose"]
        )

        # Configure the state mock: list_issues_by_label returns the issue,
        # get_escalation_context returns None → triggers HITL escalation path.
        diag_state = MagicMock()
        diag_state.get_escalation_context.return_value = None
        diag_state.get_diagnostic_attempts.return_value = []
        _seed_ports(world, diagnostic_state=diag_state)

        # list_issues_by_label must return the issue for the loop to pick it up.
        world.github._issues[55].labels = ["hydraflow-diagnose"]

        stats = await world.run_with_loops(["diagnostic"], cycles=1)

        result = stats["diagnostic"]
        assert result is not None
        assert result["processed"] == 1
        assert result["escalated"] == 1
        assert result["fixed"] == 0


# ---------------------------------------------------------------------------
# L16: epic_monitor — delegates to EpicManager
# ---------------------------------------------------------------------------


class TestL16EpicMonitorLoop:
    """L16: EpicMonitorLoop delegates stale-check and refresh to EpicManager."""

    async def test_no_stale_epics_returns_zero_stale(self, tmp_path):
        """When EpicManager reports no stale epics, stale_count=0."""
        world = MockWorld(tmp_path)

        epic_mgr = MagicMock()
        epic_mgr.check_stale_epics = AsyncMock(return_value=[])
        epic_mgr.refresh_cache = AsyncMock(return_value=None)
        epic_mgr.get_all_progress.return_value = {}
        _seed_ports(world, epic_manager=epic_mgr)

        stats = await world.run_with_loops(["epic_monitor"], cycles=1)

        result = stats["epic_monitor"]
        assert result is not None
        assert result["stale_count"] == 0
        assert result["tracked_epics"] == 0
        epic_mgr.check_stale_epics.assert_awaited_once()
        epic_mgr.refresh_cache.assert_awaited_once()

    async def test_stale_epics_reflected_in_stats(self, tmp_path):
        """When EpicManager reports 3 stale epics and 5 tracked, stats match."""
        world = MockWorld(tmp_path)

        fake_stale = [{"number": i} for i in range(3)]
        fake_progress = {i: {} for i in range(5)}

        epic_mgr = MagicMock()
        epic_mgr.check_stale_epics = AsyncMock(return_value=fake_stale)
        epic_mgr.refresh_cache = AsyncMock(return_value=None)
        epic_mgr.get_all_progress.return_value = fake_progress
        _seed_ports(world, epic_manager=epic_mgr)

        stats = await world.run_with_loops(["epic_monitor"], cycles=1)

        result = stats["epic_monitor"]
        assert result["stale_count"] == 3
        assert result["tracked_epics"] == 5


# ---------------------------------------------------------------------------
# L17: github_cache — delegates to GitHubDataCache.poll()
# ---------------------------------------------------------------------------


class TestL17GitHubCacheLoop:
    """L17: GitHubCacheLoop calls cache.poll() and passes through its stats."""

    async def test_poll_returns_expected_stats(self, tmp_path):
        """poll() result is forwarded as the loop's stats dict."""
        world = MockWorld(tmp_path)

        poll_result = {"open_prs": 4, "hitl_items": 1, "label_counts": True}
        cache = MagicMock()
        cache.poll = AsyncMock(return_value=poll_result)
        _seed_ports(world, github_cache=cache)

        stats = await world.run_with_loops(["github_cache"], cycles=1)

        result = stats["github_cache"]
        assert result == poll_result
        cache.poll.assert_awaited_once()

    async def test_empty_poll_result_returns_none(self, tmp_path):
        """When poll() returns {}, the loop returns None (falsy dict guard)."""
        world = MockWorld(tmp_path)

        cache = MagicMock()
        cache.poll = AsyncMock(return_value={})
        _seed_ports(world, github_cache=cache)

        stats = await world.run_with_loops(["github_cache"], cycles=1)

        # GitHubCacheLoop returns `stats or None`; empty dict is falsy → None
        assert stats["github_cache"] is None


# ---------------------------------------------------------------------------
# L18: repo_wiki — no repos and with repos paths
# ---------------------------------------------------------------------------


class TestL18RepoWikiLoop:
    """L18: RepoWikiLoop lints and optionally compiles per-repo wikis."""

    async def test_no_repos_returns_zero_stats(self, tmp_path):
        """When wiki_store.list_repos() is empty, early return with zero stats."""
        world = MockWorld(tmp_path)

        wiki_store = MagicMock()
        wiki_store.list_repos.return_value = []
        _seed_ports(world, wiki_store=wiki_store)

        stats = await world.run_with_loops(["repo_wiki"], cycles=1)

        result = stats["repo_wiki"]
        assert result == {"repos": 0, "total_entries": 0}

    async def test_one_repo_lint_runs(self, tmp_path):
        """With one repo, active_lint is called and stats reflect its results."""
        world = MockWorld(tmp_path)

        from repo_wiki import LintResult  # noqa: PLC0415

        lint_result = LintResult(
            stale_entries=1,
            orphan_entries=0,
            total_entries=5,
            entries_marked_stale=1,
            orphans_pruned=0,
            empty_topics=[],
        )

        wiki_store = MagicMock()
        wiki_store.list_repos.return_value = ["my-org/my-repo"]
        wiki_store.active_lint.return_value = lint_result
        _seed_ports(world, wiki_store=wiki_store)

        stats = await world.run_with_loops(["repo_wiki"], cycles=1)

        result = stats["repo_wiki"]
        assert result["repos"] == 1
        assert result["total_entries"] == 5
        assert result["stale_entries"] == 1
        wiki_store.active_lint.assert_called_once_with(
            "my-org/my-repo", closed_issues=set()
        )


# ---------------------------------------------------------------------------
# L19: report_issue — dry-run and empty-queue paths
# ---------------------------------------------------------------------------


class TestL19ReportIssueLoop:
    """L19: ReportIssueLoop processes queued bug reports into GitHub issues.

    Pattern B: direct instantiation to control dry_run and state cleanly.
    """

    async def test_dry_run_returns_none(self, tmp_path):
        """In dry_run mode _do_work short-circuits and returns None."""
        from report_issue_loop import ReportIssueLoop  # noqa: PLC0415

        config, deps = _make_loop_deps(tmp_path, dry_run=True)
        state = MagicMock()
        prs = MagicMock()
        loop = ReportIssueLoop(config=config, state=state, pr_manager=prs, deps=deps)

        result = await loop._do_work()

        assert result is None

    async def test_empty_queue_returns_none(self, tmp_path):
        """When the report queue is empty, _do_work returns None (no work)."""
        from report_issue_loop import ReportIssueLoop  # noqa: PLC0415

        config, deps = _make_loop_deps(tmp_path, dry_run=False)
        state = MagicMock()
        state.peek_report.return_value = None
        state.get_pending_reports.return_value = []
        state.get_filed_reports.return_value = []
        prs = MagicMock()
        loop = ReportIssueLoop(config=config, state=state, pr_manager=prs, deps=deps)

        result = await loop._do_work()

        assert result is None


# ---------------------------------------------------------------------------
# L20: runs_gc — purge_expired and purge_oversized paths
# ---------------------------------------------------------------------------


class TestL20RunsGCLoop:
    """L20: RunsGCLoop purges expired runs and enforces the size cap."""

    async def test_no_artifacts_returns_zero_purge(self, tmp_path):
        """When recorder returns 0 purged, stats reflect no work was done."""
        world = MockWorld(tmp_path)

        recorder = MagicMock()
        recorder.purge_expired.return_value = 0
        recorder.purge_oversized.return_value = 0
        recorder.get_storage_stats.return_value = {
            "total_runs": 0,
            "total_mb": 0.0,
            "issues": [],
        }
        _seed_ports(world, run_recorder=recorder)

        stats = await world.run_with_loops(["runs_gc"], cycles=1)

        result = stats["runs_gc"]
        assert result is not None
        assert result["expired_purged"] == 0
        assert result["oversized_purged"] == 0
        assert result["total_runs"] == 0
        assert result["total_mb"] == 0.0

    async def test_expired_runs_are_purged(self, tmp_path):
        """Recorder reports 3 expired and 1 oversized; stats reflect totals."""
        world = MockWorld(tmp_path)

        recorder = MagicMock()
        recorder.purge_expired.return_value = 3
        recorder.purge_oversized.return_value = 1
        recorder.get_storage_stats.return_value = {
            "total_runs": 12,
            "total_mb": 45.7,
            "issues": [1, 2, 3],
        }
        _seed_ports(world, run_recorder=recorder)

        stats = await world.run_with_loops(["runs_gc"], cycles=1)

        result = stats["runs_gc"]
        assert result["expired_purged"] == 3
        assert result["oversized_purged"] == 1
        assert result["total_runs"] == 12
        # Verify recorder was called with config values
        recorder.purge_expired.assert_called_once()
        recorder.purge_oversized.assert_called_once()


# ---------------------------------------------------------------------------
# L21: sentry — no credentials and project polling paths
# ---------------------------------------------------------------------------


class TestL21SentryLoop:
    """L21: SentryLoop skips gracefully when credentials are absent."""

    async def test_no_credentials_returns_skipped(self, tmp_path):
        """Without sentry_auth_token or sentry_org, loop returns skipped stats."""
        world = MockWorld(tmp_path)
        world.harness.config.sentry_org = ""

        stats = await world.run_with_loops(["sentry"], cycles=1)

        result = stats["sentry"]
        assert result is not None
        assert result.get("skipped") is True
        assert "reason" in result

    async def test_no_sentry_token_returns_skipped(self, tmp_path):
        """Without sentry_auth_token (even with org set), loop returns skipped."""
        world = MockWorld(tmp_path)
        world.harness.config.sentry_org = "my-org"

        # Credentials default to empty strings; sentry_auth_token is empty
        stats = await world.run_with_loops(["sentry"], cycles=1)

        result = stats["sentry"]
        assert result is not None
        assert result.get("skipped") is True


# ---------------------------------------------------------------------------
# L22: staging_promotion — disabled and cadence paths
# ---------------------------------------------------------------------------

# NOTE: staging_promotion is not registered in loop_registrations.py — it uses
# direct instantiation (Pattern B) throughout.


class TestL22StagingPromotionLoop:
    """L22: StagingPromotionLoop manages RC branch cuts and promotions to main.

    Uses Pattern B (direct instantiation) because staging_promotion is not
    registered in the catalog's loop_registrations.py, and the loop needs
    config fields (staging_enabled, rc_cadence_hours) that ConfigFactory
    doesn't expose.  We pass the config directly to HydraFlowConfig.
    """

    def _make_staging_loop(self, tmp_path, *, staging_enabled: bool, **extra):
        """Build a StagingPromotionLoop with controlled config and mock prs."""
        from base_background_loop import LoopDeps  # noqa: PLC0415
        from events import EventBus  # noqa: PLC0415
        from staging_promotion_loop import StagingPromotionLoop  # noqa: PLC0415
        from tests.helpers import ConfigFactory  # noqa: PLC0415

        base_config = ConfigFactory.create(repo_root=tmp_path / "repo")
        # Patch the staging fields onto the config object directly
        # (HydraFlowConfig is a Pydantic model, use model_copy with update)
        config = base_config.model_copy(
            update={"staging_enabled": staging_enabled, **extra}
        )

        bus = EventBus()
        stop_event = asyncio.Event()
        stop_event.set()
        deps = LoopDeps(
            event_bus=bus,
            stop_event=stop_event,
            status_cb=MagicMock(),
            enabled_cb=lambda _: True,
            sleep_fn=AsyncMock(),
        )

        prs = MagicMock()
        prs.find_open_promotion_pr = AsyncMock(return_value=None)
        prs.list_rc_branches = AsyncMock(return_value=[])
        prs.find_open_promotion_pr = AsyncMock(return_value=None)
        prs.create_rc_branch = AsyncMock(return_value="sha-abc")
        prs.create_promotion_pr = AsyncMock(return_value=42)
        prs.wait_for_ci = AsyncMock(return_value=(True, "all green"))

        return StagingPromotionLoop(config=config, prs=prs, deps=deps), prs, config

    async def test_staging_disabled_returns_disabled_status(self, tmp_path):
        """When staging_enabled is False, loop returns {"status": "staging_disabled"}."""
        loop, _, _ = self._make_staging_loop(tmp_path, staging_enabled=False)

        result = await loop._do_work()

        assert result is not None
        assert result["status"] == "staging_disabled"

    async def test_staging_enabled_no_open_pr_cadence_not_elapsed(self, tmp_path):
        """When staging is enabled but cadence has not elapsed, no RC is cut."""
        loop, _, config = self._make_staging_loop(tmp_path, staging_enabled=True)

        # Write a recent "last RC" timestamp so cadence is NOT elapsed
        cadence_path = config.data_root / "memory" / ".staging_promotion_last_rc"
        cadence_path.parent.mkdir(parents=True, exist_ok=True)
        cadence_path.write_text(datetime.now(UTC).isoformat())

        result = await loop._do_work()

        assert result is not None
        assert result["status"] == "cadence_not_elapsed"

    async def test_staging_enabled_cadence_elapsed_cuts_new_rc(self, tmp_path):
        """When staging enabled and cadence elapsed, a new RC branch is created."""
        loop, prs, config = self._make_staging_loop(tmp_path, staging_enabled=True)

        # Write an old "last RC" timestamp so cadence IS elapsed
        cadence_path = config.data_root / "memory" / ".staging_promotion_last_rc"
        cadence_path.parent.mkdir(parents=True, exist_ok=True)
        old_ts = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
        cadence_path.write_text(old_ts)

        result = await loop._do_work()

        assert result is not None
        # RC branch was cut and promotion PR opened
        assert result["status"] == "opened"
        assert "pr" in result
        assert "rc_branch" in result
        prs.create_rc_branch.assert_awaited_once()
        prs.create_promotion_pr.assert_awaited_once()


# ---------------------------------------------------------------------------
# L23: stale_issue — needs _run_gh; use direct instantiation (Pattern B)
# ---------------------------------------------------------------------------


class TestL23StaleIssueLoop:
    """L23: StaleIssueLoop auto-closes stale issues with no recent activity.

    StaleIssueLoop calls prs._run_gh() and prs._repo directly, which
    FakeGitHub does not implement.  We use Pattern B (direct instantiation)
    and pass a MagicMock that has _run_gh and _repo stubbed appropriately.
    """

    def _make_prs_mock(
        self, issues: list[dict], *, fail_fetch: bool = False
    ) -> MagicMock:
        """Return a MagicMock prs with _run_gh and _repo configured."""
        import json

        prs = MagicMock()
        prs._repo = "test-org/test-repo"
        if fail_fetch:
            prs._run_gh = AsyncMock(side_effect=RuntimeError("gh failed"))
        else:
            prs._run_gh = AsyncMock(return_value=json.dumps(issues))
        prs.post_comment = AsyncMock(return_value=None)
        return prs

    def _make_loop(self, tmp_path, prs, state):
        """Build a StaleIssueLoop with Pattern B (direct instantiation)."""
        from stale_issue_loop import StaleIssueLoop  # noqa: PLC0415

        config, deps = _make_loop_deps(tmp_path)
        return StaleIssueLoop(config=config, prs=prs, state=state, deps=deps)

    async def test_no_issues_returns_zero_stats(self, tmp_path):
        """When gh returns an empty issue list, all counters are zero."""
        prs = self._make_prs_mock([])
        state = MagicMock()
        state.get_stale_issue_settings.return_value = _stale_settings()
        state.get_stale_issue_closed.return_value = set()

        loop = self._make_loop(tmp_path, prs, state)
        result = await loop._do_work()

        assert result is not None
        assert result["closed"] == 0
        assert result["scanned"] == 0

    async def test_fresh_issue_not_closed(self, tmp_path):
        """Issues updated recently are scanned but not closed."""
        fresh_updated = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        issues = [
            {
                "number": 77,
                "title": "Fresh bug",
                "updatedAt": fresh_updated,
                "labels": [],
            }
        ]

        prs = self._make_prs_mock(issues)
        state = MagicMock()
        state.get_stale_issue_settings.return_value = _stale_settings(staleness_days=30)
        state.get_stale_issue_closed.return_value = set()

        loop = self._make_loop(tmp_path, prs, state)
        result = await loop._do_work()

        assert result["closed"] == 0
        assert result["scanned"] == 1

    async def test_stale_issue_is_dry_run_closed(self, tmp_path):
        """A stale issue in dry_run mode is counted closed but no API calls made."""
        stale_updated = (
            (datetime.now(UTC) - timedelta(days=60)).isoformat().replace("+00:00", "Z")
        )
        issues = [
            {
                "number": 88,
                "title": "Forgotten task",
                "updatedAt": stale_updated,
                "labels": [],
            }
        ]

        prs = self._make_prs_mock(issues)
        state = MagicMock()
        state.get_stale_issue_settings.return_value = _stale_settings(
            staleness_days=30, dry_run=True
        )
        state.get_stale_issue_closed.return_value = set()

        loop = self._make_loop(tmp_path, prs, state)
        result = await loop._do_work()

        assert result["closed"] == 1
        # In dry_run mode, post_comment is NOT called
        prs.post_comment.assert_not_awaited()

    async def test_fetch_failure_returns_zero_stats(self, tmp_path):
        """When gh fetch raises, loop handles it gracefully and returns zeroed stats."""
        prs = self._make_prs_mock([], fail_fetch=True)
        state = MagicMock()
        state.get_stale_issue_settings.return_value = _stale_settings()
        state.get_stale_issue_closed.return_value = set()

        loop = self._make_loop(tmp_path, prs, state)
        result = await loop._do_work()

        assert result is not None
        assert result["closed"] == 0


# ---------------------------------------------------------------------------
# Shared factory helpers
# ---------------------------------------------------------------------------


def _stale_settings(
    staleness_days: int = 30,
    excluded_labels: list[str] | None = None,
    dry_run: bool = False,
) -> object:
    """Return a StaleIssueSettings-compatible object."""
    from models import StaleIssueSettings  # noqa: PLC0415

    return StaleIssueSettings(
        staleness_days=staleness_days,
        excluded_labels=excluded_labels or [],
        dry_run=dry_run,
    )
