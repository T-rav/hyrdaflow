"""Shape Expert Council — concern-shape adapter for the three voter roles.

The legacy :class:`expert_council.ExpertCouncil` votes on lettered
directions and produces a :class:`expert_council.CouncilResult`. That
direction-vote logic is unchanged by this module — Task 9 of the
earlier-adversarial pipeline adds a *parallel* council adapter that
takes a shape proposal and emits the uniform ``list[Concern]`` contract
used by every other adversarial stage.

Three voters mirror the legacy roles:

  * ``user_advocate`` — User experience advocate.
  * ``tech_lead``    — Technical Lead.
  * ``product_strategist`` — Product Strategist.

Concern IDs are ``SHAPE-{ROLE_UPPER}-{i:03d}`` per role. All concerns
have ``raised_in_phase == "shape"`` and ``must_address_by == "plan"``.

This module mirrors :mod:`src.plan_council` / :mod:`src.discovery_council`
deliberately — copy-modify so each council's voter geometry and
identifiers stay grep-able in one file.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher

from src.adversarial_agents import AgentLike
from src.pending_concerns import Concern

logger = logging.getLogger(__name__)

_OVERLAP_THRESHOLD = 0.85
_ROLES: tuple[str, ...] = ("user_advocate", "tech_lead", "product_strategist")

USER_ADVOCATE_PROMPT = """\
You are the User Advocate on a product shaping council. You prioritize
user experience and solving real pain points. Critique the proposed
shape from a USER perspective — does it actually serve the user, or is
it engineering-led / market-led at the user's expense?

Output strict JSON:
{
  "findings": [
    {"severity": "CRITICAL|HIGH|MEDIUM|LOW", "concern": "..."}
  ]
}

If the shape serves users well, return an empty findings list.
"""

TECH_LEAD_PROMPT = """\
You are the Technical Lead on a product shaping council. You prioritize
feasibility, maintainability, and architectural soundness. Critique the
proposed shape from an ENGINEERING perspective — can this be built
reliably without unreasonable debt? Are the effort estimates honest?

Output strict JSON:
{
  "findings": [
    {"severity": "CRITICAL|HIGH|MEDIUM|LOW", "concern": "..."}
  ]
}

If the shape is technically sound, return an empty findings list.
"""

PRODUCT_STRATEGIST_PROMPT = """\
You are the Product Strategist on a product shaping council. You
prioritize market differentiation and business value. Critique the
proposed shape from a STRATEGY perspective — is the differentiator real,
and is this where the product should be investing?

Output strict JSON:
{
  "findings": [
    {"severity": "CRITICAL|HIGH|MEDIUM|LOW", "concern": "..."}
  ]
}

If the shape is strategically aligned, return an empty findings list.
"""

_PROMPTS: dict[str, str] = {
    "user_advocate": USER_ADVOCATE_PROMPT,
    "tech_lead": TECH_LEAD_PROMPT,
    "product_strategist": PRODUCT_STRATEGIST_PROMPT,
}


@dataclass
class CouncilTally:
    findings: list[Concern]
    should_retry: bool
    raw_per_voter: dict[str, list[Concern]] = field(default_factory=dict)


@dataclass
class ShapeExpertCouncil:
    """Three-voter adversarial review of a shape proposal.

    ``agents`` must contain keys ``user_advocate``, ``tech_lead``,
    ``product_strategist``. Each agent satisfies the AgentLike protocol
    (async ``run(system, user) -> str`` returning ``{"findings": [...]}``
    JSON).
    """

    agents: dict[str, AgentLike]

    async def deliberate(
        self, shape_content: str, pending_concerns: list[Concern]
    ) -> CouncilTally:
        user_msg = _build_user_message(shape_content, pending_concerns)
        results = await asyncio.gather(
            *(self._run_voter(role, user_msg) for role in _ROLES),
            return_exceptions=True,
        )

        per_voter: dict[str, list[Concern]] = {}
        all_findings: list[tuple[str, Concern]] = []
        for role, result in zip(_ROLES, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("ShapeExpertCouncil voter %s crashed: %s", role, result)
                per_voter[role] = []
                continue
            per_voter[role] = result
            for c in result:
                all_findings.append((role, c))

        return _tally(all_findings, per_voter)

    async def _run_voter(self, role: str, user_msg: str) -> list[Concern]:
        raw = await self.agents[role].run(_PROMPTS[role], user_msg)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("ShapeExpertCouncil voter %s returned non-JSON", role)
            return []
        now = datetime.now(UTC)
        stage = f"shape_{role}"
        return [
            Concern(
                id=f"SHAPE-{role.upper()}-{i:03d}",
                raised_in_phase="shape",
                raised_in_stage=stage,
                severity=f["severity"],
                concern=f["concern"],
                raised_at=now,
                must_address_by="plan",
            )
            for i, f in enumerate(data.get("findings", []), start=1)
        ]


def _build_user_message(shape_content: str, pending: list[Concern]) -> str:
    pending_block = (
        "\n".join(
            f"- [{c.id}|{c.severity}] {c.concern} "
            f"(from {c.raised_in_phase}/{c.raised_in_stage})"
            for c in pending
        )
        or "(none)"
    )
    return (
        f"## Shape proposal under review\n{shape_content}\n\n"
        f"## Pending concerns from earlier stages\n{pending_block}\n\n"
        f"Critique the proposal from your role. Output strict JSON only."
    )


def _tally(
    all_findings: list[tuple[str, Concern]],
    per_voter: dict[str, list[Concern]],
) -> CouncilTally:
    has_critical = any(c.severity == "CRITICAL" for _, c in all_findings)

    high_findings = [(role, c) for role, c in all_findings if c.severity == "HIGH"]
    clusters = _cluster_by_similarity(high_findings, threshold=_OVERLAP_THRESHOLD)
    overlapping_high = any(
        len({role for role, _ in cluster}) >= 2 for cluster in clusters
    )
    should_retry = has_critical or overlapping_high

    if should_retry:
        merged_findings = [c for _, c in all_findings]
    else:
        # No retry. Forward HIGHs (downgrading lone ones to MEDIUM) plus all
        # MEDIUM/LOW as-is. CRITICAL is impossible in this branch.
        merged_findings = []
        for cluster in clusters:
            unique_voters = {role for role, _ in cluster}
            for _, c in cluster:
                if len(unique_voters) == 1:
                    merged_findings.append(c.model_copy(update={"severity": "MEDIUM"}))
                else:
                    merged_findings.append(c)
        for _, c in all_findings:
            if c.severity in {"MEDIUM", "LOW"}:
                merged_findings.append(c)

    return CouncilTally(
        findings=merged_findings,
        should_retry=should_retry,
        raw_per_voter=per_voter,
    )


def _cluster_by_similarity(
    items: list[tuple[str, Concern]], threshold: float
) -> list[list[tuple[str, Concern]]]:
    clusters: list[list[tuple[str, Concern]]] = []
    for item in items:
        _, concern = item
        placed = False
        for cluster in clusters:
            _, rep = cluster[0]
            if SequenceMatcher(None, rep.concern, concern.concern).ratio() >= threshold:
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])
    return clusters
