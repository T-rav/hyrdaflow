"""Tests for ADR → source file inverse indexing (P2 wiki-evolution audit).

The validator/CI gate uses this to answer: "if a PR touches file X,
which Accepted ADRs cite X and might need updating?".
"""

from __future__ import annotations

from pathlib import Path

from adr_index import ADR, ADRIndex


def _write_adr(
    adr_dir: Path,
    number: int,
    title: str,
    citations: list[str],
    *,
    status: str = "Accepted",
) -> Path:
    """Write a minimal ADR file with `src/path:Symbol`-style citations."""
    adr_dir.mkdir(parents=True, exist_ok=True)
    path = adr_dir / f"{number:04d}-{title.lower().replace(' ', '-')}.md"
    citation_lines = "\n".join(f"- `{c}`" for c in citations)
    path.write_text(
        f"# ADR-{number:04d}: {title}\n\n"
        f"**Status:** {status}\n"
        f"**Date:** 2026-04-24\n\n"
        f"## Context\n\nTest fixture.\n\n"
        f"## Decision\n\nDo the thing.\n\n"
        f"### Related\n\n{citation_lines}\n"
    )
    return path


def test_parse_adr_extracts_source_files(tmp_path: Path) -> None:
    """An ADR parsed from disk carries the set of `src/...` files it cites."""
    _write_adr(
        tmp_path,
        32,
        "Per-Repo Wiki",
        citations=[
            "src/repo_wiki.py:RepoWikiStore",
            "src/wiki_compiler.py:WikiCompiler",
        ],
    )
    idx = ADRIndex(tmp_path)

    adrs = idx.adrs()
    adr = next(a for a in adrs if a.number == 32)

    assert "src/repo_wiki.py" in adr.source_files
    assert "src/wiki_compiler.py" in adr.source_files


def test_adrs_touching_returns_file_to_adrs_map(tmp_path: Path) -> None:
    """adrs_touching() returns {file: [ADRs citing it]} for the given paths."""
    _write_adr(tmp_path, 1, "A", ["src/foo.py:Foo"])
    _write_adr(tmp_path, 2, "B", ["src/foo.py:Bar", "src/bar.py:Baz"])
    _write_adr(tmp_path, 3, "C", ["src/bar.py:Qux"])
    idx = ADRIndex(tmp_path)

    touched = idx.adrs_touching(["src/foo.py", "src/unrelated.py"])

    assert set(touched.keys()) == {"src/foo.py"}
    numbers = {a.number for a in touched["src/foo.py"]}
    assert numbers == {1, 2}


def test_adrs_touching_skips_non_accepted(tmp_path: Path) -> None:
    """Superseded / Deprecated / Proposed ADRs don't trigger the gate."""
    _write_adr(tmp_path, 10, "Old", ["src/foo.py:X"], status="Superseded")
    _write_adr(tmp_path, 11, "Live", ["src/foo.py:Y"], status="Accepted")
    idx = ADRIndex(tmp_path)

    touched = idx.adrs_touching(["src/foo.py"])

    numbers = {a.number for a in touched["src/foo.py"]}
    assert numbers == {11}


def test_adrs_touching_empty_input_returns_empty(tmp_path: Path) -> None:
    _write_adr(tmp_path, 1, "A", ["src/foo.py:X"])
    idx = ADRIndex(tmp_path)

    assert idx.adrs_touching([]) == {}
    assert idx.adrs_touching(["src/unrelated.py"]) == {}


def test_source_files_ignores_non_src_citations(tmp_path: Path) -> None:
    """Only `src/...` citations count — tests/, docs/, scripts/ don't."""
    _write_adr(
        tmp_path,
        1,
        "Mixed",
        citations=[
            "src/foo.py:Foo",
            "tests/test_foo.py",  # not matched by _SOURCE_SYMBOL_RE
            "docs/adr/0001.md",
        ],
    )
    idx = ADRIndex(tmp_path)

    adr: ADR = next(a for a in idx.adrs() if a.number == 1)
    assert adr.source_files == frozenset({"src/foo.py"})
