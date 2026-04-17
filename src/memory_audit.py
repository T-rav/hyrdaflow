"""Periodic memory quality auditor using Hindsight reflect."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from hindsight import HindsightClient

from exception_classify import reraise_on_credit_or_bug
from hindsight import Bank

logger = logging.getLogger("hydraflow.memory_audit")

_AUDIT_PROMPT = (
    "Analyze the memories in this bank. Identify: "
    "1) Redundant or duplicate memories that say the same thing differently. "
    "2) Outdated memories that may no longer be accurate. "
    "3) Contradictory memories that conflict with each other. "
    "4) High-value memories that are consistently useful. "
    "Provide a structured assessment with specific examples."
)


class MemoryAuditor:
    """Periodic memory quality auditor using Hindsight reflect."""

    def __init__(self, client: HindsightClient, config: HydraFlowConfig) -> None:
        self._client = client
        self._config = config

    async def audit_bank(self, bank: Bank) -> dict[str, Any]:
        """Run a reflect query to assess memory quality in a bank."""
        reflection = await self._client.reflect(bank, _AUDIT_PROMPT)
        return {
            "bank": str(bank),
            "reflection": reflection,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def audit_all(self) -> list[dict[str, Any]]:
        """Audit all memory banks."""
        results: list[dict[str, Any]] = []
        for bank in Bank:
            try:
                result = await self.audit_bank(bank)
                results.append(result)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning("Audit failed for bank=%s", bank, exc_info=True)
        return results
