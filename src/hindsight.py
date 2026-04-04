"""Hindsight semantic memory client.

Wraps the Hindsight REST API (vectorize-io/hindsight) for retain/recall/reflect
operations.  All public helpers are fire-and-forget or never-raise so that a
Hindsight outage cannot break the main orchestration loop.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hindsight_wal import HindsightWAL

import httpx

from hindsight_types import Bank, HindsightMemory, WALEntry

logger = logging.getLogger("hydraflow.hindsight")

# Re-export for backward compatibility
__all__ = [
    "Bank",
    "HindsightClient",
    "HindsightMemory",
    "WALEntry",
    "format_memories_as_markdown",
    "recall_safe",
    "retain_safe",
    "schedule_retain",
]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class HindsightClient:
    """Async HTTP client for the Hindsight REST API."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        timeout: int = 30,
    ) -> None:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # -- Health ---------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return ``True`` if the Hindsight server is reachable."""
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    # -- Retain ---------------------------------------------------------------

    @staticmethod
    def _bank_path(bank: Bank | str, suffix: str = "") -> str:
        """Build the versioned bank API path."""
        base = f"/v1/default/banks/{bank}"
        return f"{base}/{suffix}" if suffix else base

    # -- Retain ---------------------------------------------------------------

    async def retain(
        self,
        bank: Bank | str,
        content: str,
        *,
        context: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a memory in *bank*."""
        item: dict[str, Any] = {
            "content": content,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if context:
            item["context"] = context
        if metadata:
            item["metadata"] = {k: str(v) for k, v in metadata.items()}
        payload: dict[str, Any] = {"items": [item]}
        resp = await self._client.post(self._bank_path(bank, "memories"), json=payload)
        resp.raise_for_status()
        return resp.json()

    # -- Recall ---------------------------------------------------------------

    async def recall(
        self,
        bank: Bank | str,
        query: str,
        *,
        limit: int = 10,
    ) -> list[HindsightMemory]:
        """Retrieve relevant memories from *bank*."""
        payload: dict[str, Any] = {"query": query}
        resp = await self._client.post(
            self._bank_path(bank, "memories/recall"), json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        items: list[dict[str, Any]] = data.get("results", [])
        memories = []
        for raw in items[:limit]:
            memories.append(
                HindsightMemory(
                    content=raw.get("text") or "",
                    text=raw.get("text") or "",
                    context=raw.get("context") or "",
                    metadata=raw.get("metadata") or {},
                    relevance_score=float(raw.get("relevance_score") or 0.0),
                    timestamp=raw.get("occurred_start") or raw.get("timestamp") or "",
                )
            )
        return memories

    # -- Reflect --------------------------------------------------------------

    async def reflect(
        self,
        bank: Bank | str,
        query: str,
    ) -> str:
        """Ask Hindsight for a synthesised reflection on *bank*."""
        payload: dict[str, Any] = {"query": query}
        resp = await self._client.post(self._bank_path(bank, "reflect"), json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("text", "")


# ---------------------------------------------------------------------------
# Safe wrappers (fire-and-forget / never-raise)
# ---------------------------------------------------------------------------


async def retain_safe(
    client: HindsightClient | None,
    bank: Bank | str,
    content: str,
    *,
    context: str = "",
    metadata: dict[str, Any] | None = None,
    wal: HindsightWAL | None = None,
) -> None:
    """Fire-and-forget retain — on failure, buffers to WAL for retry."""
    if client is None:
        return
    try:
        await client.retain(bank, content, context=context, metadata=metadata)
    except Exception:
        logger.warning("Hindsight retain failed for bank=%s", bank, exc_info=True)
        try:
            import sentry_sdk as _sentry

            _sentry.add_breadcrumb(
                category="hindsight.retain_failed",
                message=f"Hindsight retain failed for bank={bank}",
                level="warning",
                data={"bank": str(bank)},
            )
        except ImportError:
            pass
        if wal:
            wal.append(
                WALEntry(
                    bank=str(bank),
                    content=content,
                    context=context,
                    metadata=metadata or {},
                )
            )


async def recall_safe(
    client: HindsightClient | None,
    bank: Bank | str,
    query: str,
    *,
    limit: int = 10,
) -> list[HindsightMemory]:
    """Never-raise recall — returns ``[]`` on any failure."""
    if client is None:
        return []
    try:
        return await client.recall(bank, query, limit=limit)
    except Exception:
        logger.warning("Hindsight recall failed for bank=%s", bank, exc_info=True)
        try:
            import sentry_sdk as _sentry

            _sentry.add_breadcrumb(
                category="hindsight.recall_failed",
                message=f"Hindsight recall failed for bank={bank}",
                level="warning",
                data={"bank": str(bank)},
            )
        except ImportError:
            pass
        return []


def schedule_retain(
    client: HindsightClient | None,
    bank: Bank | str,
    content: str,
    *,
    context: str = "",
    metadata: dict[str, Any] | None = None,
    wal: HindsightWAL | None = None,
) -> None:
    """Schedule a fire-and-forget retain as an asyncio task.

    On failure, the operation is buffered to *wal* for later replay.
    No-op when *client* is None or no event loop is running.
    """
    import asyncio  # noqa: PLC0415

    if client is None:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            retain_safe(
                client, bank, content, context=context, metadata=metadata, wal=wal
            )
        )
    except RuntimeError:
        pass  # no event loop — skip


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_memories_as_markdown(memories: list[HindsightMemory]) -> str:
    """Format recalled memories as a markdown section for prompt injection."""
    if not memories:
        return ""
    lines: list[str] = []
    for mem in memories:
        lines.append(f"- {mem.display_text}")
        if mem.context:
            lines.append(f"  _Context: {mem.context}_")
    return "\n".join(lines)
