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

    def to_dict(self) -> dict:
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

    def to_dict(self) -> dict:
        return {
            "votes": [v.to_dict() for v in self.votes],
            "consensus": self.has_consensus,
            "winner": self.winning_direction,
            "avg_confidence": self.avg_confidence,
            "timestamp": self.timestamp,
        }


class ExpertCouncil(BaseRunner):
    """Runs expert agents to vote on product directions."""

    _log = logger

    async def vote(self, task: Task, directions_text: str) -> CouncilResult:
        """Run all experts and collect votes on the proposed directions."""
        votes: list[CouncilVote] = []

        for expert in EXPERTS:
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
        """
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
