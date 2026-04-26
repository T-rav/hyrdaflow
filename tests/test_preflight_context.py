"""PreflightContext tests (spec §3.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from preflight.audit import PreflightAuditStore
from preflight.context import gather_context


@pytest.mark.asyncio
async def test_handles_missing_escalation_context(tmp_path: Path) -> None:
    """Spec §3.2 / §7: most caretaker escalations have escalation_context=None."""
    pr = AsyncMock()
    pr.list_issue_comments = AsyncMock(return_value=[])
    state = MagicMock()
    state.get_escalation_context = MagicMock(return_value=None)

    ctx = await gather_context(
        issue_number=8501,
        issue_body="Body here",
        sub_label="flaky-test-stuck",
        pr_port=pr,
        wiki_store=None,
        state=state,
        audit_store=PreflightAuditStore(tmp_path),
        repo_slug="acme/widget",
    )
    assert ctx.escalation_context is None
    assert ctx.wiki_excerpts == ""
    assert ctx.sentry_events == []
    assert ctx.recent_commits == []
    assert ctx.prior_attempts == []


@pytest.mark.asyncio
async def test_wiki_query_failure_does_not_block(tmp_path: Path) -> None:
    """Spec §3.2: wiki failure logs warning and returns empty wiki_excerpts."""
    pr = AsyncMock()
    pr.list_issue_comments = AsyncMock(return_value=[])
    state = MagicMock()
    state.get_escalation_context = MagicMock(return_value=None)
    wiki = MagicMock()
    wiki.query = MagicMock(side_effect=RuntimeError("boom"))

    ctx = await gather_context(
        issue_number=1,
        issue_body="x",
        sub_label="x",
        pr_port=pr,
        wiki_store=wiki,
        state=state,
        audit_store=PreflightAuditStore(tmp_path),
        repo_slug="x/y",
    )
    assert ctx.wiki_excerpts == ""


@pytest.mark.asyncio
async def test_prior_attempts_loaded(tmp_path: Path) -> None:
    from preflight.audit import PreflightAuditEntry

    audit = PreflightAuditStore(tmp_path)
    audit.append(
        PreflightAuditEntry(
            ts="2026-04-25T12:00:00Z",
            issue=42,
            sub_label="x",
            attempt_n=1,
            prompt_hash="h",
            cost_usd=1.0,
            wall_clock_s=10.0,
            tokens=100,
            status="needs_human",
            pr_url=None,
            diagnosis="d",
            llm_summary="s",
        )
    )
    pr = AsyncMock()
    pr.list_issue_comments = AsyncMock(return_value=[])
    state = MagicMock()
    state.get_escalation_context = MagicMock(return_value=None)

    ctx = await gather_context(
        issue_number=42,
        issue_body="x",
        sub_label="x",
        pr_port=pr,
        wiki_store=None,
        state=state,
        audit_store=audit,
        repo_slug="x/y",
    )
    assert len(ctx.prior_attempts) == 1
    assert ctx.prior_attempts[0].attempt_n == 1
