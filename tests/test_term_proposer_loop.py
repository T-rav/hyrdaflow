"""Unit tests for TermProposerLoop's per-tick flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config import HydraFlowConfig
from term_proposer_loop import TermProposerLoop
from tests.test_term_proposer_llm import FakeLLMClient
from tests.test_term_proposer_pr_opener import FakePRPort
from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermStore,
)


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> Path:
    """Build a fake repo: one covered term + one uncovered candidate."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text(
        "class FooLoop:\n    pass\n"
    )  # covered (will seed term)
    (src / "bar.py").write_text(
        "class BarRunner:\n    pass\n"
    )  # uncovered S1 candidate
    terms_dir = tmp_path / "docs" / "wiki" / "terms"
    terms_dir.mkdir(parents=True)
    store = TermStore(terms_dir)
    store.write(
        Term(
            name="FooLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="A pre-seeded term used to verify candidate exclusion of covered classes.",
            code_anchor="src/foo.py:FooLoop",
        )
    )
    return tmp_path


def _build_loop(
    repo: Path, *, fake_llm_response: dict
) -> tuple[TermProposerLoop, FakeLLMClient, FakePRPort]:
    """Construct a TermProposerLoop wired with fakes."""
    from term_proposer_llm import TermProposerLLM
    from tests.test_term_proposer_llm import FakeLLMClient
    from tests.test_term_proposer_pr_opener import FakePRPort

    fake_client = FakeLLMClient(response=fake_llm_response)
    fake_port = FakePRPort()
    deps = MagicMock()
    config = MagicMock(spec=HydraFlowConfig)
    config.term_proposer_enabled = True
    config.term_proposer_max_per_tick = 10
    config.term_proposer_cooldown_seconds = 86400
    config.term_proposer_interval = 14400

    loop = TermProposerLoop(
        config=config,
        deps=deps,
        llm=TermProposerLLM(client=fake_client),
        pr_port=fake_port,
        repo_root=repo,
        dedup_path=repo / ".dedup.json",
    )
    return loop, fake_client, fake_port


class TestTermProposerLoopFlow:
    @pytest.mark.asyncio
    async def test_kill_switch_returns_disabled(self, synthetic_repo: Path) -> None:
        loop, _, port = _build_loop(synthetic_repo, fake_llm_response={})
        loop._config.term_proposer_enabled = False
        result = await loop._do_work()
        assert result == {"status": "disabled"}
        assert port.calls == []

    @pytest.mark.asyncio
    async def test_drafts_validates_and_opens_pr(self, synthetic_repo: Path) -> None:
        loop, llm_client, port = _build_loop(
            synthetic_repo,
            fake_llm_response={
                "definition": "BarRunner is the test runner used to verify the per-tick flow integrates correctly.",
                "kind": "runner",
                "bounded_context": "builder",
                "aliases": ["bar runner"],
                "invariants": [],
                "depends_on_anchors": [],
            },
        )
        result = await loop._do_work()
        assert len(llm_client.calls) == 1
        assert len(port.calls) == 1
        call = port.calls[0]
        assert "BarRunner" in call["body"]
        assert result["candidates"] >= 1
        assert result["drafted"] == 1
        assert result["validated"] == 1
        assert result["filed_issues"] == 0
        assert result["opened_pr"] is True

    @pytest.mark.asyncio
    async def test_invalid_draft_filed_as_issue_not_pr(
        self, synthetic_repo: Path
    ) -> None:
        loop, _, port = _build_loop(
            synthetic_repo,
            fake_llm_response={
                "definition": "Short",  # too short — fails F1
                "kind": "runner",
                "bounded_context": "builder",
                "aliases": [],
                "invariants": [],
                "depends_on_anchors": [],
            },
        )
        result = await loop._do_work()
        assert port.calls == []
        assert result["validated"] == 0
        assert result["filed_issues"] >= 1

    @pytest.mark.asyncio
    async def test_no_candidates_no_pr_no_issues(self, tmp_path: Path) -> None:
        """If src/ has no uncovered classes, the tick is a no-op."""
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / "src").mkdir()
        (empty / "docs" / "wiki" / "terms").mkdir(parents=True)
        loop, _, port = _build_loop(
            empty,
            fake_llm_response={
                "definition": "x" * 30,
                "kind": "service",
                "bounded_context": "shared-kernel",
                "aliases": [],
                "invariants": [],
                "depends_on_anchors": [],
            },
        )
        result = await loop._do_work()
        assert result["candidates"] == 0
        assert port.calls == []
