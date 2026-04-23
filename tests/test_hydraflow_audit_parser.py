"""Tests for scripts.hydraflow_audit.parser."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.hydraflow_audit.models import Severity
from scripts.hydraflow_audit.parser import _parse_text, parse_adr


def test_extracts_rows_under_principle_heading() -> None:
    text = """
### P1. Documentation Contract

Some prose.

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P1.1 | STRUCTURAL | CLAUDE.md | CLAUDE.md exists | touch CLAUDE.md |
"""
    specs = _parse_text(text)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.check_id == "P1.1"
    assert spec.principle == "P1"
    assert spec.severity is Severity.STRUCTURAL
    assert spec.source == "CLAUDE.md"
    assert spec.what == "CLAUDE.md exists"
    assert spec.remediation == "touch CLAUDE.md"


def test_supports_sub_lettered_check_ids() -> None:
    text = """
### P2. Layers

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P2.2a | STRUCTURAL | docs | a port exists per boundary | add a Protocol |
"""
    specs = _parse_text(text)
    assert [s.check_id for s in specs] == ["P2.2a"]


def test_skips_alignment_row_between_header_and_data() -> None:
    text = """
### P1. Docs

| check_id | type | source | what | remediation |
|:---|:---:|---|---|---|
| P1.1 | CULTURAL | x | y | z |
"""
    specs = _parse_text(text)
    assert len(specs) == 1
    assert specs[0].severity is Severity.CULTURAL


def test_requires_five_columns() -> None:
    text = """
### P1. Docs

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P1.1 | STRUCTURAL | only | four | columns-has-five-but-this-one-has-four |
| P1.2 | STRUCTURAL | three | cols |
"""
    specs = _parse_text(text)
    assert [s.check_id for s in specs] == ["P1.1"]


def test_rejects_unknown_severity() -> None:
    text = """
### P1. Docs

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P1.1 | MYSTERY | x | y | z |
"""
    assert _parse_text(text) == []


def test_does_not_emit_rows_without_a_principle_heading() -> None:
    text = """
| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P1.1 | STRUCTURAL | x | y | z |
"""
    assert _parse_text(text) == []


def test_handles_multiple_principles() -> None:
    text = """
### P1. Docs

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P1.1 | STRUCTURAL | a | b | c |

Prose between tables.

### P2. Arch

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P2.1 | BEHAVIORAL | d | e | f |
"""
    specs = _parse_text(text)
    assert [(s.principle, s.check_id) for s in specs] == [
        ("P1", "P1.1"),
        ("P2", "P2.1"),
    ]


def test_parses_the_real_adr_0044_with_many_rows() -> None:
    adr = Path(__file__).parents[1] / "docs" / "adr" / "0044-hydraflow-principles.md"
    specs = parse_adr(adr)
    # ADR-0044 currently defines ~94 rows across 10 principles; assert a floor so
    # accidental deletions get caught without being brittle about exact count.
    assert len(specs) >= 80
    principles = {s.principle for s in specs}
    assert principles == {f"P{i}" for i in range(1, 11)}
    # Every row has non-empty content.
    for spec in specs:
        assert spec.check_id
        assert spec.source
        assert spec.what
        assert spec.remediation


@pytest.mark.parametrize(
    "severity",
    [Severity.STRUCTURAL, Severity.BEHAVIORAL, Severity.CULTURAL],
)
def test_severity_round_trip(severity: Severity) -> None:
    text = f"""
### P1. Docs

| check_id | type | source | what | remediation |
|---|---|---|---|---|
| P1.1 | {severity.value} | x | y | z |
"""
    specs = _parse_text(text)
    assert len(specs) == 1
    assert specs[0].severity is severity
