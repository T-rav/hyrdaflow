"""Caretaker loop scenarios L9–L13 — covers loops beyond L1–L8 in test_loops.py.

Each scenario seeds a MockWorld, runs one real BaseBackgroundLoop subclass via
``run_with_loops()``, and asserts on the observable result or mock call counts.

Because the inner delegates (adr_reviewer, memory_sync, etc.) are injected as
AsyncMock / MagicMock objects through ``world._loop_ports``, the loops exercise
their full _do_work() dispatch path without touching real I/O.

Strategy for injecting port mocks before the catalog creates its defaults:
    world._loop_ports is initialised lazily on the first run_with_loops() call.
    We pre-seed it ourselves so the catalog's ``ports.get(key) or MagicMock()``
    finds our mock and uses it instead of creating a bare MagicMock().
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


def _seed_ports(world: MockWorld, extra: dict) -> None:
    """Pre-initialise world._loop_ports with base fakes + caller-supplied mocks.

    MockWorld lazily creates _loop_ports on the first run_with_loops() call.
    By seeding it here we ensure our AsyncMocks are in place before the catalog
    builder runs ``ports.get(key) or MagicMock()``.
    """
    if not hasattr(world, "_loop_ports"):
        world._loop_ports = {
            "github": world.github,
            "workspace": world._workspace,
            "hindsight": world._hindsight,
            "sentry": world._sentry,
            "clock": world._clock,
        }
    world._loop_ports.update(extra)


# ---------------------------------------------------------------------------
# L9: ADR Reviewer loop invokes reviewer delegate
# ---------------------------------------------------------------------------


class TestL9ADRReviewerLoop:
    """L9: adr_reviewer_loop calls review_proposed_adrs on its delegate."""

    async def test_adr_reviewer_loop_invokes_reviewer(self, tmp_path) -> None:
        """ADRReviewerLoop._do_work delegates entirely to adr_reviewer.review_proposed_adrs.

        We inject an AsyncMock as the adr_reviewer port before the catalog
        builds the loop, so the await inside _do_work succeeds.  The return
        value propagates back as the loop's stats dict.
        """
        world = MockWorld(tmp_path)

        fake_reviewer = AsyncMock()
        fake_reviewer.review_proposed_adrs.return_value = {
            "reviewed": 2,
            "accepted": 1,
            "deferred": 1,
        }
        _seed_ports(world, {"adr_reviewer": fake_reviewer})

        stats = await world.run_with_loops(["adr_reviewer"], cycles=1)

        assert stats["adr_reviewer"] is not None
        assert stats["adr_reviewer"]["reviewed"] == 2
        assert stats["adr_reviewer"]["accepted"] == 1
        fake_reviewer.review_proposed_adrs.assert_called_once()

    async def test_adr_reviewer_loop_returns_none_passthrough(self, tmp_path) -> None:
        """ADRReviewerLoop passes through None if reviewer returns None.

        Verifies the loop does not wrap or mutate a None result.
        """
        world = MockWorld(tmp_path)

        fake_reviewer = AsyncMock()
        fake_reviewer.review_proposed_adrs.return_value = None
        _seed_ports(world, {"adr_reviewer": fake_reviewer})

        stats = await world.run_with_loops(["adr_reviewer"], cycles=1)

        assert stats["adr_reviewer"] is None
        fake_reviewer.review_proposed_adrs.assert_called_once()


# ---------------------------------------------------------------------------
# L10: Memory Sync loop reconciles drift via delegate
# ---------------------------------------------------------------------------


class TestL10MemorySyncLoop:
    """L10: memory_sync_loop calls sync() then publish_sync_event() on its delegate."""

    async def test_memory_sync_loop_calls_sync_and_publish(self, tmp_path) -> None:
        """MemorySyncLoop._do_work calls sync(), then publish_sync_event(result).

        Both methods are async on the real MemorySyncWorker.  We inject an
        AsyncMock so the awaits succeed, and assert both calls happened with
        the expected arguments.  The stats dict is a copy of the sync result.
        """
        world = MockWorld(tmp_path)

        sync_result = {"item_count": 42, "compacted": True, "evicted": 3}
        fake_memory_sync = AsyncMock()
        fake_memory_sync.sync.return_value = sync_result
        fake_memory_sync.publish_sync_event.return_value = None
        _seed_ports(world, {"memory_sync": fake_memory_sync})

        stats = await world.run_with_loops(["memory_sync"], cycles=1)

        assert stats["memory_sync"] is not None
        assert stats["memory_sync"]["item_count"] == 42
        assert stats["memory_sync"]["compacted"] is True
        fake_memory_sync.sync.assert_called_once()
        fake_memory_sync.publish_sync_event.assert_called_once_with(sync_result)

    async def test_memory_sync_loop_stats_is_copy_of_result(self, tmp_path) -> None:
        """Stats dict returned by the loop is a fresh copy of the sync result.

        The loop does ``return dict(result)`` so mutating stats should not
        affect the original dict held by the mock.
        """
        world = MockWorld(tmp_path)

        sync_result = {"item_count": 5, "compacted": False}
        fake_memory_sync = AsyncMock()
        fake_memory_sync.sync.return_value = sync_result
        fake_memory_sync.publish_sync_event.return_value = None
        _seed_ports(world, {"memory_sync": fake_memory_sync})

        stats = await world.run_with_loops(["memory_sync"], cycles=1)

        # Mutating the returned stats must not affect the original
        stats["memory_sync"]["item_count"] = 999
        assert sync_result["item_count"] == 5


# ---------------------------------------------------------------------------
# L11: Retrospective loop processes queue items
# ---------------------------------------------------------------------------


class TestL11RetrospectiveLoop:
    """L11: retrospective_loop drains its queue and records stats."""

    async def test_empty_queue_returns_zero_processed(self, tmp_path) -> None:
        """With an empty queue, the loop returns zero processed/patterns/stale.

        queue.load() is sync on RetrospectiveQueue so a plain MagicMock works.
        We configure it to return [] to exercise the early-return branch.
        """
        world = MockWorld(tmp_path)

        fake_queue = MagicMock()
        fake_queue.load.return_value = []
        _seed_ports(world, {"retrospective_queue": fake_queue})

        stats = await world.run_with_loops(["retrospective"], cycles=1)

        assert stats["retrospective"] == {
            "processed": 0,
            "patterns_filed": 0,
            "stale_proposals": 0,
        }
        fake_queue.load.assert_called_once()

    async def test_retro_patterns_item_processed_and_acknowledged(
        self, tmp_path
    ) -> None:
        """A RETRO_PATTERNS queue item causes _handle_retro_patterns to run.

        The retrospective collector's _load_recent and _detect_patterns are
        called.  The item id is acknowledged and processed count == 1.
        """
        from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

        world = MockWorld(tmp_path)

        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=77, pr_number=88)

        fake_queue = MagicMock()
        fake_queue.load.return_value = [item]

        fake_retro = MagicMock()
        fake_retro._load_recent.return_value = []
        fake_retro._detect_patterns = AsyncMock(return_value=None)

        _seed_ports(
            world,
            {
                "retrospective_queue": fake_queue,
                "retrospective": fake_retro,
            },
        )

        stats = await world.run_with_loops(["retrospective"], cycles=1)

        assert stats["retrospective"]["processed"] == 1
        fake_queue.acknowledge.assert_called_once_with([item.id])
        fake_retro._load_recent.assert_called_once()


# ---------------------------------------------------------------------------
# L12: Epic Sweeper verifies done-epic children closed
# ---------------------------------------------------------------------------


class TestL12EpicSweeperLoop:
    """L12: epic_sweeper_loop sweeps open epics and auto-closes completed ones."""

    async def test_no_epics_returns_zero_counts(self, tmp_path) -> None:
        """When no open epics exist, the loop reports zero checked and swept.

        IssueFetcherPort.fetch_issues_by_labels is async so we need AsyncMock.
        """
        world = MockWorld(tmp_path)

        fake_fetcher = AsyncMock()
        fake_fetcher.fetch_issues_by_labels.return_value = []
        fake_state = MagicMock()
        fake_state.get_epic_state.return_value = None
        _seed_ports(
            world,
            {
                "issue_fetcher": fake_fetcher,
                "epic_sweeper_state": fake_state,
            },
        )

        stats = await world.run_with_loops(["epic_sweeper"], cycles=1)

        assert stats["epic_sweeper"] is not None
        assert stats["epic_sweeper"]["checked"] == 0
        assert stats["epic_sweeper"]["swept"] == 0
        assert stats["epic_sweeper"]["total_open_epics"] == 0

    async def test_epic_with_all_closed_sub_issues_is_swept(self, tmp_path) -> None:
        """An epic whose sub-issues are all closed gets auto-closed by the sweeper.

        The epic body contains a checkbox reference to issue #200.  Issue #200
        is closed.  After one cycle: epic closed, comment posted via FakeGitHub.
        """
        from models import GitHubIssue  # noqa: PLC0415

        world = MockWorld(tmp_path)

        # Epic issue with a checkbox ref to sub-issue #200
        epic_body = "## Tasks\n- [x] #200 — implement feature\n"
        epic = GitHubIssue(
            number=100,
            title="Epic: Implement feature",
            body=epic_body,
            state="open",
            labels=["hydraflow-epic"],
        )

        # Sub-issue that is already closed
        sub_issue = GitHubIssue(
            number=200,
            title="Implement feature",
            body="",
            state="closed",
            labels=[],
        )

        # Pre-seed FakeGitHub so close_issue / post_comment have a real target
        world.github.add_issue(100, epic.title, epic.body, labels=epic.labels)
        world.github.add_issue(200, sub_issue.title, sub_issue.body, labels=[])
        world.github.issue(200).state = "closed"

        fake_fetcher = AsyncMock()
        fake_fetcher.fetch_issues_by_labels.return_value = [epic]
        fake_fetcher.fetch_issue_by_number.return_value = sub_issue

        fake_state = MagicMock()
        fake_state.get_epic_state.return_value = None  # no formal EpicState children

        _seed_ports(
            world,
            {
                "issue_fetcher": fake_fetcher,
                "epic_sweeper_state": fake_state,
            },
        )

        stats = await world.run_with_loops(["epic_sweeper"], cycles=1)

        assert stats["epic_sweeper"]["swept"] == 1
        assert stats["epic_sweeper"]["checked"] == 1
        # FakeGitHub close_issue should have been called
        assert world.github.issue(100).state == "closed"


# ---------------------------------------------------------------------------
# L13: Security Patch loop files issues from Dependabot alerts
# ---------------------------------------------------------------------------


class TestL13SecurityPatchLoop:
    """L13: security_patch_loop creates patch issues from dependabot alerts."""

    async def test_no_alerts_returns_zero_filed(self, tmp_path) -> None:
        """When Dependabot returns no alerts, filed == 0 and no issues created.

        FakeGitHub.get_dependabot_alerts returns [] by default, so no extra
        setup is required.
        """
        world = MockWorld(tmp_path)

        stats = await world.run_with_loops(["security_patch"], cycles=1)

        assert stats["security_patch"] is not None
        assert stats["security_patch"]["filed"] == 0
        assert stats["security_patch"]["total_alerts"] == 0

    async def test_fixable_high_severity_alert_files_issue(self, tmp_path) -> None:
        """A fixable, high-severity alert causes the loop to file a GitHub issue.

        We monkeypatch FakeGitHub.get_dependabot_alerts to return one alert
        matching the default severity threshold (high).  After one cycle the
        loop should have filed exactly one issue.
        """
        world = MockWorld(tmp_path)

        alert = {
            "number": 1,
            "security_vulnerability": {
                "package": {"name": "requests"},
                "severity": "high",
                "first_patched_version": {"identifier": "2.32.0"},
            },
            "security_advisory": {
                "summary": "SSRF vulnerability in requests",
            },
        }

        async def _fake_alerts(**_kw):
            return [alert]

        world.github.get_dependabot_alerts = _fake_alerts

        initial_issue_count = len(world.github._issues)

        stats = await world.run_with_loops(["security_patch"], cycles=1)

        assert stats["security_patch"]["filed"] == 1
        assert stats["security_patch"]["total_alerts"] == 1
        assert stats["security_patch"]["skipped_dedup"] == 0
        assert len(world.github._issues) == initial_issue_count + 1

    async def test_dry_run_skips_all_alerts(self, tmp_path) -> None:
        """When dry_run=True, the loop returns None without filing any issues.

        We instantiate SecurityPatchLoop directly with a dry-run config rather
        than going through run_with_loops, which cannot pass dry_run=True.
        """
        from base_background_loop import LoopDeps  # noqa: PLC0415
        from security_patch_loop import SecurityPatchLoop  # noqa: PLC0415
        from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

        world = MockWorld(tmp_path)

        alert = {
            "number": 2,
            "security_vulnerability": {
                "package": {"name": "urllib3"},
                "severity": "critical",
                "first_patched_version": {"identifier": "2.2.0"},
            },
            "security_advisory": {"summary": "Critical vuln"},
        }

        async def _fake_alerts(**_kw):
            return [alert]

        world.github.get_dependabot_alerts = _fake_alerts

        bg = make_bg_loop_deps(tmp_path, dry_run=True)
        loop_deps = LoopDeps(
            event_bus=bg.bus,
            stop_event=bg.stop_event,
            status_cb=bg.status_cb,
            enabled_cb=bg.enabled_cb,
            sleep_fn=bg.sleep_fn,
        )

        loop = SecurityPatchLoop(
            config=bg.config,
            pr_manager=world.github,
            deps=loop_deps,
        )
        result = await loop._do_work()

        assert result is None
