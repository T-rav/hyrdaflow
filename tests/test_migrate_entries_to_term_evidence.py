"""Tests for the entry→term evidence migration script."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make scripts/ importable
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
from migrate_entries_to_term_evidence import (  # noqa: E402
    EntryReference,
    match_entry,
    run_migration,
)

from ubiquitous_language import (  # noqa: E402
    BoundedContext,
    Term,
    TermKind,
    TermStore,
)


class FakeLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    async def complete_structured(self, *, prompt, schema):
        self.calls.append(prompt)
        return self.responses.pop(0) if self.responses else {"term_ids": []}


def _make_term(name: str, term_id: str, evidence=None) -> Term:
    return Term(
        id=term_id,
        name=name,
        kind=TermKind.SERVICE,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition=f"{name} is a test term used in the migrator's fixture corpus.",
        code_anchor=f"src/{name.lower()}.py:{name}",
        confidence="accepted",
        evidence=evidence or [],
    )


class TestMatchEntry:
    @pytest.mark.asyncio
    async def test_returns_validated_references(self) -> None:
        llm = FakeLLM([{"term_ids": ["01H_T1", "01H_T2"]}])
        refs = await match_entry(
            llm=llm,
            entry_id="01H_E1",
            entry_text="entry text",
            terms=[_make_term("Alpha", "01H_T1"), _make_term("Bravo", "01H_T2")],
            valid_term_ids={"01H_T1", "01H_T2"},
        )
        assert len(refs) == 2
        assert refs[0].entry_id == "01H_E1"
        assert {r.term_id for r in refs} == {"01H_T1", "01H_T2"}

    @pytest.mark.asyncio
    async def test_filters_invalid_ids(self) -> None:
        llm = FakeLLM([{"term_ids": ["01H_T1", "01H_BOGUS"]}])
        refs = await match_entry(
            llm=llm,
            entry_id="01H_E1",
            entry_text="x",
            terms=[_make_term("A", "01H_T1")],
            valid_term_ids={"01H_T1"},
        )
        assert {r.term_id for r in refs} == {"01H_T1"}

    @pytest.mark.asyncio
    async def test_empty_term_ids_returns_no_refs(self) -> None:
        llm = FakeLLM([{"term_ids": []}])
        refs = await match_entry(
            llm=llm,
            entry_id="01H_E1",
            entry_text="x",
            terms=[_make_term("A", "01H_T1")],
            valid_term_ids={"01H_T1"},
        )
        assert refs == []

    @pytest.mark.asyncio
    async def test_llm_failure_skips_entry(self) -> None:
        class FailingLLM:
            async def complete_structured(self, *, prompt, schema):
                raise RuntimeError("boom")

        refs = await match_entry(
            llm=FailingLLM(),
            entry_id="01H_E1",
            entry_text="x",
            terms=[_make_term("A", "01H_T1")],
            valid_term_ids={"01H_T1"},
        )
        assert refs == []


class TestRunMigration:
    @pytest.mark.asyncio
    async def test_idempotent_set_difference(self, tmp_path: Path) -> None:
        # Term with evidence already containing entry-id
        terms_dir = tmp_path / "docs" / "wiki" / "terms"
        terms_dir.mkdir(parents=True)
        store = TermStore(terms_dir)
        store.write(_make_term("Alpha", "01H_T1", evidence=["01H_E1"]))

        # Topic file with one entry
        wiki_root = tmp_path / "docs" / "wiki"
        topic_path = wiki_root / "patterns.md"
        topic_path.write_text(
            "# Patterns\n\n## A pattern\n\nSome content.\n\n"
            "```json:entry\n"
            '{"id":"01H_E1","title":"A pattern","topic":null,"source_type":"manual",'
            '"source_issue":null,"source_repo":null,"created_at":"2026-01-01T00:00:00+00:00",'
            '"updated_at":"2026-01-01T00:00:00+00:00","valid_to":null,"superseded_by":null,'
            '"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}'
            "\n```\n"
        )

        # LLM returns the same term_id; should be deduped
        llm = FakeLLM([{"term_ids": ["01H_T1"]}])
        stats = await run_migration(repo_root=tmp_path, llm=llm, dry_run=False)
        assert stats["terms_written"] == 0  # already had this evidence — idempotent
        assert stats["edges_added"] == 0


def test_entry_reference_is_a_frozen_dataclass() -> None:
    """Smoke check on the dataclass shape — keeps the import surface honest."""
    ref = EntryReference(entry_id="01H_E1", term_id="01H_T1")
    assert ref.entry_id == "01H_E1"
    assert ref.term_id == "01H_T1"
