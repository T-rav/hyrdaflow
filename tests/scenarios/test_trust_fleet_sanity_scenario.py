"""MockWorld scenario for TrustFleetSanityLoop (spec §12.1).

Two scenarios:

* ``test_no_anomaly_no_file`` — all nine watched loops reporting fresh
  heartbeats with zero issue production and zero errors. The sanity loop
  should file nothing.
* ``test_staleness_breach_files_escalation`` — `flake_tracker` heartbeat
  is old enough that the staleness detector fires. The loop should file
  one ``hitl-escalation`` + ``trust-loop-anomaly`` issue with labels
  that include the breached detector kind.

The loop's external surface (``_collect_window_metrics`` via the
EventBus, ``_load_cost_reader``, ``_reconcile_closed_escalations``) is
stubbed via pre-seeded port keys.
"""

from __future__ import annotations

import datetime as _dt
from unittest.mock import AsyncMock, MagicMock

import pytest

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
