"""Discover runner — product research agent for vague/broad issues."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from exception_classify import reraise_on_credit_or_bug
from models import DiscoverResult
from plugin_skill_registry import (
    discover_plugin_skills,
    format_plugin_skills_for_prompt,
    skills_for_phase,
)
from runner_constants import MEMORY_SUGGESTION_PROMPT
from skill_registry import BUILTIN_SKILLS

if TYPE_CHECKING:
    from dedup_store import DedupStore
    from models import Task
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.discover")

# Markers for extracting structured output from transcript
_DISCOVER_START = "DISCOVER_START"
_DISCOVER_END = "DISCOVER_END"
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)

# Evaluator skill + escalation label constants (§4.10)
_SKILL_NAME = "discover-completeness"
_ESCALATION_LABEL_STUCK = "discover-stuck"
_ESCALATION_LABEL_HITL = "hitl-escalation"


class DiscoverRunner(BaseRunner):
    """Launches a Claude agent to research the product space for a vague issue.

    Unlike the research runner (which explores the codebase), this runner
    explores the external product landscape: competitors, user needs,
    market gaps, and opportunities. It uses web search tools to gather
    real-world data and synthesizes findings into a structured brief.
    """

    _log = logger

    def bind_escalation_deps(
        self, prs: PRManager, dedup: DedupStore | None = None
    ) -> None:
        """Wire issue-filing + dedup deps used by evaluator escalation.

        Called by :class:`DiscoverPhase` after construction. Without
        binding, escalation logs a warning and returns — evaluator
        dispatch and bounded retry still run.
        """
        self._prs = prs
        self._dedup = dedup

    async def discover(self, task: Task, worker_id: int = 0) -> DiscoverResult:
        """Run product discovery with post-output evaluation (§4.10).

        When ``config.max_discover_attempts > 0`` the runner evaluates
        each produced brief via the ``discover-completeness`` skill; on
        RETRY it re-runs discovery up to the budget, then escalates via
        ``hitl-escalation`` / ``discover-stuck`` and returns the last
        (best-available) brief so the phase can still post a comment.
        """
        result = DiscoverResult(issue_number=task.id)
        if self._config.dry_run:
            logger.info("[dry-run] Would run discovery for issue #%d", task.id)
            result.research_brief = "Dry-run: discovery skipped"
            return result

        max_attempts = max(1, self._config.max_discover_attempts or 1)
        evaluator_enabled = self._config.max_discover_attempts > 0
        last_summary = ""
        last_findings: list[str] = []
        for attempt in range(1, max_attempts + 1):
            result = await self._run_discovery_once(task, attempt)
            if not evaluator_enabled:
                return result
            passed, summary, findings = await self._evaluate_brief(
                task, result.research_brief
            )
            last_summary, last_findings = summary, findings
            if passed:
                return result
            logger.warning(
                "Discover brief rejected for #%d attempt %d/%d: %s",
                task.id,
                attempt,
                max_attempts,
                summary,
            )
        await self._escalate_stuck(task, last_summary, last_findings, max_attempts)
        return result

    async def _run_discovery_once(self, task: Task, attempt: int) -> DiscoverResult:
        """Run a single discovery pass — produces one :class:`DiscoverResult`.

        Factored from the original single-shot ``discover`` body so the
        outer loop can invoke it once per attempt.
        """
        result = DiscoverResult(issue_number=task.id)
        transcript = ""

        try:
            cmd = self._build_command()
            prompt = self._build_prompt(task)

            # Inject memory context (prior learnings, ADRs, retrospectives)
            memory_section = await self._inject_memory(
                query_context=f"product discovery for {task.title} {(task.body or '')[:200]}",
            )
            if memory_section:
                prompt += (
                    f"\n\n## Existing System Knowledge\n\n"
                    f"Prior learnings, architecture decisions, and retrospectives "
                    f"relevant to this discovery. Use this to ground your research "
                    f"in what the team already knows."
                    f"{memory_section}"
                )

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
                {"issue": task.id, "source": f"discover:attempt-{attempt}"},
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
            self._save_transcript(
                f"discover-issue-attempt{attempt}", task.id, transcript
            )
        except OSError:
            logger.warning(
                "Failed to save discovery transcript for issue #%d",
                task.id,
                exc_info=True,
            )

        return result

    async def _evaluate_brief(
        self, task: Task, brief: str
    ) -> tuple[bool, str, list[str]]:
        """Dispatch ``discover-completeness`` against *brief*.

        A missing skill (registry disabled) fails open so this extension
        never blocks discovery on its own absence.
        """
        skill = next((s for s in BUILTIN_SKILLS if s.name == _SKILL_NAME), None)
        if skill is None:
            return True, f"{_SKILL_NAME} not registered — fail open", []
        prompt = skill.prompt_builder(
            issue_number=task.id,
            issue_title=task.title,
            issue_body=task.body or "",
            brief=brief or "",
        )
        try:
            transcript = await self._execute(
                self._build_command(),
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "discover:evaluator"},
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "discover-completeness dispatch failed for #%d: %s", task.id, exc
            )
            return True, f"evaluator dispatch failed: {exc!r}", []
        return skill.result_parser(transcript)

    async def _escalate_stuck(
        self, task: Task, summary: str, findings: list[str], attempts: int
    ) -> None:
        """File hitl-escalation / discover-stuck with dedup.

        Dedup key ``discover_runner:{task.id}`` in the shared
        ``hitl_escalations`` set. Closing the escalation issue clears
        the key (per §3.2) so the runner can retry on the next cycle.
        """
        prs: PRManager | None = getattr(self, "_prs", None)
        dedup: DedupStore | None = getattr(self, "_dedup", None)
        key = f"discover_runner:{task.id}"
        if dedup is not None and key in dedup.get():
            logger.info("discover-stuck for #%d already filed (dedup)", task.id)
            return
        if prs is None:
            logger.warning(
                "discover-stuck for #%d but PRManager not bound; logging only. "
                "attempts=%d summary=%s",
                task.id,
                attempts,
                summary,
            )
            return
        body_lines = [
            f"Discover-completeness evaluator rejected {attempts} bounded "
            f"retries for issue #{task.id}.",
            "",
            f"**Last summary:** {summary}",
        ]
        if findings:
            body_lines.append("")
            body_lines.append("**Last findings:**")
            for finding in findings[:10]:
                body_lines.append(f"- {finding}")
        body_lines += [
            "",
            "Action: a human must review the issue body, clarify the "
            "ambiguity that blocked the brief, and either retry Discover "
            "manually or accept the current brief. Closing this issue "
            "clears the dedup key so the runner can retry.",
        ]
        issue_number = await prs.create_issue(
            title=f"[discover-stuck] #{task.id} — {task.title}",
            body="\n".join(body_lines),
            labels=[_ESCALATION_LABEL_HITL, _ESCALATION_LABEL_STUCK],
        )
        if issue_number and dedup is not None:
            dedup.add(key)
            logger.info(
                "Filed discover-stuck escalation #%d for task #%d",
                issue_number,
                task.id,
            )

    def _build_command(self, _worktree_path=None) -> list[str]:  # type: ignore[override]
        """Construct the CLI invocation for product discovery.

        Uses the planner model (opus) for deep thinking — discovery
        needs thorough reasoning, not fast classification.
        """
        return build_agent_command(
            tool=self._config.planner_tool,
            model=self._config.planner_model,
            disallowed_tools="Write,Edit,NotebookEdit",
            effort="max",
        )

    def _build_prompt(self, task: Task) -> str:
        """Build the product discovery prompt with deep product thinking frameworks."""
        prompt = f"""You are a senior product strategist conducting deep discovery research.
