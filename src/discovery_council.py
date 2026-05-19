"""DiscoveryCouncil — three-voter adversarial review of a discovery brief.

Runs Problem-Sharpener / Existing-Solution-Hunter / Cheapest-Test-Advocate
voters concurrently. Each voter encodes a distinct prior (sharpen the pain /
find prior art / falsify cheaply) in its system prompt. The council
aggregates findings into a CouncilTally that decides whether the Discovery
stage should retry.

Tally rule (identical to PlanCouncil):
  - CRITICAL from any voter → retry, forward all findings as-is.
  - >=2 voters land on overlapping HIGH (SequenceMatcher >= 0.85) → retry,
    forward all findings as-is.
  - Lone HIGH (single voter raised it) → downgrade to MEDIUM and forward,
    no retry.
  - MEDIUM/LOW always forward without modification (no retry effect).
  - Convergence = no CRITICAL AND no overlapping HIGH.

A voter that crashes is logged and treated as contributing zero findings —
the council does not propagate the exception.

This module mirrors ``src.plan_council`` deliberately — we copy-modify
rather than extract a base class so each council's voter geometry and
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
from src.discovery_council_prompts import (
    CHEAPEST_TEST_ADVOCATE_PROMPT,
    EXISTING_SOLUTION_HUNTER_PROMPT,
    PROBLEM_SHARPENER_PROMPT,
)
from src.pending_concerns import Concern

logger = logging.getLogger(__name__)

_OVERLAP_THRESHOLD = 0.85
_ROLES: tuple[str, ...] = (
    "problem_sharpener",
    "existing_solution_hunter",
    "cheapest_test_advocate",
)
_PROMPTS: dict[str, str] = {
    "problem_sharpener": PROBLEM_SHARPENER_PROMPT,
    "existing_solution_hunter": EXISTING_SOLUTION_HUNTER_PROMPT,
    "cheapest_test_advocate": CHEAPEST_TEST_ADVOCATE_PROMPT,
}


@dataclass
class CouncilTally:
    findings: list[Concern]
    should_retry: bool
    raw_per_voter: dict[str, list[Concern]] = field(default_factory=dict)


@dataclass
class DiscoveryCouncil:
    """Three-voter adversarial review of a discovery brief.

    ``agents`` must contain keys ``problem_sharpener``,
    ``existing_solution_hunter``, ``cheapest_test_advocate``. Each agent
    satisfies the AgentLike protocol (async run(system, user) -> str
    returning a JSON payload of shape {"findings": [...]}).
    """

    agents: dict[str, AgentLike]

    async def deliberate(
        self, discovery_text: str, pending_concerns: list[Concern]
    ) -> CouncilTally:
        user_msg = _build_user_message(discovery_text, pending_concerns)
        results = await asyncio.gather(
            *(self._run_voter(role, user_msg) for role in _ROLES),
            return_exceptions=True,
        )

        per_voter: dict[str, list[Concern]] = {}
        all_findings: list[tuple[str, Concern]] = []
        for role, result in zip(_ROLES, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("DiscoveryCouncil voter %s crashed: %s", role, result)
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
            logger.warning("DiscoveryCouncil voter %s returned non-JSON", role)
            return []
        now = datetime.now(UTC)
        return [
            Concern(
                id=f"DISC-{role.upper()}-{i:03d}",
                raised_in_phase="discover",
                raised_in_stage=f"discovery_council_{role}",
                severity=f["severity"],
                concern=f["concern"],
                raised_at=now,
                must_address_by="shape",
            )
            for i, f in enumerate(data.get("findings", []), start=1)
        ]


def _build_user_message(discovery_text: str, pending: list[Concern]) -> str:
    pending_block = (
        "\n".join(
            f"- [{c.id}|{c.severity}] {c.concern} "
            f"(from {c.raised_in_phase}/{c.raised_in_stage})"
            for c in pending
        )
        or "(none)"
    )
    return (
        f"## Discovery brief under review\n{discovery_text}\n\n"
        f"## Pending concerns from earlier stages\n{pending_block}\n\n"
        f"Critique the discovery brief from your role. Output strict JSON only."
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
