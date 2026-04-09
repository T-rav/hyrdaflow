"""Background loop scenario tests — Tier B sanity checks.

These tests verify that MockWorld can interact with loop-adjacent state
(workspace tracking, config snapshots). Full loop orchestration with
real BaseBackgroundLoop subclasses is planned for v2.
"""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


class TestL1HealthMonitorConfigAccess:
    """L1: Verify the harness config is accessible for health-monitor-style reads."""

    async def test_config_max_quality_fix_attempts_readable(self, tmp_path):
        """The health monitor loop reads `config.max_quality_fix_attempts`.

        This sanity-check ensures MockWorld exposes the config correctly
        so loop-style tests can read and assert on tunable values.
        """
        world = MockWorld(tmp_path)
        config = world.harness.config
        # The config must expose the tunable health monitor adjusts
        assert hasattr(config, "max_quality_fix_attempts")
        # Default from ConfigFactory — reading it must not crash
        value = config.max_quality_fix_attempts
        assert isinstance(value, int)
        assert value >= 0


class TestL2WorkspaceGCTracking:
    """L2: FakeWorkspace tracks create/destroy — the invariant gc-style loops rely on."""

    async def test_workspace_lifecycle_is_observable(self, tmp_path):
        """GC-style loops iterate over workspace state to decide what to prune.

        This sanity-check verifies FakeWorkspace records both creates and
        destroys distinctly so scenario tests (and any future loop tests)
        can assert on GC behavior.
        """
        world = MockWorld(tmp_path)
        ws = world._workspace

        await ws.create(1, "agent/issue-1")
        await ws.create(2, "agent/issue-2")
        await ws.destroy(1)

        assert ws.created == [1, 2]
        assert ws.destroyed == [1]
        # Issue 2 is still "active" — a GC loop would leave it alone
        assert 2 not in ws.destroyed
