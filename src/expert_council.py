"""Expert council — multi-perspective voting on product directions.

Runs 3 expert agents in parallel to evaluate proposed directions.
If a supermajority (2/3+) agrees, the decision is made automatically.
If split, escalates to human for tiebreaker.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from phase_utils import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from models import Task

logger = logging.getLogger("hydraflow.expert_council")

_VOTE_START = "COUNCIL_VOTE_START"
_VOTE_END = "COUNCIL_VOTE_END"

EXPERTS = [
    {
        "name": "User Advocate",
        "perspective": (
            "You prioritize user experience and solving real pain points. "
            "Vote for the direction that best serves actual users — not the "
            "technically impressive one, but the one users will love."
        ),
    },
    {
        "name": "Technical Lead",
        "perspective": (
            "You prioritize feasibility, maintainability, and architectural "
            "soundness. Vote for the direction that can be built reliably "
            "and maintained long-term without technical debt."
        ),
    },
    {
        "name": "Product Strategist",
        "perspective": (
            "You prioritize market differentiation and business value. "
            "Vote for the direction that creates the most defensible "
            "advantage and aligns with the product vision."
        ),
    },
]


# Diversified-persona experts for round 3 (ADR-0063 W4). When the standard
# council remains split after two rounds of normal voting + mediation, these
# three personas often unblock the deadlock by forcing the question from
# angles the standard experts share too much in common to surface:
#
#   * The Dissenter argues *against* whichever direction is leading — the
#     specific failure modes that make it the wrong choice 6 months out.
#   * The Consensus-Seeker hunts for the lowest-common-denominator option
#     that every standard expert can live with, even if it's nobody's first
#     pick.
#   * The Regret-in-6-Months persona pre-imagines the post-mortem: assume
#     the decision shipped, then describe what they wish had been chosen
#     instead and why.
DIVERSIFIED_EXPERTS = [
    {
        "name": "Dissenter",
        "perspective": (
            "You are the contrarian on this council. Your job is to argue "
            "AGAINST the option that currently appears to be leading in the "
            "prior round's vote. Identify the specific failure modes that "
            "would make the leading option the wrong choice 6 months from "
            "now. Then vote for whichever direction best avoids those failure "
            "modes — even if it wasn't the leader. If the leading option "
            "genuinely has no serious downsides relative to its alternatives, "
            "say so and vote for it with high confidence."
        ),
    },
    {
        "name": "Consensus-Seeker",
        "perspective": (
            "You are the consensus-builder on this council. Look at the prior "
            "round's votes and identify the lowest-common-denominator option "
            "that every expert could LIVE WITH, even if it's no one's first "
            "pick. The goal is not the most ambitious direction or the safest "
            "direction — it is the one with the broadest acceptable footprint "
            "across user, technical, and strategic concerns. Vote for that "
            "option."
        ),
    },
    {
        "name": "Regret-in-6-Months",
        "perspective": (
            "You are looking back from 6 months after this decision shipped. "
            "Imagine each candidate direction was chosen, then ask: which one "
            "would the team regret LEAST? Which one would they say 'we wish "
            "we'd done differently' about the most? Vote for the direction "
            "you'd regret the least having chosen, and explain the concrete "
            "regret you'd feel about the rejected alternatives."
        ),
    },
]


class CouncilVote:
    """Result of a single expert's vote."""

    def __init__(
        self,
        expert_name: str,
        direction: str,
        reasoning: str,
        confidence: int,
    ) -> None:
        self.expert_name = expert_name
        self.direction = direction.upper()
        self.reasoning = reasoning
        self.confidence = max(1, min(confidence, 10))
        self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, object]:
        return {
            "expert": self.expert_name,
            "direction": self.direction,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


class CouncilResult:
    """Aggregated result of all expert votes."""

    def __init__(self, votes: list[CouncilVote]) -> None:
        self.votes = votes
        self.timestamp = datetime.now(UTC).isoformat()

    @property
    def has_consensus(self) -> bool:
        """True if 2/3+ experts agree on a direction."""
        if len(self.votes) < 2:
            return False
        direction_counts: dict[str, int] = {}
        for v in self.votes:
            direction_counts[v.direction] = direction_counts.get(v.direction, 0) + 1
        threshold = len(self.votes) * 2 / 3
        return any(count >= threshold for count in direction_counts.values())

    @property
    def winning_direction(self) -> str | None:
        """The direction with the most votes, or None if no consensus."""
        if not self.votes:
            return None
        direction_counts: dict[str, int] = {}
        for v in self.votes:
            direction_counts[v.direction] = direction_counts.get(v.direction, 0) + 1
        winner = max(direction_counts, key=lambda d: direction_counts[d])
        threshold = len(self.votes) * 2 / 3
        if direction_counts[winner] >= threshold:
            return winner
        return None

    @property
    def avg_confidence(self) -> float:
        if not self.votes:
            return 0.0
        return sum(v.confidence for v in self.votes) / len(self.votes)

    def format_summary(self) -> str:
        """Format the council vote as a structured comment."""
        lines = ["## Expert Council Vote\n"]
        for v in self.votes:
            lines.append(
                f"**{v.expert_name}:** Direction {v.direction} "
                f"(confidence: {v.confidence}/10)\n"
                f"> {v.reasoning}\n"
            )
        winner = self.winning_direction
        if winner:
            lines.append(
                f"\n**Consensus reached:** Direction {winner} "
                f"(avg confidence: {self.avg_confidence:.1f}/10) — "
                f"auto-selecting.\n"
            )
        else:
            lines.append("\n**No consensus** — escalating to human for tiebreaker.\n")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "votes": [v.to_dict() for v in self.votes],
            "consensus": self.has_consensus,
            "winner": self.winning_direction,
            "avg_confidence": self.avg_confidence,
            "timestamp": self.timestamp,
        }


