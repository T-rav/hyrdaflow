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
    TermStore,
    build_symbol_index,
    dump_term_file,
    lint_anchor_resolution,
    load_term_file,
    resolve_anchor,
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


class TestTermStore:
    def test_write_and_list(self, tmp_path: Path) -> None:
        store = TermStore(tmp_path / "terms")
        term = Term(
            name="RepoWikiLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="x",
            code_anchor="src/repo_wiki_loop.py:RepoWikiLoop",
        )
        store.write(term)
        listed = store.list()
        assert len(listed) == 1
        assert listed[0].name == "RepoWikiLoop"

    def test_filename_is_slugified_name(self, tmp_path: Path) -> None:
        store = TermStore(tmp_path / "terms")
        term = Term(
            name="RepoWikiLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="x",
            code_anchor="src/repo_wiki_loop.py:RepoWikiLoop",
        )
        store.write(term)
        assert (tmp_path / "terms" / "repo-wiki-loop.md").exists()

    def test_load_by_name(self, tmp_path: Path) -> None:
        store = TermStore(tmp_path / "terms")
        term = Term(
            name="PRPort",
            kind=TermKind.PORT,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="x",
            code_anchor="src/pr_port.py:PRPort",
        )
        store.write(term)
        loaded = store.load_by_name("PRPort")
        assert loaded is not None
        assert loaded.name == "PRPort"
        assert store.load_by_name("Nonexistent") is None


class TestSymbolIndexer:
    def test_finds_class_in_src(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.py").write_text("class Bar:\n    pass\n")
        (src / "baz.py").write_text("def quux():\n    pass\n\nclass Bar:\n    pass\n")
        index = build_symbol_index(src)
        assert "Bar" in index
        assert sorted(index["Bar"]) == ["src/baz.py:Bar", "src/foo.py:Bar"]

    def test_resolve_anchor_finds_existing(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.py").write_text("class Bar:\n    pass\n")
        index = build_symbol_index(src)
        assert resolve_anchor("src/foo.py:Bar", index) is True
        assert resolve_anchor("src/foo.py:Missing", index) is False
        assert resolve_anchor("src/missing.py:Bar", index) is False

    def test_resolve_anchor_via_alias_lookup(self, tmp_path: Path) -> None:
        """Anchor names that match by class name even with different paths
        should still produce a useful diagnostic — but resolution requires
        exact path match. This documents the exact-path policy."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("class Bar:\n    pass\n")
        index = build_symbol_index(src)
        assert resolve_anchor("src/b.py:Bar", index) is False


class TestAnchorResolutionLint:
    def test_clean_when_all_resolve(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.py").write_text("class Bar:\n    pass\n")
        terms = [
            Term(
                name="Bar",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x",
                code_anchor="src/foo.py:Bar",
            )
        ]
        unresolved = lint_anchor_resolution(terms, src)
        assert unresolved == []

    def test_reports_unresolved(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        terms = [
            Term(
                name="Ghost",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x",
                code_anchor="src/ghost.py:Ghost",
            )
        ]
        unresolved = lint_anchor_resolution(terms, src)
        assert unresolved == ["Ghost -> src/ghost.py:Ghost"]
