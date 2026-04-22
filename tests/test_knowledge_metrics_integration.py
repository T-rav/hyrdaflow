"""Integration tests: each counter fires from its real call site."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from knowledge_metrics import metrics
from repo_wiki import RepoWikiStore, WikiEntry


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.reset()
    yield
    metrics.reset()


async def test_wiki_entries_ingested_increments_on_ingest(tmp_path):
    from repo_wiki_ingest import ingest_phase_output
    from wiki_compiler import ContradictionCheck

    store = RepoWikiStore(tmp_path / "wiki")
    compiler = AsyncMock()
    compiler.detect_contradictions = AsyncMock(return_value=ContradictionCheck())

    entries = [
        WikiEntry(title="x", content="y", source_type="plan", topic="patterns"),
        WikiEntry(title="z", content="w", source_type="plan", topic="patterns"),
    ]
    await ingest_phase_output(
        store=store,
        repo="acme/widget",
        entries=entries,
        compiler=compiler,
    )
    assert metrics.snapshot()["wiki_entries_ingested"] == 2


async def test_wiki_supersedes_increments(tmp_path):
    from repo_wiki_ingest import ingest_phase_output
    from wiki_compiler import ContradictedEntry, ContradictionCheck

    store = RepoWikiStore(tmp_path / "wiki")

    a = WikiEntry(
        id="01HQ0000000000000000000000",
        title="A",
        content="a",
        source_type="plan",
        topic="patterns",
    )
    compiler = AsyncMock()
    compiler.detect_contradictions = AsyncMock(return_value=ContradictionCheck())
    await ingest_phase_output(
        store=store,
        repo="acme/widget",
        entries=[a],
        compiler=compiler,
    )

    # EventBus stub is required because _emit_wiki_supersedes expects one.
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()

    b = WikiEntry(
        id="01HQ1111111111111111111111",
        title="B",
        content="b",
        source_type="plan",
        topic="patterns",
    )
    compiler.detect_contradictions = AsyncMock(
        return_value=ContradictionCheck(
            contradicts=[ContradictedEntry(id=a.id, reason="replaces")]
        )
    )
    await ingest_phase_output(
        store=store,
        repo="acme/widget",
        entries=[b],
        compiler=compiler,
        event_bus=event_bus,
    )
    assert metrics.snapshot()["wiki_supersedes"] == 1


async def test_tribal_promotions_increments(tmp_path):
    from repo_wiki_loop import run_generalization_pass
    from tribal_wiki import TribalWikiStore
    from wiki_compiler import GeneralizationCheck

    per_repo = RepoWikiStore(tmp_path / "per")
    tribal = TribalWikiStore(tmp_path / "tribal")
    per_repo.ingest(
        "acme/a",
        [
            WikiEntry(
                id="01HQA00000000000000000000A",
                title="P",
                content="Testing: same idea.",
                source_type="plan",
                topic="testing",
                source_repo="acme/a",
            )
        ],
    )
    per_repo.ingest(
        "other/b",
        [
            WikiEntry(
                id="01HQB00000000000000000000B",
                title="Q",
                content="Testing: also the same idea.",
                source_type="plan",
                topic="testing",
                source_repo="other/b",
            )
        ],
    )
    compiler = MagicMock()
    compiler.generalize_pair = AsyncMock(
        return_value=GeneralizationCheck(
            same_principle=True,
            generalized_title="T",
            generalized_body="TB.",
            confidence="high",
        )
    )
    await run_generalization_pass(
        per_repo=per_repo,
        tribal=tribal,
        compiler=compiler,
    )
    assert metrics.snapshot()["tribal_promotions"] >= 1


async def test_adr_drafts_judged_increments(tmp_path):
    from tribal_wiki import TribalWikiStore
    from wiki_compiler import WikiCompiler

    tribal = TribalWikiStore(tmp_path / "tribal")
    tribal.ingest(
        [
            WikiEntry(
                id="01HQ0000000000000000000000",
                title="p",
                content="p",
                source_type="librarian",
                topic="patterns",
            )
        ]
    )
    compiler = WikiCompiler.__new__(WikiCompiler)
    compiler._call_model = AsyncMock(
        return_value=('{"architectural": false, "load_bearing": false, "reason": "x"}')
    )
    await compiler.judge_adr_draft(
        suggestion={
            "title": "x",
            "context": "y",
            "decision": "z",
            "consequences": "w",
            "evidence_issues": [1, 2],
            "evidence_wiki_entries": ["01HQ0000000000000000000000"],
        },
        tribal=tribal,
    )
    assert metrics.snapshot()["adr_drafts_judged"] == 1


async def test_adr_drafts_opened_increments():
    from adr_draft_opener import open_adr_draft_issue
    from wiki_compiler import ADRDraftDecision

    gh = AsyncMock()
    gh.create_issue = AsyncMock(return_value={"number": 99})
    decision = ADRDraftDecision(
        two_plus_issues=True,
        in_tribal=True,
        architectural=True,
        load_bearing=True,
        draft_ok=True,
    )
    await open_adr_draft_issue(
        suggestion={"title": "x"},
        decision=decision,
        gh_client=gh,
    )
    assert metrics.snapshot()["adr_drafts_opened"] == 1


async def test_reflections_bridged_increments(tmp_path):
    from post_merge_handler import _bridge_reflections_to_wiki
    from reflections import append_reflection
    from wiki_compiler import ContradictionCheck

    cfg = MagicMock()
    cfg.data_root = tmp_path

    store = RepoWikiStore(tmp_path / "wiki")
    compiler = AsyncMock()
    compiler.detect_contradictions = AsyncMock(return_value=ContradictionCheck())
    append_reflection(cfg, 42, phase="plan", content="architecture: insight.")

    await _bridge_reflections_to_wiki(
        config=cfg,
        issue_number=42,
        repo="acme/widget",
        store=store,
        compiler=compiler,
    )
    assert metrics.snapshot()["reflections_bridged"] == 1
