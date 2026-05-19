"""MockWorld scenario for TermProposerLoop (advisor-y6vf coverage gap).

Happy-path scenario: with no source files and no existing terms, the loop
detects zero candidates and returns the ok stats dict without calling the LLM
or opening a bot-PR.

The loop does real filesystem scanning (``build_symbol_index`` + ``build_import_graph``
+ ``detect_candidates``); pointing it at an empty ``tmp_path`` makes every
collection return empty, exercising the no-candidates early-return path cleanly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestTermProposerLoopScenario:
    """MockWorld scenario coverage for TermProposerLoop (ADR-0054)."""

    async def test_no_candidates_returns_zero_stats_without_calling_llm(
        self, tmp_path
    ) -> None:
        """No source files → 0 candidates → LLM never called, no PR opened.

        This is the minimal happy-path scenario that satisfies the MockWorld
        scenario coverage criterion: loop is in the catalog AND a scenario file
        invokes it via ``run_with_loops``.
        """
        world = MockWorld(tmp_path)

        fake_llm = AsyncMock()
        fake_llm.draft = AsyncMock()

        # Point the loop at tmp_path (empty); symbol index + candidates are empty.
        _seed_ports(
            world,
            term_proposer_repo_root=tmp_path,
            term_proposer_llm=fake_llm,
        )

        stats = await world.run_with_loops(["term_proposer"], cycles=1)

        result = stats["term_proposer"]
        assert result is not None
        assert result["status"] == "ok"
        assert result["candidates"] == 0
        assert result["drafted"] == 0
        assert result["validated"] == 0
        assert result["opened_pr"] is False

        # LLM must never be called if there are no candidates.
        fake_llm.draft.assert_not_awaited()
