"""Tests for the ubiquitous-language module."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermRel,
    TermRelKind,
)


class TestTermModel:
    def test_minimal_term_round_trips(self) -> None:
        term = Term(
            name="RepoWikiLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="Background loop that ingests session events into the repo wiki.",
            code_anchor="src/repo_wiki_loop.py:RepoWikiLoop",
        )
        dumped = term.model_dump()
        rebuilt = Term.model_validate(dumped)
        assert rebuilt.name == "RepoWikiLoop"
        assert rebuilt.kind == TermKind.LOOP
        assert rebuilt.bounded_context == BoundedContext.SHARED_KERNEL
        assert rebuilt.confidence == "proposed"
        assert rebuilt.invariants == []
        assert rebuilt.aliases == []
        assert rebuilt.related == []
        assert rebuilt.evidence == []

    def test_canonical_name_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            Term(
                name="",
                kind=TermKind.LOOP,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x",
                code_anchor="src/x.py:Y",
            )

    def test_term_rel_round_trips(self) -> None:
        rel = TermRel(kind=TermRelKind.IMPLEMENTS, target="01HXYZ")
        rebuilt = TermRel.model_validate(rel.model_dump())
        assert rebuilt.kind == TermRelKind.IMPLEMENTS
        assert rebuilt.target == "01HXYZ"

    def test_confidence_enum_constrained(self) -> None:
        with pytest.raises(ValidationError):
            Term(
                name="X",
                kind=TermKind.LOOP,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x",
                code_anchor="src/x.py:Y",
                confidence="bogus",  # type: ignore[arg-type]
            )
