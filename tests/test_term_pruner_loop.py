"""Unit tests for TermPrunerLoop's per-tick flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config import HydraFlowConfig
from term_pruner_loop import TermPrunerLoop
from tests.test_term_proposer_pr_opener import FakePRPort
from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermStore,
)


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> Path:
    """Build a fake repo with one anchored term + one orphan term."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "alive.py").write_text("class AliveLoop:\n    pass\n")
    # orphan.py NOT created → its term's anchor won't resolve
    terms_dir = tmp_path / "docs" / "wiki" / "terms"
    terms_dir.mkdir(parents=True)
    store = TermStore(terms_dir)
    store.write(
        Term(
            name="AliveLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="An anchored term that should NOT be pruned.",
            code_anchor="src/alive.py:AliveLoop",
            confidence="accepted",
        )
    )
    store.write(
        Term(
            name="OrphanLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="A term whose anchor was deleted; should be deprecated.",
            code_anchor="src/orphan.py:OrphanLoop",
            confidence="accepted",
        )
    )
    return tmp_path


def _build_loop(repo: Path) -> tuple[TermPrunerLoop, FakePRPort]:
    fake_port = FakePRPort()
    deps = MagicMock()
    config = MagicMock(spec=HydraFlowConfig)
    config.term_pruner_enabled = True
    config.term_pruner_interval = 86400

    loop = TermPrunerLoop(
        config=config,
        deps=deps,
        pr_port=fake_port,
        repo_root=repo,
    )
    return loop, fake_port


class TestTermPrunerLoopFlow:
    @pytest.mark.asyncio
    async def test_kill_switch_returns_disabled(self, synthetic_repo: Path) -> None:
        loop, port = _build_loop(synthetic_repo)
        loop._config.term_pruner_enabled = False
        result = await loop._do_work()
        assert result == {"status": "disabled"}
        assert port.calls == []

    @pytest.mark.asyncio
    async def test_orphan_term_deprecated_via_pr(self, synthetic_repo: Path) -> None:
        loop, port = _build_loop(synthetic_repo)
        result = await loop._do_work()
        assert result["checked"] == 2
        assert result["deprecated"] == 1
        assert result["opened_pr"] is True
        assert len(port.calls) == 1
        call = port.calls[0]
        assert "OrphanLoop" in call["body"]
        assert "AliveLoop" not in call["body"]
        assert "hydraflow-ul-deprecated" in call["labels"]
        # The PR's term file content should reflect confidence: deprecated
        orphan_file = call["files"]["docs/wiki/terms/orphan-loop.md"]
        assert "deprecated" in orphan_file
        assert "anchor" in orphan_file.lower()

    @pytest.mark.asyncio
    async def test_already_deprecated_term_not_re_pruned(
        self, synthetic_repo: Path
    ) -> None:
        # Mark the orphan as already deprecated; should NOT be re-included
        store = TermStore(synthetic_repo / "docs" / "wiki" / "terms")
        existing = store.load_by_name("OrphanLoop")
        assert existing is not None
        existing_data = existing.model_dump()
        existing_data["confidence"] = "deprecated"
        store.write(Term.model_validate(existing_data))

        loop, port = _build_loop(synthetic_repo)
        result = await loop._do_work()
        assert result["deprecated"] == 0
        assert port.calls == []

    @pytest.mark.asyncio
    async def test_already_superseded_term_not_pruned(
        self, synthetic_repo: Path
    ) -> None:
        store = TermStore(synthetic_repo / "docs" / "wiki" / "terms")
        existing = store.load_by_name("OrphanLoop")
        assert existing is not None
        existing_data = existing.model_dump()
        existing_data["superseded_by"] = "01H_OTHER"
        store.write(Term.model_validate(existing_data))

        loop, port = _build_loop(synthetic_repo)
        result = await loop._do_work()
        assert result["deprecated"] == 0
        assert port.calls == []

    @pytest.mark.asyncio
    async def test_no_orphans_no_pr(self, tmp_path: Path) -> None:
        # Repo with one anchored term, no orphans
        src = tmp_path / "src"
        src.mkdir()
        (src / "alive.py").write_text("class AliveLoop:\n    pass\n")
        terms_dir = tmp_path / "docs" / "wiki" / "terms"
        terms_dir.mkdir(parents=True)
        store = TermStore(terms_dir)
        store.write(
            Term(
                name="AliveLoop",
                kind=TermKind.LOOP,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="anchored",
                code_anchor="src/alive.py:AliveLoop",
                confidence="accepted",
            )
        )
        loop, port = _build_loop(tmp_path)
        result = await loop._do_work()
        assert result["checked"] == 1
        assert result["deprecated"] == 0
        assert port.calls == []
