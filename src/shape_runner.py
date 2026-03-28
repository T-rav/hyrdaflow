"""Shape runner — multi-agent product direction generator."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from models import ProductDirection, ShapeResult
from phase_utils import reraise_on_credit_or_bug
from runner_constants import MEMORY_SUGGESTION_PROMPT

if TYPE_CHECKING:
    from models import Task

logger = logging.getLogger("hydraflow.shape")

_SHAPE_START = "SHAPE_START"
_SHAPE_END = "SHAPE_END"
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


class ShapeRunner(BaseRunner):
    """Launches a Claude agent to propose product directions via structured debate.

    The agent takes the discovery research brief and the original issue,
    then generates 3-5 product directions by considering multiple
    perspectives: user value, technical feasibility, market differentiation,
    and effort/risk tradeoffs.
    """

    _log = logger

    async def shape(
        self, task: Task, research_brief: str = "", worker_id: int = 0
    ) -> ShapeResult:
        """Generate product direction options for *task*.

        Returns a :class:`ShapeResult` with proposed directions.
        """
        result = ShapeResult(issue_number=task.id)
        transcript = ""

        if self._config.dry_run:
            logger.info("[dry-run] Would run shaping for issue #%d", task.id)
            return result

        try:
            cmd = self._build_command()

            # --- Pass 1: Advocate — generate initial directions ---
            advocate_prompt = self._build_advocate_prompt(task, research_brief)

            def _check_complete(accumulated: str) -> bool:
                if _SHAPE_END in accumulated:
                    logger.info(
                        "Shape markers found for issue #%d — terminating",
                        task.id,
                    )
                    return True
                return False

            advocate_transcript = await self._execute(
                cmd,
                advocate_prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "shape-advocate"},
                on_output=_check_complete,
            )

            advocate_result = self._extract_result(advocate_transcript, task.id)

            if not advocate_result or not advocate_result.directions:
                transcript = advocate_transcript
                result.recommendation = (
                    "Shape advocate agent produced no structured output. "
                    "Manual direction selection required."
                )
            else:
                # --- Pass 2: Critic — challenge and refine directions ---
                critic_prompt = self._build_critic_prompt(
                    task, advocate_result, research_brief
                )
                critic_transcript = await self._execute(
                    cmd,
                    critic_prompt,
                    self._config.repo_root,
                    {"issue": task.id, "source": "shape-critic"},
                    on_output=_check_complete,
                )
                transcript = (
                    advocate_transcript + "\n\n---CRITIC---\n\n" + critic_transcript
                )

                critic_result = self._extract_result(critic_transcript, task.id)
                # Use critic's refined output if available, otherwise advocate's
                result = critic_result if critic_result else advocate_result

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.recommendation = f"Shaping failed: {exc!r}"
            logger.exception(
                "Shaping failed for issue #%d: %s",
                task.id,
                exc,
                extra={"issue": task.id},
            )

        try:
            self._save_transcript("shape-issue", task.id, transcript)
        except OSError:
            logger.warning(
                "Failed to save shape transcript for issue #%d",
                task.id,
                exc_info=True,
            )

        return result

    def _build_command(self, _worktree_path=None) -> list[str]:  # type: ignore[override]
        """Construct the CLI invocation for product shaping."""
        return build_agent_command(
            tool=self._config.planner_tool,
            model=self._config.planner_model,
            disallowed_tools="Write,Edit,NotebookEdit",
        )

    def _build_advocate_prompt(self, task: Task, research_brief: str = "") -> str:
        """Build the multi-perspective shaping prompt."""
        research_section = ""
        if research_brief:
            research_section = f"""
## Discovery Research Brief

The following research was gathered during the discovery phase:

{research_brief}

Use this research to inform your direction proposals. Do NOT repeat it.
"""

        return f"""You are a product strategist proposing directions for a product initiative.

## Issue #{task.id}: {task.title}

{task.body or "(No description provided)"}
{research_section}
## Your Mission

Propose 3-5 distinct product DIRECTIONS — not features, not specs, but
strategic approaches to solving the underlying problem. Each direction
represents a fundamentally different way to address the user need.

## Multi-Perspective Analysis

For each direction you propose, evaluate it from these perspectives:

1. **User Advocate**: Does this genuinely solve the user's core pain point?
   How delightful is the experience? What friction remains?

2. **Technical Realist**: How complex is this to build? What are the hard
   technical problems? What existing infrastructure can we leverage?

3. **Market Strategist**: How does this differentiate from competitors?
   Is there a defensible advantage? Will this matter in 12 months?

4. **Scope Hawk**: What is the MVP version? What can be cut without
   losing the core value proposition? What's v2 vs v1?