Think through the tradeoffs carefully before producing your analysis.

## Issue #{task.id}: {task.title}

{task.body or "(No description provided)"}

## Your Mission

This is a BROAD product request. Your job is NOT to plan implementation.
Your job is to produce a BEST-IN-CLASS product discovery brief — the kind
a top PM at Stripe or Figma would produce before committing to a direction.

## Deep Discovery Framework

Work through each step with genuine depth. Don't just list things — analyze.

### Step 1: Problem Decomposition (Jobs-to-be-Done)

Before researching solutions, deeply understand the PROBLEM:
- What is the core job the user is trying to get done?
- What are the functional, emotional, and social dimensions?
- What are the "struggling moments" — when does the current approach fail?
- What would "perfect" look like from the user's perspective?
- Who are the different user personas and how do their needs differ?

### Step 2: Competitive Landscape (use WebSearch)

Research existing solutions thoroughly. For each significant competitor:
- **What they do well** — their core insight or innovation
- **Where they fall short** — genuine weaknesses, not just "could be better"
- **Their positioning** — who they serve and how they talk about it
- **Business model** — how they monetize (impacts what they prioritize)
- **User sentiment** — search for reviews on G2, Capterra, Reddit, HN, Twitter

Don't just list competitors. Identify the **strategic gaps** — what is
NOBODY doing well? Where is the market underserved?

