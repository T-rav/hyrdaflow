"""Hindsight memory client — async adapter for the Hindsight REST API.

Provides retain/recall/reflect operations for unified agent memory.
See https://github.com/vectorize-io/hindsight
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("hydraflow.hindsight")

# Bank IDs for different memory domains
BANK_LEARNINGS = "hydraflow-learnings"
BANK_RETROSPECTIVES = "hydraflow-retrospectives"
BANK_REVIEW_INSIGHTS = "hydraflow-review-insights"
BANK_HARNESS_INSIGHTS = "hydraflow-harness-insights"
BANK_TROUBLESHOOTING = "hydraflow-troubleshooting"


class HindsightMemory(BaseModel):
    """A single memory item returned by Hindsight recall."""

    content: str = ""
    context: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
    relevance_score: float = 0.0
    timestamp: str = ""


class HindsightClient:
    """Async HTTP client for the Hindsight memory API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8888",
        api_key: str = "",
        timeout: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def health_check(self) -> bool:
        """Return True if the Hindsight server is reachable."""
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def retain(
        self,
        bank_id: str,
        content: str,
        *,
        context: str = "",
        metadata: dict[str, str] | None = None,
    ) -> bool:
        """Store a memory in the given bank.

        Returns True on success, False on failure.
        """
        payload: dict[str, Any] = {
            "bank_id": bank_id,
            "content": content,
        }
        if context:
            payload["context"] = context
        if metadata:
            payload["metadata"] = metadata

        try:
            resp = await self._client.post("/v1/retain", json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "Hindsight retain failed (status=%d): %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
        except httpx.HTTPError:
            logger.warning("Hindsight retain request failed", exc_info=True)
            return False

    async def recall(
        self,
        bank_id: str,
        query: str,
        *,
        limit: int = 10,
        metadata_filter: dict[str, str] | None = None,
    ) -> list[HindsightMemory]:
        """Retrieve relevant memories from the given bank.

        Returns an empty list on failure.
        """
        payload: dict[str, Any] = {
            "bank_id": bank_id,
            "query": query,
            "limit": limit,
        }
        if metadata_filter:
            payload["metadata_filter"] = metadata_filter

        try:
            resp = await self._client.post("/v1/recall", json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "Hindsight recall failed (status=%d): %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return []
            data = resp.json()
            memories = data.get("memories", [])
            return [
                HindsightMemory(
                    content=m.get("content", ""),
                    context=m.get("context", ""),
                    metadata=m.get("metadata", {}),
                    relevance_score=m.get("relevance_score", 0.0),
                    timestamp=m.get("timestamp", ""),
                )
                for m in memories
            ]
        except httpx.HTTPError:
            logger.warning("Hindsight recall request failed", exc_info=True)
            return []

    async def reflect(self, bank_id: str) -> bool:
        """Trigger reflection on the given bank to build mental models.

        Returns True on success, False on failure.
        """
        payload = {"bank_id": bank_id}
        try:
            resp = await self._client.post("/v1/reflect", json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "Hindsight reflect failed (status=%d): %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
        except httpx.HTTPError:
            logger.warning("Hindsight reflect request failed", exc_info=True)
            return False


async def retain_safe(
    client: HindsightClient | None,
    bank_id: str,
    content: str,
    *,
    context: str = "",
    metadata: dict[str, str] | None = None,
) -> None:
    """Fire-and-forget retain — never raises, never blocks the pipeline."""
    if client is None:
        return
    try:
        await client.retain(bank_id, content, context=context, metadata=metadata)
    except Exception:
        logger.warning(
            "Hindsight retain_safe failed for bank %s",
            bank_id,
            exc_info=True,
        )


async def recall_safe(
    client: HindsightClient | None,
    bank_id: str,
    query: str,
    *,
    limit: int = 10,
    metadata_filter: dict[str, str] | None = None,
) -> list[HindsightMemory]:
    """Safe recall — returns empty list on any failure."""
    if client is None:
        return []
    try:
        return await client.recall(
            bank_id, query, limit=limit, metadata_filter=metadata_filter
        )
    except Exception:
        logger.warning(
            "Hindsight recall_safe failed for bank %s",
            bank_id,
            exc_info=True,
        )
        return []


def format_memories_as_markdown(memories: list[HindsightMemory]) -> str:
    """Format recalled memories as a markdown section for prompt injection."""
    if not memories:
        return ""
    lines = [f"## Relevant Learnings ({len(memories)} memories)\n"]
    for m in memories:
        ctx = f" — {m.context}" if m.context else ""
        lines.append(f"- {m.content}{ctx}")
    return "\n".join(lines) + "\n"
