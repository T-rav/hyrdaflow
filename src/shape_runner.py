"""Shape runner — turn-based product design conversation agent."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from models import ProductDirection, ShapeConversation, ShapeResult, ShapeTurnResult
from phase_utils import reraise_on_credit_or_bug
from runner_constants import MEMORY_SUGGESTION_PROMPT

if TYPE_CHECKING:
    from models import Task

logger = logging.getLogger("hydraflow.shape")

_SHAPE_CONTINUE = "SHAPE_CONTINUE"
_SHAPE_CONTINUE_END = "SHAPE_CONTINUE_END"
_SHAPE_FINALIZE = "SHAPE_FINALIZE"
_SHAPE_FINALIZE_END = "SHAPE_FINALIZE_END"
# Legacy markers for backward compatibility with extract_result
_SHAPE_START = "SHAPE_START"
_SHAPE_END = "SHAPE_END"
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


class ShapeRunner(BaseRunner):
    """Turn-based product design conversation agent.

    Each call to ``run_turn`` is a single agent invocation with the full
    conversation history injected. The agent adapts its behavior based on
    turn count: explore broadly early, crystallize late.
    """

    _log = logger

    async def run_turn(
        self,
        task: Task,
        conversation: ShapeConversation,
        research_brief: str = "",
        learned_preferences: str = "",
    ) -> ShapeTurnResult:
        """Run a single conversation turn for *task*.

        Returns a :class:`ShapeTurnResult` with the agent's response.
        """
        result = ShapeTurnResult()

        if self._config.dry_run:
            logger.info("[dry-run] Would run shape turn for issue #%d", task.id)
            result.content = "Dry-run: shape turn skipped"
            return result

        try:
            cmd = self._build_command()
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
                {"issue": task.id, "source": "shape"},
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
                f"shape-issue-turn{turn_num}", task.id, result.transcript
            )
        except OSError:
            logger.warning(
                "Failed to save shape transcript for issue #%d",
                task.id,
                exc_info=True,
            )

        return result

    def _build_command(self, _worktree_path=None) -> list[str]:  # type: ignore[override]
        """Construct the CLI invocation for product shaping.

        Shape agents can read the codebase (Glob, Grep, Read) and search
        the web (WebSearch, WebFetch) but cannot modify files.
        """
        return build_agent_command(
            tool=self._config.planner_tool,
            model=self._config.planner_model,
            disallowed_tools="Write,Edit,NotebookEdit",
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

        return f"""You are a product design agent having a conversation about GitHub issue #{task.id}.

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