### Step 3: Design Thinking — User Journey Analysis

Map the end-to-end user experience in this problem space:
- What triggers the user to seek a solution?
- What is their current workflow (even if manual/hacky)?
- Where are the friction points and drop-off moments?
- What delights them in existing solutions?
- What would a 10x better experience look like?

### Step 4: Market & Timing Analysis

Think about WHY NOW:
- What has changed that creates a new opportunity?
- Technology shifts (new APIs, AI capabilities, platform changes)?
- Market shifts (remote work, regulatory changes, user expectations)?
- What's the window of opportunity?

### Step 5: Technical Feasibility Scan

Use Glob/Grep/Read to explore the CODEBASE for:
- What existing infrastructure could be leveraged?
- What patterns and conventions already exist?
- What would be hard vs easy to build given the current architecture?

### Step 6: Opportunity Synthesis

Synthesize everything above into clear, actionable opportunities.
Each opportunity should be:
- **Specific** — not "make it better" but "solve group scheduling for teams of 5-15"
- **Differentiated** — why this angle vs what exists
- **Feasible** — grounded in what can actually be built
- **Impactful** — addresses a real pain point with evidence

## Required Output

{_DISCOVER_START}

```json
{{
  "issue_number": {task.id},
  "research_brief": "3-4 paragraph executive summary: problem insight, market landscape, key opportunities, and recommended focus areas",
  "competitors": ["Competitor — what they do, their core strength, and their key weakness"],
  "user_needs": ["Need — evidence from research, affected persona, severity"],
  "opportunities": ["Opportunity — why viable, differentiation angle, feasibility assessment"]
}}
```

{_DISCOVER_END}

## Research Quality Standards

- FIRST, check if you have WebSearch and WebFetch tools available.
  - If YES: Use them extensively. Cite sources. Research at least 5 competitors.
  - If NO: State "NOTE: Web search unavailable — analysis based on general knowledge.
    Verify before making decisions." Still apply the frameworks above deeply.
- Use Glob/Grep/Read to explore the codebase for technical feasibility.
- Quality over quantity — 3 deep insights beat 10 shallow bullet points.
- Challenge your own assumptions — what could you be wrong about?

{MEMORY_SUGGESTION_PROMPT}
"""
        plugin_skills_section = format_plugin_skills_for_prompt(
            skills_for_phase(
                "discover",
                discover_plugin_skills(self._config.required_plugins),
                self._config.phase_skills,
            )
        )
        if plugin_skills_section:
            prompt = f"{prompt}\n\n{plugin_skills_section}"
        return prompt

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
