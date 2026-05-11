"""Unit tests for EdgeProposerLoop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from edge_proposer_loop import EdgeProposerLoop
from tests.test_term_proposer_pr_opener import FakePRPort
from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermRel,
    TermRelKind,
    TermStore,
)


def _seed(repo: Path, *terms: Term) -> None:
    terms_dir = repo / "docs" / "wiki" / "terms"
    terms_dir.mkdir(parents=True, exist_ok=True)
    store = TermStore(terms_dir)
    for t in terms:
        store.write(t)


def _build_loop(repo: Path) -> tuple[EdgeProposerLoop, FakePRPort]:
    fake_port = FakePRPort()
    deps = MagicMock()
    config = MagicMock()
    config.edge_proposer_enabled = True
    config.edge_proposer_interval = 86400
    return (
        EdgeProposerLoop(config=config, deps=deps, pr_port=fake_port, repo_root=repo),
        fake_port,
    )


class TestEdgeProposerLoop:
    @pytest.mark.asyncio
    async def test_kill_switch_returns_disabled(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        loop, port = _build_loop(tmp_path)
        loop._config.edge_proposer_enabled = False
        result = await loop._do_work()
        assert result == {"status": "disabled"}
        assert port.calls == []

    @pytest.mark.asyncio
    async def test_proposes_depends_on_from_imports(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "alpha.py").write_text(
            "from bravo import Bravo\n\nclass Alpha:\n    pass\n"
        )
        (src / "bravo.py").write_text("class Bravo:\n    pass\n")
        _seed(
            tmp_path,
            Term(
                id="01H_ALPHA",
                name="Alpha",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="Alpha service that depends on Bravo.",
                code_anchor="src/alpha.py:Alpha",
                confidence="accepted",
            ),
            Term(
                id="01H_BRAVO",
                name="Bravo",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="Bravo service used by Alpha.",
                code_anchor="src/bravo.py:Bravo",
                confidence="accepted",
            ),
        )
        loop, port = _build_loop(tmp_path)
        result = await loop._do_work()
        assert result["edges"] == 1
        assert result["terms_touched"] == 1
        assert len(port.calls) == 1
        body = port.calls[0]["body"]
        assert "Alpha" in body and "Bravo" in body and "depends_on" in body

    @pytest.mark.asyncio
    async def test_proposes_implements_from_inheritance(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "ports.py").write_text(
            "from typing import Protocol\n\nclass Port(Protocol):\n    pass\n"
        )
        (src / "adapter.py").write_text(
            "from ports import Port\n\nclass Adapter(Port):\n    pass\n"
        )
        _seed(
            tmp_path,
            Term(
                id="01H_PORT",
                name="Port",
                kind=TermKind.PORT,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="Hexagonal port for Adapter.",
                code_anchor="src/ports.py:Port",
                confidence="accepted",
            ),
            Term(
                id="01H_ADAPTER",
                name="Adapter",
                kind=TermKind.ADAPTER,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="Adapter that implements the Port.",
                code_anchor="src/adapter.py:Adapter",
                confidence="accepted",
            ),
        )
        loop, port = _build_loop(tmp_path)
        result = await loop._do_work()
        # Adapter -> Port via implements (and depends_on from the import)
        assert result["edges"] >= 1
        assert "implements" in port.calls[0]["body"]

    @pytest.mark.asyncio
    async def test_existing_edge_not_duplicated(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "alpha.py").write_text(
            "from bravo import Bravo\n\nclass Alpha:\n    pass\n"
        )
        (src / "bravo.py").write_text("class Bravo:\n    pass\n")
        _seed(
            tmp_path,
            Term(
                id="01H_ALPHA",
                name="Alpha",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="Alpha already linked to Bravo.",
                code_anchor="src/alpha.py:Alpha",
                confidence="accepted",
                related=[TermRel(kind=TermRelKind.DEPENDS_ON, target="01H_BRAVO")],
            ),
            Term(
                id="01H_BRAVO",
                name="Bravo",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="Bravo.",
                code_anchor="src/bravo.py:Bravo",
                confidence="accepted",
            ),
        )
        loop, port = _build_loop(tmp_path)
        result = await loop._do_work()
        assert result["edges"] == 0
        assert port.calls == []

    @pytest.mark.asyncio
    async def test_no_proposals_no_pr(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "alpha.py").write_text("class Alpha:\n    pass\n")
        _seed(
            tmp_path,
            Term(
                id="01H_ALPHA",
                name="Alpha",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="Lonely Alpha with no relevant imports.",
                code_anchor="src/alpha.py:Alpha",
                confidence="accepted",
            ),
        )
        loop, port = _build_loop(tmp_path)
        result = await loop._do_work()
        assert result["edges"] == 0
        assert port.calls == []
