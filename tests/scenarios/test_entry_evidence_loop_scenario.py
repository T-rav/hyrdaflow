"""MockWorld scenario for EntryEvidenceLoop (ADR-0062).

Drives the loop end-to-end with a stubbed LLM client and a captured
``BotPRPort``, asserts that:

1. The loop emits ONE bot PR with the correct label.
2. The PR's files dict contains an updated term file whose evidence
   list now references the matched wiki entry.
3. A re-tick is a no-op (idempotence by set-difference) — second call
   opens no PR.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from entry_evidence_loop import ENTRY_EVIDENCE_PR_LABEL, EntryEvidenceLoop
from events import EventBus
from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermStore,
)

pytestmark = pytest.mark.scenario_loops


def _write_entry(
    wiki_root: Path, *, topic: str, eid: str, title: str, prose: str
) -> None:
    page = wiki_root / f"{topic}.md"
    meta = {
        "id": eid,
        "title": title,
        "source_type": "manual",
        "valid_from": "2026-01-01T00:00:00Z",
    }
    block = f"## {title}\n\n{prose}\n\n```json:entry\n{json.dumps(meta)}\n```\n\n"
    existing = page.read_text() if page.exists() else f"# {topic.title()}\n\n"
    page.write_text(existing + block)


class TestEntryEvidenceLoop:
    @pytest.mark.asyncio
    async def test_links_entries_and_is_idempotent_on_re_tick(
        self, tmp_path: Path
    ) -> None:
        # 1. Seed terms.
        terms_root = tmp_path / "docs" / "wiki" / "terms"
        store = TermStore(terms_root)
        target = Term(
            id="01EVTBUS0000000000000",
            name="EventBus",
            kind=TermKind.SERVICE,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="Async pub/sub bus.",
            code_anchor="src/events.py:EventBus",
            confidence="accepted",
        )
        store.write(target)

        # 2. Seed wiki entries — one that mentions EventBus, one orphan.
        wiki_root = tmp_path / "docs" / "wiki"
        _write_entry(
            wiki_root,
            topic="architecture",
            eid="ev-101",
            title="Async coordination",
            prose="The EventBus carries all worker status events.",
        )
        _write_entry(
            wiki_root,
            topic="gotchas",
            eid="ev-102",
            title="Stray ordering bug",
            prose="A test-only sequencing bug unrelated to any domain term.",
        )

        # 3. Stub LLM: matches ev-101 → EventBus, refuses ev-102.
        llm = AsyncMock()

        async def fake(prompt: str, schema):
            if "Async coordination" in prompt:
                return {"term_ids": ["01EVTBUS0000000000000"]}
            return {"term_ids": []}

        llm.complete_structured.side_effect = fake

        # 4. Capture the bot PR opened by the loop.
        pr_port = AsyncMock()
        pr_port.open_bot_pr = AsyncMock(return_value=1234)

        config = HydraFlowConfig(repo_root=tmp_path)
        deps = LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=lambda *_a, **_kw: None,
            enabled_cb=lambda _name: True,
        )
        loop = EntryEvidenceLoop(
            config=config,
            deps=deps,
            llm=llm,
            pr_port=pr_port,
            repo_root=tmp_path,
        )

        # First tick — should open a PR linking ev-101 to EventBus.
        result = await loop._do_work()  # noqa: SLF001
        assert result["status"] == "ok"
        assert result["matched_entries"] == 1
        assert result["terms_touched"] == 1
        assert result["opened_pr"] is True
        pr_port.open_bot_pr.assert_awaited_once()
        _, kwargs = pr_port.open_bot_pr.call_args
        assert kwargs["labels"] == [ENTRY_EVIDENCE_PR_LABEL]
        # File contents should include the linked entry id.
        rendered = next(iter(kwargs["files"].values()))
        assert "ev-101" in rendered

        # 5. Simulate the PR landing: write the updated term to disk so the
        # next tick sees the link as already-applied.
        target_with_evidence = Term.model_validate(
            {
                **target.model_dump(),
                "evidence": ["ev-101"],
            }
        )
        store.write(target_with_evidence)

        # Reset call counters and run another tick.
        pr_port.open_bot_pr.reset_mock()
        llm.complete_structured.reset_mock()

        result2 = await loop._do_work()  # noqa: SLF001

        # Idempotent: ev-101 is already linked, so the loop should
        # consult the LLM only for ev-102 (the orphan) and open no PR.
        assert result2["opened_pr"] is False
        assert result2["matched_entries"] == 0
        pr_port.open_bot_pr.assert_not_awaited()
        assert llm.complete_structured.await_count == 1
