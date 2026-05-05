"""Tests for the ubiquitous-language module."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermRel,
    TermRelKind,
    dump_term_file,
    load_term_file,
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


class TestTermFileFormat:
    def test_round_trip_through_disk(self, tmp_path: Path) -> None:
        original = Term(
            id="01HX000000000000000000000A",
            name="RepoWikiLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="Background loop ingesting session events into the repo wiki.",
            invariants=[
                "Idempotent — re-ingesting the same session is a no-op.",
                "Never blocks the main pipeline.",
            ],
            code_anchor="src/repo_wiki_loop.py:RepoWikiLoop",
            aliases=["repo wiki loop", "wiki ingest loop"],
            confidence="accepted",
        )
        path = tmp_path / "repo-wiki-loop.md"
        dump_term_file(path, original)

        loaded = load_term_file(path)
        assert loaded.id == original.id
        assert loaded.name == original.name
        assert loaded.invariants == original.invariants
        assert loaded.aliases == original.aliases
        assert loaded.confidence == "accepted"

    def test_load_rejects_missing_frontmatter(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.md"
        path.write_text("just prose, no frontmatter")
        with pytest.raises(ValueError, match="frontmatter"):
            load_term_file(path)
