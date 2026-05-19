"""Sandbox-e2e scenario for TermProposerLoop (advisor-7qvd).

Two minimal ticks:

* ``test_no_candidates_returns_zero_stats`` — an empty src/ tree with no
  load-bearing-suffix classes means ``detect_candidates`` returns nothing
  and the loop exits with ``candidates=0, opened_pr=False``.

* ``test_draft_accepted_opens_pr`` — a src/ tree with one ``*Loop`` class,
  an LLM stub that returns a valid draft, and a seeded ``BotPRPort`` fake.
  The loop should propose the term and open one bot PR.

The loop's external surface (``TermProposerLLM.draft`` and
``BotPRPort.open_bot_pr``) is stubbed via pre-seeded port keys.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports
from ubiquitous_language import BoundedContext, TermDraft, TermKind

pytestmark = pytest.mark.scenario_loops


def _seed_src_with_loop_class(repo_root) -> None:
    """Seed src/ with one FreshLoop class that detect_candidates can pick up."""
    src = repo_root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "fresh_loop.py").write_text("class FreshLoop:\n    pass\n")


class TestTermProposerScenario:
    """advisor-7qvd — sandbox-e2e for TermProposerLoop."""

    async def test_no_candidates_returns_zero_stats(self, tmp_path) -> None:
        """Empty src/ -> detect_candidates finds nothing, loop returns candidates=0."""
        world = MockWorld(tmp_path)

        repo_root = world.harness.config.repo_root
        (repo_root / "src").mkdir(parents=True, exist_ok=True)

        fake_llm = MagicMock()
        fake_llm.draft = AsyncMock(return_value=None)

        fake_pr_port = MagicMock()
        fake_pr_port.open_bot_pr = AsyncMock(return_value=0)

        _seed_ports(
            world,
            term_proposer_llm=fake_llm,
            term_proposer_pr_port=fake_pr_port,
            term_proposer_repo_root=repo_root,
        )

        stats = await world.run_with_loops(["term_proposer"], cycles=1)

        result = stats["term_proposer"]
        assert result is not None, result
        assert result["candidates"] == 0
        assert result["opened_pr"] is False
        fake_pr_port.open_bot_pr.assert_not_awaited()

    async def test_draft_accepted_opens_pr(self, tmp_path) -> None:
        """FreshLoop class in src/ + LLM returns valid draft -> one bot PR opened."""
        world = MockWorld(tmp_path)

        repo_root = world.harness.config.repo_root
        _seed_src_with_loop_class(repo_root)

        # The LLM stub returns a draft that passes validate_draft.
        valid_draft = TermDraft(
            include=True,
            name="FreshLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.CARETAKER,
            definition=(
                "A caretaker loop that periodically refreshes stale data"
                " and enforces freshness invariants across the system."
            ),
            invariants=["Freshness invariant: data is never more than N minutes old"],
            aliases=[],
        )

        fake_llm = MagicMock()
        fake_llm.draft = AsyncMock(return_value=valid_draft)

        fake_pr_port = MagicMock()
        fake_pr_port.open_bot_pr = AsyncMock(return_value=99)

        _seed_ports(
            world,
            term_proposer_llm=fake_llm,
            term_proposer_pr_port=fake_pr_port,
            term_proposer_repo_root=repo_root,
        )

        stats = await world.run_with_loops(["term_proposer"], cycles=1)

        result = stats["term_proposer"]
        assert result is not None, result
        assert result["candidates"] >= 1
        assert result["opened_pr"] is True
        fake_pr_port.open_bot_pr.assert_awaited_once()
        call_kwargs = fake_pr_port.open_bot_pr.await_args.kwargs
        assert "ul-proposer/" in call_kwargs["branch"]
        assert "FreshLoop" in call_kwargs["body"]
