"""Discover runner — product research agent for vague/broad issues."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from models import DiscoverResult
from phase_utils import reraise_on_credit_or_bug
from runner_constants import MEMORY_SUGGESTION_PROMPT

if TYPE_CHECKING:
    from models import Task

logger = logging.getLogger("hydraflow.discover")

# Markers for extracting structured output from transcript
_DISCOVER_START = "DISCOVER_START"
_DISCOVER_END = "DISCOVER_END"
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


class DiscoverRunner(BaseRunner):
    """Launches a Claude agent to research the product space for a vague issue.

    Unlike the research runner (which explores the codebase), this runner
    explores the external product landscape: competitors, user needs,
    market gaps, and opportunities. It uses web search tools to gather
    real-world data and synthesizes findings into a structured brief.
    """

    _log = logger

    async def discover(self, task: Task, worker_id: int = 0) -> DiscoverResult:
        """Run product discovery research for *task*.

        Returns a :class:`DiscoverResult` with research findings.
        """
        result = DiscoverResult(issue_number=task.id)
        transcript = ""

        if self._config.dry_run:
            logger.info("[dry-run] Would run discovery for issue #%d", task.id)
            result.research_brief = "Dry-run: discovery skipped"
            return result

        try:
            cmd = self._build_command()
            prompt = self._build_prompt(task)

            def _check_complete(accumulated: str) -> bool:
                if _DISCOVER_END in accumulated:
                    logger.info(
                        "Discovery markers found for issue #%d — terminating",
                        task.id,
                    )
                    return True
                return False

            transcript = await self._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "discover"},
                on_output=_check_complete,
            )

            parsed = self._extract_result(transcript, task.id)
            if parsed:
                result = parsed
            else:
                # Fallback: use raw transcript as research brief
                result.research_brief = self._extract_raw_brief(transcript)
                if not result.research_brief:
                    result.research_brief = (
                        "Discovery agent ran but produced no structured output. "
                        "Raw transcript available in logs."
                    )

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.research_brief = f"Discovery failed: {exc!r}"
            logger.exception(
                "Discovery failed for issue #%d: %s",
                task.id,
                exc,
                extra={"issue": task.id},
            )

        try:
            self._save_transcript("discover-issue", task.id, transcript)
        except OSError:
            logger.warning(
                "Failed to save discovery transcript for issue #%d",
                task.id,
                exc_info=True,
            )

        return result

    def _build_command(self, _worktree_path=None) -> list[str]:  # type: ignore[override]
        """Construct the CLI invocation for product discovery."""
        return build_agent_command(
            tool=self._config.planner_tool,
            model=self._config.planner_model,
            # Discovery needs web search but no file editing
            disallowed_tools="Write,Edit,NotebookEdit",
        )

    def _build_prompt(self, task: Task) -> str:
        """Build the product discovery prompt for *task*."""
        return f"""You are a product discovery agent researching the problem space for a GitHub issue.

## Issue #{task.id}: {task.title}

{task.body or "(No description provided)"}

## Your Mission

This is a VAGUE or BROAD product request. Your job is NOT to plan implementation.
Your job is to research the external product landscape and produce a structured
brief that will inform product direction decisions.

## Research Strategy

1. **Understand the intent** — What is the user really asking for? What problem
   are they trying to solve? Restate the core need.

2. **Competitive landscape** — Use web search to find existing products, tools,
   and solutions in this space. For each competitor, note:
   - Name and URL
   - Key features and approach
   - Strengths and weaknesses
   - Pricing model (if relevant)

3. **User needs & pain points** — Research what users say about existing
   solutions. Look for:
   - Common complaints in reviews (G2, Capterra, Reddit, HN)
   - Feature requests and wishlists
   - Unserved or underserved user segments

4. **Market gaps & opportunities** — Based on your research, identify:
   - What existing solutions do poorly
   - User needs that aren't addressed
   - Emerging trends or shifts in the space
   - Differentiation opportunities

5. **Technical landscape** — Note any relevant:
   - Open source alternatives or building blocks
   - APIs or services that could accelerate development
   - Technical constraints or considerations

## Required Output

Output your findings between these exact markers in a JSON code block:

{_DISCOVER_START}

```json
{{
  "issue_number": {task.id},
  "research_brief": "A 2-3 paragraph executive summary of your findings",
  "competitors": ["Competitor 1 — brief description", "Competitor 2 — brief description"],
  "user_needs": ["Need 1 — evidence/source", "Need 2 — evidence/source"],
  "opportunities": ["Opportunity 1 — why this is viable", "Opportunity 2 — why this is viable"]
}}
```

{_DISCOVER_END}

## IMPORTANT — Research Quality

- FIRST, check if you have WebSearch and WebFetch tools available.
  - If YES: Use them to gather REAL data. Cite sources.
  - If NO: Explicitly state "NOTE: Web search tools unavailable. Analysis
    below is based on general knowledge, not live research. Verify findings
    before making product decisions." Then provide your best analysis from
    training data, clearly marking it as unverified.
- Focus on actionable insights, not exhaustive lists.
- If the issue domain is too niche for web research, note that and focus on
  what you CAN determine from the issue description and general knowledge.

{MEMORY_SUGGESTION_PROMPT}
"""

    def _extract_result(
        self, transcript: str, issue_number: int
    ) -> DiscoverResult | None:
        """Extract structured DiscoverResult from agent transcript."""
        # Find content between markers
        start_idx = transcript.find(_DISCOVER_START)
        end_idx = transcript.find(_DISCOVER_END)
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            return None

        section = transcript[start_idx:end_idx]

        # Extract JSON block
        match = _JSON_BLOCK_RE.search(section)
        if not match:
            return None

        try:
            data = json.loads(match.group(1))
            return DiscoverResult(
                issue_number=issue_number,
                research_brief=data.get("research_brief", ""),
                competitors=data.get("competitors", []),
                user_needs=data.get("user_needs", []),
                opportunities=data.get("opportunities", []),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning(
                "Failed to parse discovery JSON for issue #%d",
                issue_number,
                exc_info=True,
            )
            return None

    def _extract_raw_brief(self, transcript: str) -> str:
        """Extract a usable brief from raw transcript when JSON parsing fails."""
        start_idx = transcript.find(_DISCOVER_START)
        end_idx = transcript.find(_DISCOVER_END)
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            raw = transcript[start_idx + len(_DISCOVER_START) : end_idx].strip()
            # Remove JSON blocks, keep any plain text
            raw = _JSON_BLOCK_RE.sub("", raw).strip()
            if raw:
                return raw
        return ""
