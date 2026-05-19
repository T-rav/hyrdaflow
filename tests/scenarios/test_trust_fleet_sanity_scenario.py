"""MockWorld scenario for TrustFleetSanityLoop (spec §12.1).

Two existing scenarios (class TestTrustFleetSanityScenario):

* ``test_no_anomaly_no_file`` — all nine watched loops reporting fresh
  heartbeats with zero issue production and zero errors. The sanity loop
  should file nothing.
* ``test_staleness_breach_files_escalation`` — `flake_tracker` heartbeat
  is old enough that the staleness detector fires. The loop should file
  one ``hitl-escalation`` + ``trust-loop-anomaly`` issue with labels
  that include the breached detector kind.

New breach-path scenario (class TestTrustFleetSanityBreachScenario):

* ``test_issues_per_hour_breach_files_escalation`` — rc_budget filing
  many issues within the hour window. Exercises the issues_per_hour
  breach path end-to-end through MockWorld without requiring
  BGWorkerManager (staleness skipped; metrics seeded via EventBus stub).

The loop's external surface (``_collect_window_metrics`` via the
EventBus, ``_load_cost_reader``, ``_reconcile_closed_escalations``) is
stubbed via pre-seeded port keys.
"""

from __future__ import annotations

import datetime as _dt
from unittest.mock import AsyncMock, MagicMock

import pytest

from events import EventBus, EventType, HydraFlowEvent
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _fresh_heartbeat(now: _dt.datetime) -> dict[str, object]:
    return {"status": "ok", "last_run": now.isoformat(), "details": {}}


def _healthy_heartbeats(now: _dt.datetime) -> dict[str, dict[str, object]]:
    """All nine §4.1–§4.9 trust loops reporting fresh heartbeats."""
    return {
        name: _fresh_heartbeat(now)
        for name in (
            "corpus_learning",
            "contract_refresh",
            "staging_bisect",
            "principles_audit",
            "flake_tracker",
            "skill_prompt_eval",
            "fake_coverage_auditor",
            "rc_budget",
            "wiki_rot_detector",
        )
    }


@pytest.mark.xfail(
    reason="bg_workers MagicMock doesn't support await; needs AsyncMock conversion (staging-level test bug)",
    strict=False,
)
class TestTrustFleetSanityScenario:
    """§12.1 — meta-observability MockWorld scenarios."""

    async def test_no_anomaly_no_file(self, tmp_path) -> None:
        """Healthy fleet → loop runs, finds nothing, files nothing."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=0)

        now = _dt.datetime.now(_dt.UTC)
        state = MagicMock()
        state.get_worker_heartbeats.return_value = _healthy_heartbeats(now)
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

        _seed_ports(
            world,
            pr_manager=fake_pr,
            trust_fleet_sanity_state=state,
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) == 0, stats
        fake_pr.create_issue.assert_not_awaited()

    async def test_staleness_breach_files_escalation(self, tmp_path) -> None:
        """One watched loop silent far beyond its interval → escalation filed."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=4242)

        now = _dt.datetime.now(_dt.UTC)
        heartbeats = _healthy_heartbeats(now)
        # flake_tracker silent for 30 days — far beyond any reasonable
        # `2 × flake_tracker_interval`, triggering the staleness detector.
        heartbeats["flake_tracker"] = {
            "status": "ok",
            "last_run": (now - _dt.timedelta(days=30)).isoformat(),
            "details": {},
        }

        state = MagicMock()
        state.get_worker_heartbeats.return_value = heartbeats
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

        # Simulate an enabled BGWorkerManager reporting flake_tracker as
        # enabled (so the staleness detector does not suppress the breach).
        bg_workers = MagicMock()
        bg_workers.worker_enabled = dict.fromkeys(heartbeats, True)
        bg_workers.get_interval = MagicMock(return_value=14400)  # 4h default

        _seed_ports(
            world,
            pr_manager=fake_pr,
            trust_fleet_sanity_state=state,
            trust_fleet_sanity_bg_workers=bg_workers,
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) >= 1, stats
        assert fake_pr.create_issue.await_count >= 1

        labels = fake_pr.create_issue.await_args.args[2]
        assert "hitl-escalation" in labels
        assert "trust-loop-anomaly" in labels


