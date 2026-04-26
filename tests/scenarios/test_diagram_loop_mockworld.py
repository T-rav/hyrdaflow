"""MockWorld-based scenarios for DiagramLoop (L24).

These exercise the full ``run_with_loops`` path — same harness as every other
caretaker loop — so the loop's catalog wiring, port resolution, and dispatch
are all under test, not just ``_do_work`` in isolation.

Companion to ``tests/scenarios/test_diagram_loop_scenario.py`` (which calls
``_do_work`` directly with mocked seams).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestL24DiagramLoop:
    """L24: DiagramLoop regenerates docs/arch/generated/, opens PR on drift."""

    async def test_no_drift_runs_emit_and_skips_pr(self, tmp_path) -> None:
        """Clean source → emit() runs, git status empty, no PR opened."""
        world = MockWorld(tmp_path)

        github = AsyncMock(
            find_existing_issue=AsyncMock(return_value=0),
            create_issue=AsyncMock(return_value=0),
        )
        _seed_ports(world, github=github)

        pr_helper = AsyncMock()
        with (
            patch("arch.runner.emit") as mock_emit,
            patch("diagram_loop.subprocess.run") as mock_run,
            patch("auto_pr.open_automated_pr_async", pr_helper),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            stats = await world.run_with_loops(["diagram_loop"], cycles=1)

        result = stats["diagram_loop"]
        assert result == {"drift": False}
        mock_emit.assert_called_once()
        pr_helper.assert_not_awaited()
        github.find_existing_issue.assert_not_awaited()

    async def test_drift_opens_regen_pr_via_auto_pr(self, tmp_path) -> None:
        """Source drifted → auto_pr opens PR with arch-regen-auto branch."""
        world = MockWorld(tmp_path)

        github = AsyncMock(
            find_existing_issue=AsyncMock(return_value=0),
            create_issue=AsyncMock(return_value=0),
        )
        _seed_ports(world, github=github)

        pr_result = MagicMock(status="opened", pr_url="https://github.com/x/y/pull/1")
        pr_helper = AsyncMock(return_value=pr_result)

        with (
            patch("arch.runner.emit"),
            patch("diagram_loop.subprocess.run") as mock_run,
            patch("auto_pr.open_automated_pr_async", pr_helper),
            # Stub _unassigned_items to focus on the PR path.
            patch(
                "diagram_loop.DiagramLoop._unassigned_items",
                AsyncMock(return_value={"loops": [], "ports": []}),
            ),
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=" M docs/arch/generated/loops.md\n M docs/arch/generated/ports.md\n",
            )
            stats = await world.run_with_loops(["diagram_loop"], cycles=1)

        result = stats["diagram_loop"]
        assert result["drift"] is True
        assert result["pr_url"] == "https://github.com/x/y/pull/1"
        assert result["changed_files"] == 2

        pr_helper.assert_awaited_once()
        kwargs = pr_helper.await_args.kwargs
        assert kwargs["branch"] == "arch-regen-auto"
        assert "hydraflow-ready" in kwargs["labels"]
        assert kwargs["pr_title"].startswith(
            "chore(arch): regenerate architecture knowledge"
        )