## Required Output

Output your directions between these exact markers in a JSON code block:

{_SHAPE_START}

```json
{{
  "issue_number": {task.id},
  "directions": [
    {{
      "name": "Short descriptive name",
      "approach": "2-3 sentence description of the strategic approach",
      "tradeoffs": "Key tradeoffs — what you gain and what you give up",
      "effort": "low|medium|high",
      "risk": "low|medium|high",
      "differentiator": "What makes this direction stand out vs alternatives"
    }}
  ],
  "recommendation": "Which direction you'd recommend and why (1-2 sentences)"
}}
```

{_SHAPE_END}

## Guidelines

- Each direction should be MEANINGFULLY DIFFERENT, not variations of the same idea
- Be concrete about tradeoffs — every direction has real costs
- effort/risk should be honest assessments, not optimistic guesses
- The recommendation should explain the reasoning, not just pick one
- If the research brief identified specific user needs or market gaps,
  at least one direction should directly address those

{MEMORY_SUGGESTION_PROMPT}
"""

    def _build_critic_prompt(
        self, task: Task, advocate_result: ShapeResult, research_brief: str = ""
    ) -> str:
        """Build the critic prompt that challenges and refines advocate directions."""
        directions_text = ""
        for i, d in enumerate(advocate_result.directions):
            letter = chr(65 + i)
            directions_text += (
                f"\n### Direction {letter}: {d.name}\n"
                f"**Approach:** {d.approach}\n"
                f"**Tradeoffs:** {d.tradeoffs}\n"
                f"**Effort:** {d.effort} | **Risk:** {d.risk}\n"
                f"**Differentiator:** {d.differentiator}\n"
            )

        research_section = ""
        if research_brief:
            research_section = f"\n## Original Research Brief\n\n{research_brief}\n"

        return f"""You are a product strategy CRITIC reviewing proposed directions for a product initiative.

## Issue #{task.id}: {task.title}

{task.body or "(No description provided)"}
{research_section}
## Proposed Directions (from Advocate Agent)

{directions_text}

Advocate's recommendation: {advocate_result.recommendation}

## Your Mission

You are the SECOND pass in a two-agent debate. The Advocate above proposed directions.
Your job is to CHALLENGE, REFINE, and IMPROVE them:

1. **Kill weak directions** — If a direction is poorly differentiated, unrealistic,
   or a variation of another, remove it and replace with something genuinely different.

2. **Strengthen survivors** — For directions worth keeping, make the tradeoffs more
   honest, the effort/risk assessments more realistic, and the approach more specific.

3. **Challenge the recommendation** — Is the advocate's recommendation actually the
   best choice? Argue for a different one if warranted.

4. **Add what's missing** — If the advocate missed an obvious direction (especially
   one suggested by the research), add it.

5. **Be adversarial but constructive** — Your goal is better directions, not fewer.

## Required Output

Output your REFINED directions (keep, modify, replace, or add) using the same
format between these markers:

{_SHAPE_START}

```json
{{
  "issue_number": {task.id},
  "directions": [
    {{
      "name": "Short descriptive name",
      "approach": "2-3 sentence description",
      "tradeoffs": "Honest tradeoffs",
      "effort": "low|medium|high",
      "risk": "low|medium|high",
      "differentiator": "What makes this stand out"
    }}
  ],
  "recommendation": "Your recommendation after critique (may differ from advocate)"
}}
```

{_SHAPE_END}

{MEMORY_SUGGESTION_PROMPT}
"""

    def _extract_result(self, transcript: str, issue_number: int) -> ShapeResult | None:
        """Extract structured ShapeResult from agent transcript."""
        start_idx = transcript.find(_SHAPE_START)
        end_idx = transcript.find(_SHAPE_END)
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            return None

        section = transcript[start_idx:end_idx]
        match = _JSON_BLOCK_RE.search(section)
        if not match:
            return None

        try:
            data = json.loads(match.group(1))
            directions = []
            for d in data.get("directions", []):
                directions.append(
                    ProductDirection(
                        name=d.get("name", "Unnamed"),
                        approach=d.get("approach", ""),
                        tradeoffs=d.get("tradeoffs", ""),
                        effort=d.get("effort", "unknown"),
                        risk=d.get("risk", "unknown"),
                        differentiator=d.get("differentiator", ""),
                    )
                )
            return ShapeResult(
                issue_number=issue_number,
                directions=directions,
                recommendation=data.get("recommendation", ""),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning(
                "Failed to parse shape JSON for issue #%d",
                issue_number,
                exc_info=True,
            )
            return None
