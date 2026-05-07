"""Shape runner — turn-based product design conversation agent."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from exception_classify import reraise_on_credit_or_bug
from models import ProductDirection, ShapeConversation, ShapeResult, ShapeTurnResult
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

logger = logging.getLogger("hydraflow.shape")

_SHAPE_CONTINUE = "SHAPE_CONTINUE"
_SHAPE_CONTINUE_END = "SHAPE_CONTINUE_END"
_SHAPE_FINALIZE = "SHAPE_FINALIZE"
_SHAPE_FINALIZE_END = "SHAPE_FINALIZE_END"
# Legacy markers for backward compatibility with extract_result
_SHAPE_START = "SHAPE_START"
_SHAPE_END = "SHAPE_END"
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)

# Evaluator skill name (§4.10)
_SKILL_NAME = "shape-coherence"


class ShapeRunner(BaseRunner):
    """Turn-based product design conversation agent.

    Each call to ``run_turn`` is a single agent invocation with the full
    conversation history injected. The agent adapts its behavior based on
    turn count: explore broadly early, crystallize late.
    """

    _log = logger

    def bind_escalation_deps(
        self, prs: PRManager, dedup: DedupStore | None = None
    ) -> None:
        """Wire issue-filing + dedup deps used by evaluator escalation.

        Called by :class:`ShapePhase` after construction. Without
        binding, escalation logs a warning and returns — evaluator
        dispatch and bounded retry still run.
        """
        self._prs = prs
        self._dedup = dedup

    async def run_turn(
        self,
        task: Task,
        conversation: ShapeConversation,
        research_brief: str = "",
        learned_preferences: str = "",
    ) -> ShapeTurnResult:
        """Run a single conversation turn with post-finalize evaluation (§4.10).

        Non-final turns (continue/explore) bypass the ``shape-coherence``
        evaluator — rubric criteria 1–4 only apply to a finalized
        proposal with options. When ``is_final`` is set, the runner
        evaluates the content; on RETRY it re-runs the SAME turn up to
        ``config.max_shape_attempts`` before escalating.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would run shape turn for issue #%d", task.id)
            result = ShapeTurnResult()
            result.content = "Dry-run: shape turn skipped"
            return result

        max_attempts = max(1, self._config.max_shape_attempts or 1)
        evaluator_enabled = self._config.max_shape_attempts > 0
        last_summary = ""
        last_findings: list[str] = []
        result = ShapeTurnResult()
        for attempt in range(1, max_attempts + 1):
            result = await self._run_turn_once(
                task, conversation, research_brief, learned_preferences, attempt
            )
            if not result.is_final or not evaluator_enabled:
                return result
            passed, summary, findings = await self._evaluate_proposal(
                task, research_brief, result.content
            )
            last_summary, last_findings = summary, findings
            if passed:
                return result
            logger.warning(
                "Shape proposal rejected for #%d attempt %d/%d: %s",
                task.id,
                attempt,
                max_attempts,
                summary,
            )
        await self._escalate_stuck(task, last_summary, last_findings, max_attempts)
        return result

    async def _run_turn_once(
        self,
        task: Task,
        conversation: ShapeConversation,
        research_brief: str,
        learned_preferences: str,
        attempt: int,
    ) -> ShapeTurnResult:
        """Run a single conversation turn — one agent invocation.

        Factored from the original single-shot ``run_turn`` body so the
        outer loop can invoke it once per attempt.
        """
        result = ShapeTurnResult()

        try:
            cmd = self._build_command()

            # Inject compressed memory context (ADRs, learnings, retrospectives)
            memory_section = await self._inject_memory(
                query_context=f"product shaping for {task.title} {(task.body or '')[:200]}",
            )
            if memory_section and not learned_preferences:
                # Memory section serves as learned preferences if none provided
                learned_preferences = memory_section

            prompt = self._build_turn_prompt(
                task, conversation, research_brief, learned_preferences
            )

            def _check_complete(accumulated: str) -> bool:
                if (
                    _SHAPE_CONTINUE_END in accumulated
                    or _SHAPE_FINALIZE_END in accumulated
                ):
                    return True
                # Legacy marker support
                return _SHAPE_END in accumulated

            transcript = await self._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": f"shape:attempt-{attempt}"},
                on_output=_check_complete,
            )
            result.transcript = transcript

            # Check for finalization first
            finalize_content = self._extract_between(
                transcript, _SHAPE_FINALIZE, _SHAPE_FINALIZE_END
            )
            if finalize_content:
                result.content = finalize_content
                result.is_final = True
            else:
                # Check for continue
                continue_content = self._extract_between(
                    transcript, _SHAPE_CONTINUE, _SHAPE_CONTINUE_END
                )
                if continue_content:
                    result.content = continue_content
                else:
                    # Fallback: use everything after the last prompt marker
                    result.content = self._extract_fallback(transcript)

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.content = f"Shape turn failed: {exc!r}"
            logger.exception(
                "Shape turn failed for issue #%d: %s",
                task.id,
                exc,
                extra={"issue": task.id},
            )

        try:
            turn_num = len(conversation.turns) + 1
            self._save_transcript(
                f"shape-issue-turn{turn_num}-attempt{attempt}",
                task.id,
                result.transcript,
            )
        except OSError:
            logger.warning(
                "Failed to save shape transcript for issue #%d",
                task.id,
                exc_info=True,
            )

        return result

    async def _evaluate_proposal(
        self, task: Task, discover_brief: str, proposal: str
    ) -> tuple[bool, str, list[str]]:
        """Dispatch ``shape-coherence`` against *proposal*.

        A missing skill (registry disabled) fails open so this extension
        never blocks shaping on its own absence.
        """
        skill = next((s for s in BUILTIN_SKILLS if s.name == _SKILL_NAME), None)
        if skill is None:
            return True, f"{_SKILL_NAME} not registered — fail open", []
        prompt = skill.prompt_builder(
            issue_number=task.id,
            issue_title=task.title,
            discover_brief=discover_brief or "",
            proposal=proposal or "",
        )
        try:
            transcript = await self._execute(
                self._build_command(),
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "shape:evaluator"},
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("shape-coherence dispatch failed for #%d: %s", task.id, exc)
            return True, f"evaluator dispatch failed: {exc!r}", []
        return skill.result_parser(transcript)

    async def _escalate_stuck(
        self, task: Task, summary: str, findings: list[str], attempts: int
    ) -> None:
        """File hitl-escalation / shape-stuck with dedup.

        Dedup key ``shape_runner:{task.id}`` in the shared
        ``hitl_escalations`` set. Closing the escalation issue clears
        the key (per §3.2) so the runner can retry on the next cycle.
        """
        prs: PRManager | None = getattr(self, "_prs", None)
        dedup: DedupStore | None = getattr(self, "_dedup", None)
        key = f"shape_runner:{task.id}"
        if dedup is not None and key in dedup.get():
            logger.info("shape-stuck for #%d already filed (dedup)", task.id)
            return
        if prs is None:
            logger.warning(
                "shape-stuck for #%d but PRManager not bound; logging only. "
                "attempts=%d summary=%s",
                task.id,
                attempts,
                summary,
            )
            return
        body_lines = [
            f"Shape-coherence evaluator rejected {attempts} bounded "
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
            "Action: a human must review the shaping output, reconcile "
            "the overlap/gap the evaluator flagged, and either retry "
            "Shape manually or accept the current proposal. Closing "
            "this issue clears the dedup key so the runner can retry.",
        ]
        issue_number = await prs.create_issue(
            title=f"[shape-stuck] #{task.id} — {task.title}",
            body="\n".join(body_lines),
            labels=[
                self._config.hitl_escalation_label[0],
                self._config.shape_stuck_label[0],
            ],
        )
        if issue_number and dedup is not None:
            dedup.add(key)
            logger.info(
                "Filed shape-stuck escalation #%d for task #%d",
                issue_number,
                task.id,
            )

    def _build_command(self, _worktree_path=None) -> list[str]:  # type: ignore[override]
        """Construct the CLI invocation for product shaping.

        Shape agents can read the codebase (Glob, Grep, Read) and search
        the web (WebSearch, WebFetch) but cannot modify files.
        """
        return build_agent_command(
            tool=self._config.planner_tool,
            model=self._config.planner_model,
            disallowed_tools="Write,Edit,NotebookEdit",
            effort="high",
        )

    def _build_turn_prompt(
        self,
        task: Task,
        conversation: ShapeConversation,
        research_brief: str = "",
        learned_preferences: str = "",
    ) -> str:
        """Build the conversation-aware prompt for this turn."""
        turn_count = len(conversation.turns)

        # Format conversation history
        history = ""
        if conversation.turns:
            history_parts = []
            for i, turn in enumerate(conversation.turns):
                role_label = "Design Agent" if turn.role == "agent" else "Product Owner"
                history_parts.append(f"### Turn {i + 1} — {role_label}\n{turn.content}")
            history = "\n\n".join(history_parts)

        # Research context (only on first turn)
        research_section = ""
        if research_brief and turn_count == 0:
            research_section = f"""
## Discovery Research Brief

{research_brief}

Use this research to inform your thinking. Do NOT repeat it verbatim.
"""

        # Learned preferences and cross-issue context (only on first turn)
        preference_section = ""
        if learned_preferences and turn_count == 0:
            preference_section = f"""
## Learned Preferences & Related Decisions

Based on prior product decisions by this user:

{learned_preferences}

Use these to inform your recommendations, but don't constrain your exploration.
If any prior decisions are directly related to this issue, call out the
connection and explain how this work should align or differ.
"""

        # Adaptive instructions based on turn count
        if turn_count == 0:
            phase_instruction = """## First Turn — Explore Broadly

Present 3-5 distinct product DIRECTIONS. Not features, not specs — strategic
approaches. Each direction should be meaningfully different.

For each direction, evaluate from four lenses:
- **User Advocate**: Does this solve the real pain point?
- **Technical Realist**: How complex to build? Use Glob and Grep to explore
  the codebase and assess what exists, what can be reused, and what's hard.
- **Market Strategist**: What's the differentiation?
- **Scope Hawk**: What's the MVP?

For UI-heavy directions, sketch the key user flows:
- Describe the screens/views the user would see
- Note the primary actions and transitions
- Call out where the UX is novel vs. standard patterns"""
        elif turn_count < 5:
            phase_instruction = """## Refinement Phase

The product owner is guiding the conversation. Your job:
- Go deeper on directions they find interesting
- Combine ideas they suggest
- Explore angles they ask about — if they mention a competitor or concept,
  USE WebSearch to research it in real time and bring back specifics
- Be specific about UX, scope, and implementation details
- If they seem interested in a direction, flesh it out more
- Use Glob/Grep/Read to check the codebase when assessing feasibility
- For UI directions, describe the user flow step by step"""
        else:
            phase_instruction = """## Crystallization Phase

We're deep in the conversation. Time to converge:
- Synthesize what the product owner has expressed
- Propose a clear, specific direction based on the conversation
- If they haven't narrowed down, recommend your best option with reasoning
- Be ready to finalize if they agree
- Include concrete UX flow descriptions for the chosen direction"""

        # History section
        history_section = ""
        if history:
            history_section = f"""
## Conversation So Far

{history}
"""

        prompt = f"""You are a product design agent having a conversation about GitHub issue #{task.id}.

## Issue: {task.title}

{task.body or "(No description provided)"}
{research_section}{preference_section}{history_section}
{phase_instruction}

## How to Respond

If you want to continue the conversation (present options, ask a question,
explore an angle, go deeper on a direction):

{_SHAPE_CONTINUE}
Your response here. Be conversational, specific, and helpful.
Ask questions if you need clarity. Present options clearly.
{_SHAPE_CONTINUE_END}

If the product owner has given a clear signal and you're ready to produce
a final specification for the engineering team:

{_SHAPE_FINALIZE}
## Final Product Direction

**Problem**: What we're solving
**Approach**: The chosen direction and why
**Scope**: What's in and what's explicitly out
**Success criteria**: How we'll know it worked
**Key risks**: What could go wrong
{_SHAPE_FINALIZE_END}

## Your Capabilities — Use Them

- **Codebase exploration**: Use Glob, Grep, and Read to check existing code
  when assessing technical feasibility. Mention specific files/functions.
- **Web research**: Use WebSearch when the product owner asks about competitors,
  market trends, or specific technologies. Bring back real data, not guesses.
- **UX sketching**: For UI directions, describe user flows as step-by-step
  narratives: "User lands on → sees → clicks → transitions to → result."
  Include layout descriptions and key visual elements.

## Guidelines

- Be a thought partner, not a form wizard
- Match the product owner's energy — if they're brief, be concise
- If they say "go with this" or "ship it", produce the SHAPE_FINALIZE output
- Every direction should have real tradeoffs, not just pros
- Prefer depth on 2-3 good ideas over breadth on 5 shallow ones
- When you reference code feasibility, cite actual files you found
- When you reference competitors, cite actual features you researched

{MEMORY_SUGGESTION_PROMPT}
"""

        plugin_skills_section = format_plugin_skills_for_prompt(
            skills_for_phase(
                "shape",
                discover_plugin_skills(self._config.required_plugins),
                self._config.phase_skills,
            )
        )
        if plugin_skills_section:
            prompt = f"{prompt}\n\n{plugin_skills_section}"

        return prompt

    @staticmethod
    def _extract_between(text: str, start_marker: str, end_marker: str) -> str:
        """Extract content between two markers."""
        start = text.find(start_marker)
        end = text.find(end_marker)
        if start == -1 or end == -1 or end <= start:
            return ""
        return text[start + len(start_marker) : end].strip()

    @staticmethod
    def _extract_fallback(transcript: str) -> str:
        """Extract usable content from transcript when markers are missing."""
        # Try legacy markers
        start = transcript.find(_SHAPE_START)
        end = transcript.find(_SHAPE_END)
        if start != -1 and end != -1 and end > start:
            return transcript[start + len(_SHAPE_START) : end].strip()
        # Last resort: return the last 2000 chars
        return (
            transcript[-2000:].strip() if len(transcript) > 2000 else transcript.strip()
        )

    def _extract_result(self, transcript: str, issue_number: int) -> ShapeResult | None:
        """Extract structured ShapeResult from agent transcript.

        Looks for SHAPE_RESULT_START/END (or legacy SHAPE_START/END) markers
        containing a JSON code block with directions and recommendation.
        """
        return self.extract_result(transcript, issue_number)

    def _build_advocate_prompt(
        self,
        task: Task,
        research_brief: str = "",
        learned_preferences: str = "",
    ) -> str:
        """Build the prompt for the advocate perspective.

        Presents the issue from multiple lenses: User Advocate, Technical
        Realist, Market Strategist, and Scope Hawk.
        """
        research_section = ""
        if research_brief:
            research_section = f"""
## Discovery Research Brief

{research_brief}

Use this research to inform your thinking. Do NOT repeat it verbatim.
"""

        preference_section = ""
        if learned_preferences:
            preference_section = f"""
## Learned Preferences

{learned_preferences}
"""

        return f"""You are a product design advocate for GitHub issue #{task.id}.

## Issue: {task.title}

{task.body or "(No description provided)"}
{research_section}{preference_section}
Present 3-5 distinct product DIRECTIONS. Each direction should be meaningfully different.

For each direction, evaluate from four lenses:
- **User Advocate**: Does this solve the real pain point?
- **Technical Realist**: How complex to build?
- **Market Strategist**: What's the differentiation?
- **Scope Hawk**: What's the MVP?

Output your directions as structured JSON between markers.
"""

    def _build_critic_prompt(
        self,
        task: Task,
        advocate_result: ShapeResult,
    ) -> str:
        """Build the prompt for the CRITIC perspective.

        Takes the advocate's directions and challenges them — poking holes,
        stress-testing assumptions, and recommending which to kill.
        """
        directions_text = ""
        for d in advocate_result.directions:
            directions_text += f"\n### {d.name}\n"
            directions_text += f"- Approach: {d.approach}\n"
            directions_text += f"- Tradeoffs: {d.tradeoffs}\n"
            directions_text += f"- Effort: {d.effort}\n"
            directions_text += f"- Risk: {d.risk}\n"
            if d.differentiator:
                directions_text += f"- Differentiator: {d.differentiator}\n"

        return f"""You are a CRITIC reviewing proposed product directions for GitHub issue #{task.id}.

## Issue: {task.title}

{task.body or "(No description provided)"}

## Advocate's Directions
{directions_text}

## Advocate's Recommendation

{advocate_result.recommendation}

## Your Role: CHALLENGE Everything

CHALLENGE each direction rigorously:
- Kill weak directions that don't hold up to scrutiny
- Poke holes in assumptions
- Identify hidden risks the advocate missed
- Stress-test the effort estimates
- Question whether the differentiator is real

Be constructive but ruthless. The goal is to surface the strongest direction.
"""

    def extract_result(self, transcript: str, issue_number: int) -> ShapeResult | None:
        """Extract structured ShapeResult from agent transcript (legacy compatibility)."""
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
            directions = [
                ProductDirection(
                    name=d.get("name", "Unnamed"),
                    approach=d.get("approach", ""),
                    tradeoffs=d.get("tradeoffs", ""),
                    effort=d.get("effort", "unknown"),
                    risk=d.get("risk", "unknown"),
                    differentiator=d.get("differentiator", ""),
                )
                for d in data.get("directions", [])
            ]
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
