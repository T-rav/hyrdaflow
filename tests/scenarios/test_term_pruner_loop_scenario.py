"""MockWorld scenario for TermPrunerLoop (advisor-y4e7 coverage gap).

Happy-path scenario: when no terms exist on disk, the loop reports
``deprecated=0`` and does not open a bot-PR.

The loop does real filesystem scanning (``TermStore.list`` + ``build_symbol_index``);
we point it at an empty ``tmp_path`` so both return empty collections, exercising
the no-candidates short-circuit path cleanly.
"""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestTermPrunerLoopScenario:
    """MockWorld scenario coverage for TermPrunerLoop (ADR-0057)."""

    async def test_empty_terms_dir_returns_zero_deprecated(self, tmp_path) -> None:
        """No terms on disk → 0 candidates, 0 deprecated, loop returns ok with no PR.

        This is the minimal happy-path scenario that satisfies the MockWorld
        scenario coverage criterion: loop is in the catalog AND a scenario file
        invokes it via ``run_with_loops``.
        """
        world = MockWorld(tmp_path)

        # Point the loop at tmp_path (empty); TermStore.list() returns [].
        _seed_ports(world, term_pruner_repo_root=tmp_path)

        stats = await world.run_with_loops(["term_pruner"], cycles=1)

        result = stats["term_pruner"]
        assert result is not None
        assert result["status"] == "ok"
        assert result["checked"] == 0
        assert result["deprecated"] == 0
        assert result["opened_pr"] is False
