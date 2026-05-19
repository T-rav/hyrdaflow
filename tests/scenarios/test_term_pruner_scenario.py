"""Sandbox-e2e scenario for TermPrunerLoop (advisor-eg1i).

One happy-path tick: the loop discovers one accepted term whose
``code_anchor`` no longer resolves in ``src/``, deprecates it, and opens
a bot PR via the seeded ``BotPRPort`` fake.

The loop's external surface (``open_bot_pr`` via ``BotPRPort``) is stubbed
via pre-seeded port keys.  A real ``TermStore`` backed by tmp_path is seeded
with one accepted term whose anchor points at a class that does NOT exist in
the seeded source tree.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports
from ubiquitous_language import BoundedContext, Term, TermKind, TermStore, dump_term_file

pytestmark = pytest.mark.scenario_loops


def _seed_term_with_broken_anchor(terms_root: Path) -> None:
    """Write one accepted term whose code_anchor does not resolve in src/."""
    term = Term(
        name="StaleLoop",
        kind=TermKind.LOOP,
        bounded_context=BoundedContext.CARETAKER,
        definition="A loop whose anchor class was deleted from the codebase.",
        code_anchor="src/deleted_loop.py:StaleLoop",
        confidence="accepted",
    )
    terms_root.mkdir(parents=True, exist_ok=True)
    dump_term_file(terms_root / "stale-loop.md", term)


def _seed_src(repo_root: Path) -> None:
    """Seed a src/ tree that does NOT contain StaleLoop."""
    src = repo_root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "other_module.py").write_text("class OtherThing:\n    pass\n")


class TestTermPrunerScenario:
    """advisor-eg1i — sandbox-e2e for TermPrunerLoop."""

    async def test_broken_anchor_opens_deprecation_pr(self, tmp_path) -> None:
        """Accepted term with missing anchor -> deprecated + bot PR opened."""
        world = MockWorld(tmp_path)

        repo_root = world.harness.config.repo_root
        terms_root = repo_root / "docs" / "wiki" / "terms"
        _seed_term_with_broken_anchor(terms_root)
        _seed_src(repo_root)

        fake_pr_port = MagicMock()
        fake_pr_port.open_bot_pr = AsyncMock(return_value=42)

        _seed_ports(
            world,
            term_pruner_pr_port=fake_pr_port,
            term_pruner_repo_root=repo_root,
        )

        stats = await world.run_with_loops(["term_pruner"], cycles=1)

        result = stats["term_pruner"]
        assert result is not None, result
        assert result["deprecated"] == 1
        assert result["opened_pr"] is True
        fake_pr_port.open_bot_pr.assert_awaited_once()
        call_kwargs = fake_pr_port.open_bot_pr.await_args.kwargs
        assert "ul-pruner/" in call_kwargs["branch"]
        assert "StaleLoop" in call_kwargs["body"]

    async def test_all_anchors_resolve_no_pr_opened(self, tmp_path) -> None:
        """All accepted terms have live anchors -> no deprecation, no bot PR."""
        world = MockWorld(tmp_path)

        repo_root = world.harness.config.repo_root
        terms_root = repo_root / "docs" / "wiki" / "terms"
        src = repo_root / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "live_module.py").write_text("class LiveLoop:\n    pass\n")

        live_term = Term(
            name="LiveLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.CARETAKER,
            definition="A loop that is alive and resolves in the codebase.",
            code_anchor="src/live_module.py:LiveLoop",
            confidence="accepted",
        )
        terms_root.mkdir(parents=True, exist_ok=True)
        dump_term_file(terms_root / "live-loop.md", live_term)

        fake_pr_port = MagicMock()
        fake_pr_port.open_bot_pr = AsyncMock(return_value=0)

        _seed_ports(
            world,
            term_pruner_pr_port=fake_pr_port,
            term_pruner_repo_root=repo_root,
        )

        stats = await world.run_with_loops(["term_pruner"], cycles=1)

        result = stats["term_pruner"]
        assert result is not None, result
        assert result["deprecated"] == 0
        assert result["opened_pr"] is False
        fake_pr_port.open_bot_pr.assert_not_awaited()