def _consume_mockworld_council_vote(council, issue_number, *, diversified):  # noqa: ANN001
    """Return a synthesized CouncilResult from the scripted verdict map.

    Returns ``None`` when the council is not under a MockWorld harness or
    when the scenario has not scripted a verdict for the current round.
    The per-council round counter advances every time a synthesized vote
    is returned, mirroring the production round progression driven by
    :meth:`ShapePhase._run_council_vote`.

    A ``"split"`` verdict synthesizes three votes on three distinct
    directions (A/B/C) so :meth:`CouncilResult.has_consensus` returns
    False; a ``"consensus"`` verdict synthesizes three votes on the same
    direction A so consensus is True. ``diversified=True`` synthesizes
    against the diversified-persona panel; the consensus-rule check is
    identical so downstream code is unchanged.
    """
    fake_llm = getattr(council, "_mockworld_fake_llm", None)
    if fake_llm is None or not getattr(fake_llm, "_is_fake_adapter", False):
        return None
    if not hasattr(fake_llm, "shape_council_verdict_for_round"):
        return None

    counters = getattr(council, "_mockworld_round_counters", None)
    if counters is None:
        counters = {}
        council._mockworld_round_counters = counters  # type: ignore[attr-defined]
    next_round = counters.get(issue_number, 0) + 1
    verdict = fake_llm.shape_council_verdict_for_round(issue_number, next_round)
    if verdict is None:
        # No script for this round — fall through to production behavior.
        # Don't advance the counter so a partial script doesn't desync.
        return None
    counters[issue_number] = next_round

    panel_names = (
        ["Dissenter", "Consensus-Seeker", "Regret-in-6-Months"]
        if diversified
        else ["User Advocate", "Technical Lead", "Product Strategist"]
    )
    directions = ["A", "A", "A"] if verdict == "consensus" else ["A", "B", "C"]
    votes = [
        CouncilVote(
            expert_name=name,
            direction=direction,
            reasoning=f"Scripted round-{next_round} verdict: {verdict}",
            confidence=8,
        )
        for name, direction in zip(panel_names, directions, strict=True)
    ]
    return CouncilResult(votes)


