"""Memory context route handlers for surfacing Hindsight data to operators."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._routes import RouteContext
from hindsight_types import Bank, HindsightMemory
from models import MemoryBankInfo, MemoryContextItem, MemoryContextResponse

logger = logging.getLogger("hydraflow.dashboard.memory")


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register memory-context routes on *router*."""

    # -- helpers --------------------------------------------------------------

    def _memory_from_hindsight(
        bank: Bank,
        mem: HindsightMemory,
    ) -> MemoryContextItem:
        """Convert a HindsightMemory to a MemoryContextItem."""
        return MemoryContextItem(
            bank=str(bank),
            content=mem.display_text,
            relevance_score=mem.relevance_score,
            timestamp=mem.timestamp,
            context=mem.context,
        )

    # -- endpoints ------------------------------------------------------------

    @router.get("/api/memory/banks")
    async def memory_banks() -> JSONResponse:
        """List all memory banks with metadata."""
        banks = [MemoryBankInfo(id=str(b), name=b.name) for b in Bank]
        return JSONResponse(
            {"banks": [b.model_dump() for b in banks]},
        )

    @router.get("/api/memory/search")
    async def memory_search(
        q: str = "",
        bank: str | None = None,
        limit: int = 10,
    ) -> JSONResponse:
        """Search memories across banks by keyword query."""
        if not q.strip():
            return JSONResponse(
                MemoryContextResponse(query=q, bank_filter=bank).model_dump(),
            )
        if ctx.hindsight_client is None:
            return JSONResponse(
                MemoryContextResponse(query=q, bank_filter=bank).model_dump(),
            )

        # Resolve bank filter
        target_banks: list[Bank] | None = None
        if bank:
            matched = next((b for b in Bank if str(b) == bank or b.name == bank), None)
            if matched is None:
                return JSONResponse(
                    MemoryContextResponse(query=q, bank_filter=bank).model_dump(),
                )
            target_banks = [matched]

        try:
            bank_results = await ctx.hindsight_client.recall_banks(
                q,
                target_banks,
                limit=limit,
            )
        except Exception:  # noqa: BLE001
            logger.warning("memory_search: recall_banks failed", exc_info=True)
            return JSONResponse(
                MemoryContextResponse(query=q, bank_filter=bank).model_dump(),
            )

        items: list[MemoryContextItem] = []
        for b, memories in bank_results.items():
            for mem in memories:
                items.append(_memory_from_hindsight(b, mem))

        items.sort(key=lambda x: x.relevance_score, reverse=True)
        items = items[:limit]

        resp = MemoryContextResponse(items=items, query=q, bank_filter=bank)
        return JSONResponse(resp.model_dump())

    @router.get("/api/memory/issue/{issue_number}")
    async def memory_for_issue(issue_number: int) -> JSONResponse:
        """Return memory context relevant to a specific issue.

        Queries Hindsight with the issue number as context so the human
        operator can see what institutional knowledge is available.
        """
        if ctx.hindsight_client is None:
            return JSONResponse(
                MemoryContextResponse(query=f"issue #{issue_number}").model_dump(),
            )

        query = f"issue #{issue_number}"
        try:
            bank_results = await ctx.hindsight_client.recall_banks(query, limit=5)
        except Exception:  # noqa: BLE001
            logger.warning(
                "memory_for_issue: recall failed for issue #%d",
                issue_number,
                exc_info=True,
            )
            return JSONResponse(MemoryContextResponse(query=query).model_dump())

        items: list[MemoryContextItem] = []
        for b, memories in bank_results.items():
            for mem in memories:
                items.append(_memory_from_hindsight(b, mem))

        items.sort(key=lambda x: x.relevance_score, reverse=True)
        items = items[:5]

        resp = MemoryContextResponse(items=items, query=query)
        return JSONResponse(resp.model_dump())

    @router.get("/api/memory/pr/{pr_number}")
    async def memory_for_pr(pr_number: int) -> JSONResponse:
        """Return memory context relevant to a specific PR.

        Queries Hindsight with the PR number as context so the human
        operator can see which institutional knowledge was in play for
        that PR.
        """
        if ctx.hindsight_client is None:
            return JSONResponse(
                MemoryContextResponse(query=f"PR #{pr_number}").model_dump(),
            )

        query = f"PR #{pr_number}"
        try:
            bank_results = await ctx.hindsight_client.recall_banks(query, limit=5)
        except Exception:  # noqa: BLE001
            logger.warning(
                "memory_for_pr: recall failed for PR #%d",
                pr_number,
                exc_info=True,
            )
            return JSONResponse(MemoryContextResponse(query=query).model_dump())

        items: list[MemoryContextItem] = []
        for b, memories in bank_results.items():
            for mem in memories:
                items.append(_memory_from_hindsight(b, mem))

        items.sort(key=lambda x: x.relevance_score, reverse=True)
        items = items[:5]

        resp = MemoryContextResponse(items=items, query=query)
        return JSONResponse(resp.model_dump())

    @router.get("/api/memory/hitl/{issue_number}")
    async def memory_for_hitl(issue_number: int) -> JSONResponse:
        """Return memory context for a HITL escalation.

        Combines the issue query with the HITL cause (if available) to
        surface the most relevant troubleshooting knowledge.
        """
        cause = ctx.state.get_hitl_cause(issue_number)

        query_parts = [f"issue #{issue_number}"]
        if cause:
            query_parts.append(cause)
        query = " ".join(query_parts)

        if ctx.hindsight_client is None:
            return JSONResponse(
                MemoryContextResponse(query=query).model_dump(),
            )

        # Recall from troubleshooting + learnings banks for HITL context
        hitl_banks = [Bank.TROUBLESHOOTING, Bank.TRIBAL, Bank.REVIEW_INSIGHTS]
        try:
            bank_results = await ctx.hindsight_client.recall_banks(
                query,
                hitl_banks,
                limit=5,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "memory_for_hitl: recall failed for issue #%d",
                issue_number,
                exc_info=True,
            )
            return JSONResponse(MemoryContextResponse(query=query).model_dump())

        items: list[MemoryContextItem] = []
        for b, memories in bank_results.items():
            for mem in memories:
                items.append(_memory_from_hindsight(b, mem))

        items.sort(key=lambda x: x.relevance_score, reverse=True)
        items = items[:5]

        resp = MemoryContextResponse(items=items, query=query)
        return JSONResponse(resp.model_dump())
