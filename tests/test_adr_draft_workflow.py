"""Tests for agent-drafted ADR workflow."""

from __future__ import annotations

from wiki_compiler import parse_adr_draft_suggestion


def test_parse_adr_draft_suggestion_basic():
    transcript = """Implementing the feature now.

ADR_DRAFT_SUGGESTION:
title: Always use Pydantic BaseModel for configs
context: Multiple issues (#123, #456) have shown that config classes written as
  dataclasses drift from the validation we get from Pydantic.
decision: Require config classes to subclass BaseModel.
consequences: Slightly more boilerplate; catches validation bugs at construction.
evidence:
  - issue: 123
  - issue: 456
  - wiki_entry: 01HQ0000000000000000000000
"""
    parsed = parse_adr_draft_suggestion(transcript)
    assert parsed is not None
    assert parsed["title"] == "Always use Pydantic BaseModel for configs"
    assert "dataclasses" in parsed["context"]
    assert parsed["evidence_issues"] == [123, 456]
    assert parsed["evidence_wiki_entries"] == ["01HQ0000000000000000000000"]


def test_parse_adr_draft_suggestion_returns_none_when_absent():
    assert parse_adr_draft_suggestion("no suggestion block here") is None


def test_parse_adr_draft_suggestion_tolerates_missing_evidence():
    transcript = """ADR_DRAFT_SUGGESTION:
title: X
context: Y
decision: Z
consequences: W
"""
    parsed = parse_adr_draft_suggestion(transcript)
    assert parsed is not None
    assert parsed["evidence_issues"] == []
