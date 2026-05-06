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
    build_import_graph,
    build_symbol_index,
    detect_candidates,
    dump_term_file,
    lint_anchor_resolution,
    lint_paraphrases,
    lint_reverse_coverage,
    load_term_file,
    render_context_map,
    render_glossary,
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


class TestParaphraseLint:
    def test_clean_when_canonical_only(self, tmp_path: Path) -> None:
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "patterns.md").write_text("Use RepoWikiStore directly.")
        terms = [
            Term(
                name="RepoWikiStore",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x",
                code_anchor="src/repo_wiki.py:RepoWikiStore",
                aliases=["repo wiki store"],
            )
        ]
        violations = lint_paraphrases(terms, wiki)
        assert violations == []

    def test_flags_alias_usage(self, tmp_path: Path) -> None:
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "patterns.md").write_text("The repo wiki store handles ingest.")
        terms = [
            Term(
                name="RepoWikiStore",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x",
                code_anchor="src/repo_wiki.py:RepoWikiStore",
                aliases=["repo wiki store"],
            )
        ]
        violations = lint_paraphrases(terms, wiki)
        assert len(violations) == 1
        assert "repo wiki store" in violations[0]
        assert "patterns.md" in violations[0]

    def test_ignores_aliases_inside_term_files_themselves(self, tmp_path: Path) -> None:
        """Term files DEFINE aliases — they aren't paraphrase violations."""
        wiki = tmp_path / "wiki"
        terms_dir = wiki / "terms"
        terms_dir.mkdir(parents=True)
        (terms_dir / "repo-wiki-store.md").write_text(
            "frontmatter naming the alias 'repo wiki store' is fine"
        )
        (wiki / "patterns.md").write_text("Use RepoWikiStore.")  # canonical
        terms = [
            Term(
                name="RepoWikiStore",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x",
                code_anchor="src/repo_wiki.py:RepoWikiStore",
                aliases=["repo wiki store"],
            )
        ]
        violations = lint_paraphrases(terms, wiki)
        assert violations == []


class TestReverseCoverageLint:
    def test_reports_uncovered_load_bearing_classes(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text(
            "class FooLoop:\n    pass\nclass HelperUtil:\n    pass\n"
        )
        (src / "b.py").write_text("class BarRunner:\n    pass\n")
        terms = [
            Term(
                name="FooLoop",
                kind=TermKind.LOOP,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x",
                code_anchor="src/a.py:FooLoop",
            )
        ]
        uncovered = lint_reverse_coverage(terms, src)
        # FooLoop covered; HelperUtil isn't load-bearing; BarRunner is uncovered
        assert uncovered == ["src/b.py:BarRunner"]

    def test_returns_empty_when_full_coverage(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("class Helper:\n    pass\n")
        terms: list[Term] = []
        assert lint_reverse_coverage(terms, src) == []


class TestGlossaryRender:
    def test_renders_alphabetical_with_header(self) -> None:
        terms = [
            Term(
                name="ZebraPort",
                kind=TermKind.PORT,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="zzz",
                code_anchor="src/z.py:ZebraPort",
            ),
            Term(
                name="AlphaLoop",
                kind=TermKind.LOOP,
                bounded_context=BoundedContext.BUILDER,
                definition="aaa",
                code_anchor="src/a.py:AlphaLoop",
            ),
        ]
        out = render_glossary(terms)
        assert out.startswith("<!-- DO NOT EDIT")
        # Alphabetical order
        assert out.index("AlphaLoop") < out.index("ZebraPort")
        assert "src/a.py:AlphaLoop" in out
        assert "builder" in out


class TestContextMapRender:
    def test_groups_by_context_and_emits_edges(self) -> None:
        terms = [
            Term(
                id="01HX01",
                name="EventBus",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x",
                code_anchor="src/event_bus.py:EventBus",
                related=[TermRel(kind=TermRelKind.CONSUMES, target="01HX02")],
            ),
            Term(
                id="01HX02",
                name="AgentRunner",
                kind=TermKind.RUNNER,
                bounded_context=BoundedContext.BUILDER,
                definition="x",
                code_anchor="src/agent.py:AgentRunner",
            ),
        ]
        out = render_context_map(terms)
        assert "```mermaid" in out
        assert "subgraph shared-kernel" in out
        assert "subgraph builder" in out
        # Edge label encodes the rel kind
        assert "consumes" in out


class TestTermProvenance:
    def test_provenance_fields_default_none(self) -> None:
        term = Term(
            name="X",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="A test term used in unit tests for provenance defaults.",
            code_anchor="src/x.py:X",
        )
        assert term.proposed_by is None
        assert term.proposed_at is None
        assert term.proposal_signals is None
        assert term.proposal_imports_seen is None

    def test_provenance_round_trip_through_disk(self, tmp_path: Path) -> None:
        original = Term(
            name="FooLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="A test loop term used in unit tests for provenance round-trip.",
            code_anchor="src/foo.py:FooLoop",
            proposed_by="TermProposerLoop",
            proposed_at="2026-05-08T12:00:00+00:00",
            proposal_signals=["S1", "S2"],
            proposal_imports_seen=3,
        )
        path = tmp_path / "foo-loop.md"
        dump_term_file(path, original)
        loaded = load_term_file(path)
        assert loaded.proposed_by == "TermProposerLoop"
        assert loaded.proposed_at == "2026-05-08T12:00:00+00:00"
        assert loaded.proposal_signals == ["S1", "S2"]
        assert loaded.proposal_imports_seen == 3

    def test_hand_authored_term_loads_without_provenance(self, tmp_path: Path) -> None:
        """Existing seed-term files have no provenance; they must still load."""
        path = tmp_path / "hand-authored.md"
        path.write_text(
            "---\n"
            'id: "01HX01"\n'
            'name: "HandAuthored"\n'
            'kind: "service"\n'
            'bounded_context: "shared-kernel"\n'
            'code_anchor: "src/x.py:HandAuthored"\n'
            "aliases: []\n"
            "related: []\n"
            "evidence: []\n"
            "superseded_by: null\n"
            "superseded_reason: null\n"
            'confidence: "accepted"\n'
            'created_at: "2026-05-04T00:00:00+00:00"\n'
            'updated_at: "2026-05-04T00:00:00+00:00"\n'
            "---\n\n## Definition\n\nA hand-authored term loaded as a smoke check.\n"
        )
        loaded = load_term_file(path)
        assert loaded.proposed_by is None
        assert loaded.proposal_signals is None


class TestImportGraph:
    def test_finds_imports_from_python_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.py").write_text(
            "from bar import Bar\nfrom baz import Baz, Qux\n\nclass Foo:\n    pass\n"
        )
        (src / "bar.py").write_text("class Bar:\n    pass\n")
        (src / "baz.py").write_text("class Baz:\n    pass\nclass Qux:\n    pass\n")
        graph = build_import_graph(src)
        assert graph["src/foo.py"] == {"Bar", "Baz", "Qux"}
        assert graph["src/bar.py"] == set()
        assert graph["src/baz.py"] == set()

    def test_handles_relative_imports(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        pkg = src / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "child.py").write_text(
            "from .sibling import Sibling\n\nclass Child:\n    pass\n"
        )
        (pkg / "sibling.py").write_text("class Sibling:\n    pass\n")
        graph = build_import_graph(src)
        assert "Sibling" in graph["src/pkg/child.py"]

    def test_skips_unparseable_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "good.py").write_text("from x import Y\n")
        (src / "broken.py").write_text("def : :\n")  # syntax error
        graph = build_import_graph(src)
        assert graph["src/good.py"] == {"Y"}
        assert "src/broken.py" not in graph


