"""ShapeChallenger — concern-shape adapter around a shape-critique agent.

The existing :class:`shape_runner.ShapeRunner` already runs a critic-style
prompt (see ``_build_critic_prompt``) embedded inside its multi-turn
product-shaping conversation. The retrofit here does NOT replace that
behaviour — it adds an adversarial-pipeline adapter that produces the
uniform ``list[Concern]`` contract used by every other Task-1..8 stage.

Contract per the earlier-adversarial pipeline plan (Task 9):

  * Concern IDs are ``SHAPE-CHAL-{i:03d}`` (1-indexed).
  * ``raised_in_phase == "shape"``.
  * ``raised_in_stage == "shape_challenger"``.
  * ``must_address_by == "expert_council"`` (the next stage in shape).

The adapter is read-only: a single AgentLike call, JSON parse, soft-fail
to an empty concern list if the agent crashes or returns malformed
output (mirrors :class:`assumption_surfacer.AssumptionSurfacer`).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from exception_classify import reraise_on_credit_or_bug
from src.adversarial_agents import AgentLike
from src.pending_concerns import Concern

logger = logging.getLogger(__name__)


SHAPE_CHALLENGER_PROMPT = """\
You are the Shape Challenger. You receive a proposed product direction
(or set of directions) and must surface concerns that would weaken or
invalidate it.

Critique the proposal rigorously. Focus on:
  - Hidden assumptions that may not hold.
  - Missing tradeoffs in the proposed direction.
  - Differentiators that look weak or unsupported.
  - Risks the proposer underplayed.
  - Whether the scoping is honest (no scope-creep masquerading as MVP).

Output strict JSON:
{
  "findings": [
    {"severity": "CRITICAL|HIGH|MEDIUM|LOW",
     "concern": "..."}
  ]
}

If the proposal stands up, return an empty findings list. Do not invent
concerns to fill space. Severity guide:
  CRITICAL: the direction is non-viable as stated.
  HIGH: a major risk that should change the proposal.
  MEDIUM: a tradeoff worth documenting.
  LOW: a nit.
"""


@dataclass
class ChallengerOutput:
    """Adapter output. ``findings`` matches the ``HasFindings`` protocol."""

    findings: list[Concern]


@dataclass
class ShapeChallenger:
    """Read-only adversarial critic for shape proposals.

    Run a single AgentLike invocation against ``SHAPE_CHALLENGER_PROMPT``
    plus the shape content, parse the JSON reply, and return concerns
    keyed for the shape phase.
    """

    agent: AgentLike

    async def run(
        self,
        shape_content: str,
        carryover_concerns: list[Concern],
    ) -> ChallengerOutput:
        carryover_block = (
            "\n".join(
                f"- [{c.id}|{c.severity}] {c.concern} "
                f"(from {c.raised_in_phase}/{c.raised_in_stage})"
                for c in carryover_concerns
            )
            or "(none)"
        )

        user_msg = (
            f"## Shape proposal under review\n{shape_content}\n\n"
            f"## Carryover concerns from earlier stages\n{carryover_block}\n\n"
            f"Critique the proposal. Output strict JSON only."
        )

        try:
            raw = await self.agent.run(SHAPE_CHALLENGER_PROMPT, user_msg)
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("ShapeChallenger JSON parse failure: %s", exc)
            return ChallengerOutput(findings=[])
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.warning("ShapeChallenger agent failure: %s", exc)
            return ChallengerOutput(findings=[])

        now = datetime.now(UTC)
        findings = [
            Concern(
                id=f"SHAPE-CHAL-{i:03d}",
                raised_in_phase="shape",
                raised_in_stage="shape_challenger",
                severity=f["severity"],
                concern=f["concern"],
                raised_at=now,
                must_address_by="expert_council",
            )
            for i, f in enumerate(data.get("findings", []), start=1)
        ]
        return ChallengerOutput(findings=findings)
