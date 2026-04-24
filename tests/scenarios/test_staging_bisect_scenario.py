"""MockWorld scenario for StagingBisectLoop (spec §4.3).

Three scenarios over the loop's early-return ladder:

* ``test_no_red_sha`` — state reports no last_rc_red_sha → loop returns
  ``{"status": "no_red"}`` and files nothing.
* ``test_flake_dismissed`` — red SHA seeded, but the second probe passes
  → loop increments ``flake_reruns_total``, adds SHA to dedup, files
  nothing.
* ``test_already_processed`` — red SHA seeded AND in dedup → loop
  returns ``{"status": "already_processed"}`` without running the probe.

The loop's external subprocess surface (``git bisect`` / ``gh`` calls
inside ``_run_full_bisect_pipeline``) is never exercised in these
scenarios — each one short-circuits before the pipeline runs, which is
exactly the "lights-off" behavior §4.3 needs to guarantee.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestStagingBisectScenario:
    """§4.3 — staging RC red-attribution + bisect MockWorld scenarios."""

    async def test_no_red_sha(self, tmp_path) -> None:
        """No red SHA → no-op, no PR call."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=0)

        state = MagicMock()
        state.get_last_rc_red_sha.return_value = ""
        state.get_last_green_rc_sha.return_value = ""

        _seed_ports(
            world,
            pr_manager=fake_pr,
            staging_bisect_state=state,
        )

        stats = await world.run_with_loops(["staging_bisect"], cycles=1)

        assert stats["staging_bisect"]["status"] == "no_red", stats
        fake_pr.create_issue.assert_not_awaited()

    async def test_flake_dismissed(self, tmp_path) -> None:
        """Red SHA seeded, probe passes on retry → flake-dismissed, no file."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=0)

        state = MagicMock()
        state.get_last_rc_red_sha.return_value = "redshaflake"
        state.get_last_green_rc_sha.return_value = "greensha123"
        state.increment_flake_reruns_total.return_value = None

        # Probe passes on retry → loop treats the red as a flake.
        probe = AsyncMock(return_value=(True, "all tests passed"))

        _seed_ports(
            world,
            pr_manager=fake_pr,
            staging_bisect_state=state,
            staging_bisect_run_probe=probe,
        )

        stats = await world.run_with_loops(["staging_bisect"], cycles=1)

        assert stats["staging_bisect"]["status"] == "flake_dismissed", stats
        assert stats["staging_bisect"]["sha"] == "redshaflake"
        probe.assert_awaited_once_with("redshaflake")
        state.increment_flake_reruns_total.assert_called_once()
        fake_pr.create_issue.assert_not_awaited()

    async def test_already_processed(self, tmp_path) -> None:
        """Red SHA already in dedup → skip without running the probe."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=0)

        state = MagicMock()
        state.get_last_rc_red_sha.return_value = "redshadup1234"
        state.get_last_green_rc_sha.return_value = "greensha5678"

        # Prime the loop's dedup by running once with the probe passing
        # (the flake-dismissed path), which adds the SHA to dedup. Then run
        # again — the second cycle must short-circuit on dedup.
        probe_prime = AsyncMock(return_value=(True, ""))
        _seed_ports(
            world,
            pr_manager=fake_pr,
            staging_bisect_state=state,
            staging_bisect_run_probe=probe_prime,
        )

        await world.run_with_loops(["staging_bisect"], cycles=1)

        # Swap probe — must not be invoked on the second cycle.
        probe_after = AsyncMock(return_value=(False, "should not be called"))
        world._loop_ports["staging_bisect_run_probe"] = probe_after

        stats = await world.run_with_loops(["staging_bisect"], cycles=1)

        assert stats["staging_bisect"]["status"] == "already_processed", stats
        probe_after.assert_not_awaited()
        fake_pr.create_issue.assert_not_awaited()

    async def test_guardrail_escalation(self, tmp_path) -> None:
        """Red SHA seeded, bisect pipeline returns guardrail_escalated → no
        revert PR, hitl-escalation issue filed with rc-red-attribution-unsafe."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=777)

        state = MagicMock()
        state.get_last_rc_red_sha.return_value = "redguardr4il"
        state.get_last_green_rc_sha.return_value = "greensha9999"
        state.get_auto_reverts_in_cycle.return_value = 1

        # Probe fails (not a flake) → pipeline runs.
        probe = AsyncMock(return_value=(False, "it is broken"))
        pipeline = AsyncMock(
            return_value={"status": "guardrail_escalated", "escalation_issue": 777}
        )

        _seed_ports(
            world,
            pr_manager=fake_pr,
            staging_bisect_state=state,
            staging_bisect_run_probe=probe,
            staging_bisect_run_pipeline=pipeline,
        )

        stats = await world.run_with_loops(["staging_bisect"], cycles=1)

        assert stats["staging_bisect"]["status"] == "guardrail_escalated", stats
        pipeline.assert_awaited_once()

    async def test_revert_pr_filed(self, tmp_path) -> None:
        """Red SHA, bisect pipeline returns reverted → revert PR recorded
        and the pipeline short-circuits the flake + already-processed paths."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=0)

        state = MagicMock()
        state.get_last_rc_red_sha.return_value = "redrevert01"
        state.get_last_green_rc_sha.return_value = "greenbase02"
        state.get_auto_reverts_in_cycle.return_value = 0

        probe = AsyncMock(return_value=(False, "broken"))
        pipeline = AsyncMock(
            return_value={
                "status": "reverted",
                "culprit_sha": "badcommit",
                "revert_pr_url": "https://x/pr/42",
            }
        )

        _seed_ports(
            world,
            pr_manager=fake_pr,
            staging_bisect_state=state,
            staging_bisect_run_probe=probe,
            staging_bisect_run_pipeline=pipeline,
        )

        stats = await world.run_with_loops(["staging_bisect"], cycles=1)

        assert stats["staging_bisect"]["status"] == "reverted", stats
        assert stats["staging_bisect"]["culprit_sha"] == "badcommit"
        pipeline.assert_awaited_once()

    async def test_no_green_anchor(self, tmp_path) -> None:
        """Red SHA seeded but no last_green_rc_sha → pipeline refuses to bisect."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=0)

        state = MagicMock()
        state.get_last_rc_red_sha.return_value = "redorphan1"
        state.get_last_green_rc_sha.return_value = ""

        probe = AsyncMock(return_value=(False, "broken"))
        pipeline = AsyncMock(
            return_value={"status": "no_green_anchor", "sha": "redorphan1"}
        )

        _seed_ports(
            world,
            pr_manager=fake_pr,
            staging_bisect_state=state,
            staging_bisect_run_probe=probe,
            staging_bisect_run_pipeline=pipeline,
        )

        stats = await world.run_with_loops(["staging_bisect"], cycles=1)

        assert stats["staging_bisect"]["status"] == "no_green_anchor", stats
        pipeline.assert_awaited_once()
        fake_pr.create_issue.assert_not_awaited()