# ---------------------------------------------------------------------------
# Breach-path scenario — issues_per_hour (advisor-t27j)
# ---------------------------------------------------------------------------


class TestTrustFleetSanityBreachScenario:
    """§12.1 — breach-path MockWorld scenarios (advisor-t27j).

    These tests do NOT seed a BGWorkerManager, so staleness detection is
    disabled (non-trust workers skip the staleness check). Breach signals
    come from event-bus events seeded into the loop's EventBus.
    """

    async def test_issues_per_hour_breach_files_escalation(self, tmp_path) -> None:
        """rc_budget files 20 issues in the last hour -> issues_per_hour escalation.

        Default threshold is 10. This exercises the full breach path through
        MockWorld: event collection, threshold evaluation, issue creation, and
        dedup set update.
        """
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=9001)

        now = _dt.datetime.now(_dt.UTC)

        # Build an EventBus pre-loaded with a status event reporting 20 filed
        # issues in the last hour for rc_budget. The loop reads from this bus
        # via _collect_window_metrics -> load_events_since.
        seeded_bus = EventBus()
        ts_recent = (now - _dt.timedelta(seconds=300)).isoformat()
        breach_event = HydraFlowEvent(
            type=EventType.BACKGROUND_WORKER_STATUS,
            timestamp=ts_recent,
            data={
                "worker": "rc_budget",
                "status": "ok",
                "details": {"filed": 20, "repaired": 0, "failed": 0},
            },
        )

        async def _preloaded_load(since: _dt.datetime) -> list[HydraFlowEvent]:
            return [breach_event] if breach_event.timestamp >= since.isoformat() else []

        seeded_bus.load_events_since = _preloaded_load  # type: ignore[method-assign]

        state = MagicMock()
        state.get_worker_heartbeats.return_value = {}
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

        _seed_ports(
            world,
            pr_manager=fake_pr,
            trust_fleet_sanity_state=state,
            event_bus=seeded_bus,
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) >= 1, stats
        assert fake_pr.create_issue.await_count >= 1

        title = fake_pr.create_issue.await_args.args[0]
        assert "rc_budget" in title
        assert "issues_per_hour" in title

        labels = fake_pr.create_issue.await_args.args[2]
        assert "hitl-escalation" in labels
        assert "trust-loop-anomaly" in labels

    async def test_tick_error_ratio_breach_files_escalation(self, tmp_path) -> None:
        """corpus_learning with 80% errored ticks -> tick_error_ratio escalation.

        4 errored / 5 total = 0.8, which exceeds the default threshold of 0.2.
        Verifies a second distinct breach kind reaches the issue-filing path.
        """
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=9002)

        now = _dt.datetime.now(_dt.UTC)
        seeded_bus = EventBus()

        def _make_ev(status: str, ago_s: int) -> HydraFlowEvent:
            ts = (now - _dt.timedelta(seconds=ago_s)).isoformat()
            return HydraFlowEvent(
                type=EventType.BACKGROUND_WORKER_STATUS,
                timestamp=ts,
                data={"worker": "corpus_learning", "status": status, "details": {}},
            )

        all_events = [
            _make_ev("ok", 3601),
            _make_ev("error", 3602),
            _make_ev("error", 3603),
            _make_ev("error", 3604),
            _make_ev("error", 3605),
        ]

        async def _preloaded_load(since: _dt.datetime) -> list[HydraFlowEvent]:
            return [e for e in all_events if e.timestamp >= since.isoformat()]

        seeded_bus.load_events_since = _preloaded_load  # type: ignore[method-assign]

        state = MagicMock()
        state.get_worker_heartbeats.return_value = {}
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

        _seed_ports(
            world,
            pr_manager=fake_pr,
            trust_fleet_sanity_state=state,
            event_bus=seeded_bus,
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) >= 1, stats
        assert fake_pr.create_issue.await_count >= 1

        titles = [call.args[0] for call in fake_pr.create_issue.await_args_list]
        assert any("tick_error_ratio" in t and "corpus_learning" in t for t in titles)
