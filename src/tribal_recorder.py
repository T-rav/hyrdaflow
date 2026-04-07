"""Explicit tribal-knowledge recording tool.

Agents call this when they hit a 'huh, that's load-bearing weirdness'
moment and want to deliberately preserve a fact for future runs. The
recorder routes through the same `file_memory_suggestion` pipeline as
transcript-parsed suggestions, so the LLM judge gate applies uniformly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from hindsight import HindsightClient
    from memory_judge import MemoryJudge

logger = logging.getLogger("hydraflow.tribal_recorder")


async def record_tribal_knowledge(
    *,
    principle: str,
    rationale: str,
    failure_mode: str,
    scope: str,
    source: str,
    config: HydraFlowConfig,
    hindsight: HindsightClient | None = None,
    judge: MemoryJudge | None = None,
) -> None:
    """Deliberately record a piece of tribal knowledge.

    Builds a synthetic MEMORY_SUGGESTION transcript and routes it through
    `file_memory_suggestion`, which applies schema validation, the LLM
    judge gate, JSONL storage, and Hindsight retain in one shot.
    """
    from memory import file_memory_suggestion  # noqa: PLC0415

    transcript = (
        "MEMORY_SUGGESTION_START\n"
        f"principle: {principle}\n"
        f"rationale: {rationale}\n"
        f"failure_mode: {failure_mode}\n"
        f"scope: {scope}\n"
        "MEMORY_SUGGESTION_END\n"
    )
    await file_memory_suggestion(
        transcript,
        source=source,
        reference=f"explicit:{source}",
        config=config,
        hindsight=hindsight,
        judge=judge,
    )
