"""Tests for the bot-PR opener used by TermProposerLoop."""

from __future__ import annotations

from pathlib import Path

import pytest

from term_proposer_loop import open_proposer_pr
from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
)


class FakePRPort:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def open_bot_pr(
        self,
        *,
        branch: str,
        title: str,
        body: str,
        labels: list[str],
        files: dict[str, str],
    ) -> int:
        self.calls.append(
            {
                "branch": branch,
                "title": title,
                "body": body,
                "labels": labels,
                "files": files,
            }
        )
        return 9999


class TestOpenProposerPR:
    @pytest.mark.asyncio
    async def test_opens_pr_with_terms_as_files(self) -> None:
        terms = [
            Term(
                name="FooLoop",
                kind=TermKind.LOOP,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="A test foo loop drafted for the bot-PR opener test fixture.",
                code_anchor="src/foo.py:FooLoop",
                confidence="proposed",
                proposed_by="TermProposerLoop",
            ),
            Term(
                name="BarRunner",
                kind=TermKind.RUNNER,
                bounded_context=BoundedContext.BUILDER,
                definition="A test bar runner drafted for the bot-PR opener test fixture.",
                code_anchor="src/bar.py:BarRunner",
                confidence="proposed",
                proposed_by="TermProposerLoop",
            ),
        ]
        port = FakePRPort()
        pr_number = await open_proposer_pr(
            terms=terms,
            run_id="abc123",
            port=port,
            terms_root=Path("docs/wiki/terms"),
        )
        assert pr_number == 9999
        assert len(port.calls) == 1
        call = port.calls[0]
        assert call["branch"] == "ul-proposer/abc123"
        assert "term-proposer batch" in call["title"]
        assert "FooLoop" in call["body"]
        assert "BarRunner" in call["body"]
        assert "hydraflow-ul-proposed" in call["labels"]
        assert "docs/wiki/terms/foo-loop.md" in call["files"]
        assert "docs/wiki/terms/bar-runner.md" in call["files"]
        assert "---" in call["files"]["docs/wiki/terms/foo-loop.md"]

    @pytest.mark.asyncio
    async def test_returns_none_when_terms_empty(self) -> None:
        port = FakePRPort()
        pr_number = await open_proposer_pr(
            terms=[],
            run_id="abc123",
            port=port,
            terms_root=Path("docs/wiki/terms"),
        )
        assert pr_number is None
        assert port.calls == []