class ExpertCouncil(BaseRunner):
    """Runs expert agents to vote on product directions."""

    _log = logger

    async def vote(self, task: Task, directions_text: str) -> CouncilResult:
        """Run all experts and collect votes on the proposed directions."""
        scripted = _consume_mockworld_council_vote(self, task.id, diversified=False)
        if scripted is not None:
            return scripted
        return await self._vote_with_panel(task, directions_text, EXPERTS)

    async def vote_diversified(self, task: Task, directions_text: str) -> CouncilResult:
        """Round-3 vote using diversified personas (ADR-0063 W4).

        Runs the :data:`DIVERSIFIED_EXPERTS` panel (Dissenter,
        Consensus-Seeker, Regret-in-6-Months) instead of the standard
        role-based panel. Called by :class:`ShapePhase._run_council_vote`
        only when the standard council remains split after two rounds.

        Returns a :class:`CouncilResult` using the same consensus rule
        (2/3 supermajority) as the standard vote, so the downstream
        consensus / escalate handling in :class:`ShapePhase` is unchanged.
        """
        scripted = _consume_mockworld_council_vote(self, task.id, diversified=True)
        if scripted is not None:
            return scripted
        return await self._vote_with_panel(task, directions_text, DIVERSIFIED_EXPERTS)

    async def _vote_with_panel(
        self, task: Task, directions_text: str, panel: list[dict]
    ) -> CouncilResult:
        """Run every expert in *panel* and collect their votes.

        Failures from individual experts are logged and skipped so a
        single crash never disqualifies the whole vote — matches the
        contract the standard ``vote`` had before extraction.
        ``reraise_on_credit_or_bug`` still propagates credit-exhaustion
        and Hydraflow-bug signals up to the caller per dark-factory
        rules.
        """
        votes: list[CouncilVote] = []
        for expert in panel:
            try:
                vote = await self._run_expert(task, expert, directions_text)
                if vote:
                    votes.append(vote)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Expert %s failed for #%d: %s",
                    expert["name"],
                    task.id,
                    exc,
                )
        return CouncilResult(votes)

    async def mediate(
        self, task: Task, prior_result: CouncilResult, directions_text: str
    ) -> str:
        """Run a mediator agent to reconcile a split council vote.

        Returns a mediation brief that identifies common ground, the core
        tension, and a proposed synthesis — injected into the revote prompt
        so experts can adjust their positions with full context.

        MockWorld bypass: when the runner carries a ``_mockworld_fake_llm``
        sentinel, the mediator is short-circuited to a fixed synthesis
        string so the round-2 revote happens without a subprocess. The
        round-2 verdict still comes from the scripted ``shape_council``
        map keyed by round number, so the scenario controls convergence.
        """
        fake_llm = getattr(self, "_mockworld_fake_llm", None)
        if fake_llm is not None and getattr(fake_llm, "_is_fake_adapter", False):
            return "Scripted mediation: experts hold their positions."
        vote_summary = prior_result.format_summary()
        cmd = self._build_command()
        prompt = f"""You are a neutral mediator reconciling a split product council vote.

## Issue #{task.id}: {task.title}

{task.body or "(No description)"}

## Proposed Directions

{directions_text}

## Council Votes (Split — No Consensus)

{vote_summary}

## Your Task

The council is split. Your job is NOT to pick a winner. Instead:

1. **Identify common ground** — What do the experts agree on? Which aspects
   of the problem do they see the same way?

2. **Name the core tension** — What is the fundamental disagreement? Is it
   about user needs, technical feasibility, or strategic priority?

3. **Propose a synthesis** — Can the best elements of the preferred directions
   be combined? Is there a hybrid that addresses each expert's concerns?

4. **Reframe the choice** — Present the decision in a way that makes the
   tradeoffs clearer. Sometimes a split means the options weren't framed well.

Write your mediation brief in 3-4 paragraphs. Be specific and constructive.
The experts will read this before revoting.
"""

        _MEDIATION_MARKER = "MEDIATION_END"

        def _check(acc: str) -> bool:
            return _MEDIATION_MARKER in acc or len(acc) > 3000

        try:
            transcript = await self._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "council-mediator"},
                on_output=_check,
            )
            # Extract the useful content (strip stream wrappers)
            from triage import TriageRunner  # noqa: PLC0415

            cleaned = TriageRunner._strip_system_lines(transcript)
            return cleaned.strip() or "Mediation produced no output."
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("Mediation failed for #%d: %s", task.id, exc)
            return "Mediation failed — proceeding with raw revote."

    async def _run_expert(
        self,
        task: Task,
        expert: dict,
        directions_text: str,
    ) -> CouncilVote | None:
        """Run a single expert vote."""
        cmd = self._build_command()
        prompt = self._build_vote_prompt(task, expert, directions_text)

        def _check_complete(accumulated: str) -> bool:
            return _VOTE_END in accumulated

        transcript = await self._execute(
            cmd,
            prompt,
            self._config.repo_root,
            {
                "issue": task.id,
                "source": f"council-{expert['name'].lower().replace(' ', '-')}",
            },
            on_output=_check_complete,
        )

        return self._parse_vote(transcript, expert["name"])

    def _build_command(self, _worktree_path=None) -> list[str]:  # type: ignore[override]
        return build_agent_command(
            tool=self._config.planner_tool,
            model=self._config.triage_model,  # Use fast model for voting
            disallowed_tools="Write,Edit,NotebookEdit",
            max_turns=1,
        )

    @staticmethod
    def _build_vote_prompt(task: Task, expert: dict, directions_text: str) -> str:
        return f"""You are the {expert["name"]} on a product council voting on the best direction for a product initiative.

## Your Perspective

{expert["perspective"]}

## Issue #{task.id}: {task.title}

{task.body or "(No description)"}

## Proposed Directions

{directions_text}

## Your Vote

Evaluate each direction from your perspective and cast your vote.

{_VOTE_START}

```json
{{
  "direction": "A",
  "reasoning": "2-3 sentences explaining why this direction is best from your perspective",
  "confidence": 8
}}
```

{_VOTE_END}

Rules:
- Vote for exactly ONE direction (A, B, C, etc.)
- Confidence is 1-10 (10 = absolutely certain, 1 = coin flip)
- Be honest about tradeoffs — don't just agree with the recommendation
- Your perspective may disagree with others — that's the point
"""

    @staticmethod
    def _parse_vote(transcript: str, expert_name: str) -> CouncilVote | None:
        start = transcript.find(_VOTE_START)
        end = transcript.find(_VOTE_END)
        if start == -1 or end == -1:
            return None

        section = transcript[start:end]
        match = re.search(r"```json\s*\n(.*?)\n```", section, re.DOTALL)
        if not match:
            return None

        try:
            data = json.loads(match.group(1))
            return CouncilVote(
                expert_name=expert_name,
                direction=str(data.get("direction", "")),
                reasoning=str(data.get("reasoning", "")),
                confidence=int(data.get("confidence", 5)),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.warning("Failed to parse council vote from %s", expert_name)
            return None
