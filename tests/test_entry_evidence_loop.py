"""Unit tests for EntryEvidenceLoop (ADR-0062)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from entry_evidence_loop import (
    ENTRY_EVIDENCE_PR_LABEL,
    EntryEvidenceLoop,
)
from events import EventBus
from state import StateTracker
from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermStore,
)


def _seed_terms(tmp_path: Path) -> list[Term]:
    terms_root = tmp_path / "docs" / "wiki" / "terms"
    store = TermStore(terms_root)
    a = Term(
        id="01EVTBUS0000000000000",
        name="EventBus",
        kind=TermKind.SERVICE,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition="Async pub/sub bus.",
        code_anchor="src/events.py:EventBus",
        confidence="accepted",
    )
    store.write(a)
    b = Term(
        id="01STATETR000000000000",
        name="StateTracker",
        kind=TermKind.SERVICE,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition="Persistence.",
        code_anchor="src/state.py:StateTracker",
        confidence="accepted",
    )
    store.write(b)
    return [a, b]


def _entry_block(*, eid: str, title: str, prose: str) -> str:
    """Render a wiki-entry block in the topic-page schema RepoWikiStore parses."""
    import json as _json

    meta = {
        "id": eid,
        "title": title,
        "source_type": "manual",
        "valid_from": "2026-01-01T00:00:00Z",
    }
    return f"## {title}\n\n{prose}\n\n```json:entry\n{_json.dumps(meta)}\n```\n\n"


def _seed_wiki(tmp_path: Path, *, with_orphan: bool = True) -> None:
    """Write a docs/wiki/{topic}.md tree with at least one entry."""
    wiki_root = tmp_path / "docs" / "wiki"
    (wiki_root / "terms").mkdir(parents=True, exist_ok=True)
    (wiki_root / "architecture.md").write_text(
        "# Architecture\n\n"
        + _entry_block(
            eid="ev-001",
            title="AgentRunner overview",
            prose=(
                "The AgentRunner uses the EventBus for status updates and the\n"
                "StateTracker for persistence."
            ),
        )
    )
    if with_orphan:
        (wiki_root / "gotchas.md").write_text(
            "# Gotchas\n\n"
            + _entry_block(
                eid="ev-002",
                title="Unrelated gotcha",
                prose="Something completely unrelated to any term.",
            )
        )


def _make_deps(tmp_path: Path) -> LoopDeps:
    import asyncio

    _ = StateTracker(tmp_path / "state.json")  # not used by _do_work directly
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *_a, **_kw: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def llm_match_only_eventbus():
    """LLM matches ev-001 → EventBus, refuses ev-002."""
    mock = AsyncMock()

    async def fake(prompt: str, schema):
        if "AgentRunner overview" in prompt:
            return {"term_ids": ["01EVTBUS0000000000000"]}
        return {"term_ids": []}

    mock.complete_structured.side_effect = fake
    return mock


@pytest.fixture
def pr_port_capturing():
    mock = AsyncMock()
    mock.open_bot_pr = AsyncMock(return_value=42)
    return mock


class TestEntryEvidenceLoop:
    @pytest.mark.asyncio
    async def test_disabled_returns_disabled_status(
        self,
        tmp_path: Path,
        llm_match_only_eventbus,
        pr_port_capturing,
    ) -> None:
        _seed_terms(tmp_path)
        config = HydraFlowConfig(repo_root=tmp_path, entry_evidence_enabled=False)
        loop = EntryEvidenceLoop(
            config=config,
            deps=_make_deps(tmp_path),
            llm=llm_match_only_eventbus,
            pr_port=pr_port_capturing,
            repo_root=tmp_path,
            dedup_path=tmp_path / "dedup.json",
        )
        result = await loop._do_work()  # noqa: SLF001 — exercising the loop body
        assert result == {"status": "disabled"}
        pr_port_capturing.open_bot_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_terms_returns_ok_zero_with_no_pr(
        self,
        tmp_path: Path,
        llm_match_only_eventbus,
        pr_port_capturing,
    ) -> None:
        # Terms root is empty.
        (tmp_path / "docs" / "wiki" / "terms").mkdir(parents=True)
        config = HydraFlowConfig(repo_root=tmp_path)
        loop = EntryEvidenceLoop(
            config=config,
            deps=_make_deps(tmp_path),
            llm=llm_match_only_eventbus,
            pr_port=pr_port_capturing,
            repo_root=tmp_path,
            dedup_path=tmp_path / "dedup.json",
        )
        result = await loop._do_work()  # noqa: SLF001
        assert result["status"] == "ok"
        assert result["opened_pr"] is False
        pr_port_capturing.open_bot_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_links_matched_entries_and_opens_pr(
        self,
        tmp_path: Path,
        llm_match_only_eventbus,
        pr_port_capturing,
    ) -> None:
        _seed_terms(tmp_path)
        _seed_wiki(tmp_path)
        config = HydraFlowConfig(repo_root=tmp_path)
        loop = EntryEvidenceLoop(
            config=config,
            deps=_make_deps(tmp_path),
            llm=llm_match_only_eventbus,
            pr_port=pr_port_capturing,
            repo_root=tmp_path,
            dedup_path=tmp_path / "dedup.json",
        )

        result = await loop._do_work()  # noqa: SLF001

        assert result["status"] == "ok"
        assert result["matched_entries"] == 1
        assert result["terms_touched"] == 1
        assert result["opened_pr"] is True

        # PR opened with the right label + a file under docs/wiki/terms/.
        pr_port_capturing.open_bot_pr.assert_awaited_once()
        _, kwargs = pr_port_capturing.open_bot_pr.call_args
        assert kwargs["labels"] == [ENTRY_EVIDENCE_PR_LABEL]
        assert any(p.startswith("docs/wiki/terms/") for p in kwargs["files"])
        # The rendered file should include the new evidence backlink.
        rendered = next(iter(kwargs["files"].values()))
        assert "ev-001" in rendered

    @pytest.mark.asyncio
    async def test_already_linked_entries_are_skipped_idempotent(
        self,
        tmp_path: Path,
        llm_match_only_eventbus,
        pr_port_capturing,
    ) -> None:
        # Seed terms with EventBus already referencing ev-001.
        terms_root = tmp_path / "docs" / "wiki" / "terms"
        store = TermStore(terms_root)
        store.write(
            Term(
                id="01EVTBUS0000000000000",
                name="EventBus",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="bus.",
                code_anchor="src/events.py:EventBus",
                confidence="accepted",
                evidence=["ev-001"],
            )
        )
        _seed_wiki(tmp_path, with_orphan=False)

        config = HydraFlowConfig(repo_root=tmp_path)
        loop = EntryEvidenceLoop(
            config=config,
            deps=_make_deps(tmp_path),
            llm=llm_match_only_eventbus,
            pr_port=pr_port_capturing,
            repo_root=tmp_path,
            dedup_path=tmp_path / "dedup.json",
        )

        result = await loop._do_work()  # noqa: SLF001

        # The single entry was already linked, so the loop should consult no
        # LLM, touch no terms, and open no PR.
        assert result["opened_pr"] is False
        assert result["matched_entries"] == 0
        llm_match_only_eventbus.complete_structured.assert_not_awaited()
        pr_port_capturing.open_bot_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_max_entries_per_tick_bounds_llm_calls(
        self,
        tmp_path: Path,
        pr_port_capturing,
    ) -> None:
        _seed_terms(tmp_path)
        # Seed three unrelated wiki entries — all unlinked.
        wiki_root = tmp_path / "docs" / "wiki"
        wiki_root.mkdir(parents=True, exist_ok=True)
        (wiki_root / "architecture.md").write_text(
            "# Architecture\n\n"
            + _entry_block(eid="ev-001", title="a", prose="first.")
            + _entry_block(eid="ev-002", title="b", prose="second.")
            + _entry_block(eid="ev-003", title="c", prose="third.")
        )
        llm = AsyncMock()
        llm.complete_structured = AsyncMock(return_value={"term_ids": []})

        config = HydraFlowConfig(
            repo_root=tmp_path, entry_evidence_max_entries_per_tick=2
        )
        loop = EntryEvidenceLoop(
            config=config,
            deps=_make_deps(tmp_path),
            llm=llm,
            pr_port=pr_port_capturing,
            repo_root=tmp_path,
            dedup_path=tmp_path / "dedup.json",
        )

        result = await loop._do_work()  # noqa: SLF001

        # 2 LLM calls (cap), all returned empty so no PR.
        assert llm.complete_structured.await_count == 2
        assert result["checked"] == 2
        assert result["opened_pr"] is False

    @pytest.mark.asyncio
    async def test_zero_match_entries_are_cached_to_dedup_store(
        self,
        tmp_path: Path,
        pr_port_capturing,
    ) -> None:
        """Negative-evidence cache prevents re-burning LLM budget on
        entries that match no terms — review feedback from PR #8733."""
        _seed_terms(tmp_path)
        _seed_wiki(tmp_path)  # ev-001 matches EventBus, ev-002 is an orphan
        llm = AsyncMock()
        llm.complete_structured = AsyncMock(return_value={"term_ids": []})

        config = HydraFlowConfig(repo_root=tmp_path)
        loop = EntryEvidenceLoop(
            config=config,
            deps=_make_deps(tmp_path),
            llm=llm,
            pr_port=pr_port_capturing,
            repo_root=tmp_path,
            dedup_path=tmp_path / "dedup.json",
        )

        # Tick 1 — both entries hit the LLM and return [].
        await loop._do_work()  # noqa: SLF001
        assert llm.complete_structured.await_count == 2

        # Tick 2 — both entries should be cached as zero-match. No LLM calls.
        llm.complete_structured.reset_mock()
        await loop._do_work()  # noqa: SLF001
        assert llm.complete_structured.await_count == 0
