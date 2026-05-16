from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, cast

from src.pending_concerns import Concern, Phase

logger = logging.getLogger(__name__)


class AgentLike(Protocol):
    async def run(self, system_prompt: str, user_message: str) -> str: ...


@dataclass
class SurfacerOutput:
    assumptions: list[str] = field(default_factory=list)
    concerns: list[Concern] = field(default_factory=list)


_SYSTEM_PROMPT = """\
You are an Assumption Surfacer. Read an issue body, available research
context, and any carryover concerns from earlier pipeline stages, and
extract:

  1. Implicit assumptions the downstream planner will make ("we assume X").
  2. NEW concerns where one of those assumptions could be wrong.

Output strict JSON:
{
  "assumptions": ["..."],
  "concerns": [
    {"severity": "CRITICAL|HIGH|MEDIUM|LOW",
     "concern": "...",
     "must_address_by": "<next stage name>"}
  ]
}

Be concise. Do not invent assumptions to fill space. If nothing stands out,
return empty lists. Severity guide:
  CRITICAL: assumption is provably false or directly contradicts an ADR.
  HIGH: assumption affects buildability or test design and is unverified.
  MEDIUM: assumption is plausible but worth documenting.
  LOW: assumption is minor.
"""


@dataclass
class AssumptionSurfacer:
    """Read-only agent that surfaces assumptions + uncertainty concerns.

    Used in both Discovery and Plan phases. The `phase` parameter namespaces
    emitted concern IDs and is recorded on each Concern's `raised_in_phase`.
    """

    agent: AgentLike
    phase: str  # "discover" or "plan"

    async def run(
        self,
        issue_body: str,
        research_context: str,
        carryover_concerns: list[Concern],
    ) -> SurfacerOutput:
        carryover_block = (
            "\n".join(
                f"- [{c.id}|{c.severity}] {c.concern}" for c in carryover_concerns
            )
            or "(none)"
        )

        user_msg = (
            f"## Issue body\n{issue_body}\n\n"
            f"## Research context\n{research_context}\n\n"
            f"## Carryover concerns from earlier stages\n{carryover_block}\n"
        )

        try:
            raw = await self.agent.run(_SYSTEM_PROMPT, user_msg)
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("AssumptionSurfacer JSON parse failure: %s", exc)
            return SurfacerOutput()
        except Exception as exc:
            logger.warning("AssumptionSurfacer agent failure: %s", exc)
            return SurfacerOutput()

        now = datetime.now(UTC)
        phase_literal = cast(Phase, self.phase)
        concerns = [
            Concern(
                id=f"{self.phase.upper()}-ASSUMP-{i:03d}",
                raised_in_phase=phase_literal,
                raised_in_stage="assumption_surfacer",
                severity=c["severity"],
                concern=c["concern"],
                raised_at=now,
                must_address_by=c.get("must_address_by", "next"),
            )
            for i, c in enumerate(data.get("concerns", []), start=1)
        ]
        return SurfacerOutput(
            assumptions=list(data.get("assumptions", [])),
            concerns=concerns,
        )
