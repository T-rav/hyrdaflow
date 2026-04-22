"""Tests for ADR runtime indexer."""

from __future__ import annotations

from pathlib import Path

from adr_index import (
    ADR,
    parse_adr_file,
    render_full,
    render_titles_only,
    scan_adr_directory,
)


def _write_adr(path: Path, number: int, title: str, status: str, context: str) -> Path:
    p = path / f"{number:04d}-{title.lower().replace(' ', '-')}.md"
    p.write_text(
        f"# ADR-{number:04d}: {title}\n\n"
        f"**Status:** {status}\n"
        f"**Date:** 2026-01-01\n\n"
        f"## Context\n\n{context}\n"
    )
    return p


def test_parse_adr_file_extracts_number_title_status(tmp_path):
    p = _write_adr(tmp_path, 1, "Async Loops", "Accepted", "We run five loops.")
    adr = parse_adr_file(p)
    assert adr.number == 1
    assert adr.title == "Async Loops"
    assert adr.status == "Accepted"
    assert "five loops" in adr.summary


def test_parse_adr_file_status_is_normalized(tmp_path):
    p = _write_adr(tmp_path, 7, "Old Thing", "Superseded by ADR-0021", "old.")
    adr = parse_adr_file(p)
    # Normalize to bucket: "Accepted" | "Proposed" | "Superseded"
    assert adr.status == "Superseded"
    assert adr.superseded_by == "ADR-0021"


def test_parse_adr_file_handles_missing_context_section(tmp_path):
    p = tmp_path / "0099-empty.md"
    p.write_text("# ADR-0099: Empty\n\n**Status:** Proposed\n")
    adr = parse_adr_file(p)
    assert adr.number == 99
    assert adr.summary == ""


def test_scan_adr_directory_sorts_by_number_and_filters_non_adr(tmp_path):
    _write_adr(tmp_path, 3, "C", "Accepted", "c.")
    _write_adr(tmp_path, 1, "A", "Accepted", "a.")
    _write_adr(tmp_path, 2, "B", "Proposed", "b.")
    # A distractor: README, not an ADR
    (tmp_path / "README.md").write_text("# README\n\nnot an ADR\n")

    adrs = scan_adr_directory(tmp_path)
    assert [a.number for a in adrs] == [1, 2, 3]


def test_scan_adr_directory_missing_returns_empty(tmp_path):
    nonexistent = tmp_path / "nope"
    assert scan_adr_directory(nonexistent) == []


def test_render_full_groups_by_status(tmp_path):
    adrs = [
        ADR(number=1, title="A", status="Accepted", summary="a."),
        ADR(number=2, title="B", status="Proposed", summary="b."),
        ADR(
            number=7,
            title="Old",
            status="Superseded",
            summary="old.",
            superseded_by="ADR-0021",
        ),
    ]
    out = render_full(adrs)
    assert "## Accepted (load-bearing)" in out
    assert "## Proposed (drafted, not yet accepted)" in out
    assert "## Superseded" in out
    assert "ADR-0001 A — a." in out
    assert "ADR-0007" in out and "superseded by ADR-0021" in out


def test_render_full_empty_input_returns_empty():
    assert render_full([]) == ""


def test_render_titles_only_excludes_summaries_and_superseded():
    adrs = [
        ADR(number=1, title="A", status="Accepted", summary="long summary here"),
        ADR(
            number=7,
            title="Old",
            status="Superseded",
            summary="old.",
            superseded_by="ADR-0021",
        ),
    ]
    out = render_titles_only(adrs)
    assert "ADR-0001 A" in out
    assert "long summary" not in out
    # Titles-only skips Superseded entries to avoid noise in implement/review
    assert "ADR-0007" not in out


def test_render_titles_only_empty_input_returns_empty():
    assert render_titles_only([]) == ""