class TestCandidateDetection:
    def test_s1_finds_load_bearing_suffix_classes(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("class FooLoop:\n    pass\nclass Helper:\n    pass\n")
        (src / "b.py").write_text(
            "class BarRunner:\n    pass\nclass BazPort:\n    pass\n"
        )
        index = build_symbol_index(src)
        graph = build_import_graph(src)
        candidates = detect_candidates(index, graph, terms=[])
        names = {c.name for c in candidates}
        assert names == {"FooLoop", "BarRunner", "BazPort"}

    def test_s2_finds_imported_by_term_anchors(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "term_class.py").write_text(
            "from helper import HelperService\n\nclass MyLoop:\n    pass\n"
        )
        (src / "helper.py").write_text("class HelperService:\n    pass\n")
        index = build_symbol_index(src)
        graph = build_import_graph(src)
        my_loop_term = Term(
            name="MyLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="A test term anchoring src/term_class.py for the S2 detection test.",
            code_anchor="src/term_class.py:MyLoop",
        )
        candidates = detect_candidates(index, graph, terms=[my_loop_term])
        names = {c.name for c in candidates}
        assert "HelperService" in names
        assert "MyLoop" not in names

    def test_s5_ranks_by_in_degree(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("from helper import Helper\nclass ALoop:\n    pass\n")
        (src / "b.py").write_text("from helper import Helper\nclass BLoop:\n    pass\n")
        (src / "c.py").write_text(
            "from other_helper import OtherHelper\nclass CLoop:\n    pass\n"
        )
        (src / "helper.py").write_text("class Helper:\n    pass\n")
        (src / "other_helper.py").write_text("class OtherHelper:\n    pass\n")
        index = build_symbol_index(src)
        graph = build_import_graph(src)
        terms = [
            Term(
                name=n,
                kind=TermKind.LOOP,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x" * 30,
                code_anchor=anchor,
            )
            for n, anchor in [
                ("ALoop", "src/a.py:ALoop"),
                ("BLoop", "src/b.py:BLoop"),
                ("CLoop", "src/c.py:CLoop"),
            ]
        ]
        candidates = detect_candidates(index, graph, terms=terms)
        helper = next(c for c in candidates if c.name == "Helper")
        other = next(c for c in candidates if c.name == "OtherHelper")
        assert helper.imports_seen == 2
        assert other.imports_seen == 1
        names_in_order = [c.name for c in candidates]
        assert names_in_order.index("Helper") < names_in_order.index("OtherHelper")

    def test_excludes_already_covered_classes(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("class FooLoop:\n    pass\n")
        index = build_symbol_index(src)
        graph = build_import_graph(src)
        covered_term = Term(
            name="FooLoop",
            kind=TermKind.LOOP,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="An already-covered loop used to verify detection excludes it.",
            code_anchor="src/a.py:FooLoop",
        )
        candidates = detect_candidates(index, graph, terms=[covered_term])
        assert candidates == []

    def test_candidate_carries_signals_and_anchor(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("class FooLoop:\n    pass\n")
        index = build_symbol_index(src)
        graph = build_import_graph(src)
        candidates = detect_candidates(index, graph, terms=[])
        assert len(candidates) == 1
        c = candidates[0]
        assert c.name == "FooLoop"
        assert c.code_anchor == "src/a.py:FooLoop"
        assert "S1" in c.signals
