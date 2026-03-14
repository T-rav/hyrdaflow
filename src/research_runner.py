"""Research runner — pre-plan codebase exploration for complex issues."""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from models import ResearchResult
from phase_utils import reraise_on_credit_or_bug
from runner_constants import MEMORY_SUGGESTION_PROMPT

if TYPE_CHECKING:
    from models import Task

logger = logging.getLogger("hydraflow.research")


class ResearchRunner(BaseRunner):
    """Launches a ``claude -p`` process to explore the codebase before planning.

    The research agent works READ-ONLY against the repo root (same as the
    planner).  It produces structured research context that is injected
    into the planner prompt for complex issues.
    """

    _log = logger

    async def research(self, task: Task, worker_id: int = 0) -> ResearchResult:
        """Run the research agent for *task*.

        Returns a :class:`ResearchResult` with the research context.
        """
        start = time.monotonic()
        result = ResearchResult(issue_number=task.id)

        if self._config.dry_run:
            logger.info("[dry-run] Would research issue #%d", task.id)
            result.success = True
            result.duration_seconds = time.monotonic() - start
            return result

        try:
            cmd = self._build_command()
            prompt = self._build_prompt(task)

            def _check_complete(accumulated: str) -> bool:
                if "RESEARCH_END" in accumulated:
                    logger.info(
                        "Research markers found for issue #%d — terminating",
                        task.id,
                    )
                    return True
                return False

            transcript = await self._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "researcher"},
                on_output=_check_complete,
            )
            result.transcript = transcript

            research = self._extract_research(transcript)
            if research:
                result.research = research
                result.success = True
            else:
                result.error = "No RESEARCH_START/RESEARCH_END markers found"
                result.success = False

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.success = False
            result.error = repr(exc)
            logger.exception(
                "Research failed for issue #%d: %s",
                task.id,
                exc,
                extra={"issue": task.id},
            )

        result.duration_seconds = time.monotonic() - start

        try:
            self._save_transcript("research-issue", task.id, result.transcript)
        except OSError:
            logger.warning(
                "Failed to save research transcript for issue #%d",
                task.id,
                exc_info=True,
                extra={"issue": task.id},
            )

        return result

    def _build_command(self, _worktree_path=None) -> list[str]:  # type: ignore[override]
        """Construct the CLI invocation for research (read-only)."""
        return build_agent_command(
            tool=self._config.planner_tool,
            model=self._config.planner_model,
            disallowed_tools="Write,Edit,NotebookEdit",
        )

    def _build_prompt(self, task: Task) -> str:
        """Build the research prompt for *task*."""
        manifest_section, memory_section = self._inject_manifest_and_memory()

        return f"""You are a research agent exploring the codebase for GitHub issue #{task.id}.

## Issue: {task.title}

{task.body}{manifest_section}{memory_section}

## Instructions

You are in READ-ONLY mode. Do NOT create, modify, or delete any files.
Do NOT run any commands that change state.

Your job: deeply explore the codebase and produce structured research context
that will help a planning agent create a better implementation plan.

## Research Strategy

1. **Understand the request** — Restate the issue in your own words.
2. **Find relevant files** — Use semantic search and grep to locate all files
   related to the issue. Note their paths, key functions, and patterns.
3. **Trace dependencies** — Identify what depends on the code being changed
   and what the code depends on.
4. **Identify patterns** — Note coding conventions, testing patterns, and
   architectural decisions relevant to this change.
5. **Find constraints** — Note any constraints (type contracts, config schemas,
   backward compatibility requirements) that the implementation must respect.
6. **Identify integration points** — List all places where the new code must
   integrate with existing code.

## Required Output

Output your research between these exact markers:

RESEARCH_START

### Relevant Files
| File | Purpose | Key Functions/Classes |
|------|---------|----------------------|
| path/to/file.py | description | `function_name()`, `ClassName` |

### Patterns & Conventions
- <pattern observed in the codebase relevant to this issue>

### Constraints
- <constraint the implementation must respect>

### Integration Points
- <where new code connects to existing code>

### Risks & Considerations
- <potential issues or edge cases discovered>

RESEARCH_END

{MEMORY_SUGGESTION_PROMPT.format(context="research")}"""

    @staticmethod
    def _extract_research(transcript: str) -> str:
        """Extract research content from between markers."""
        pattern = r"RESEARCH_START\s*\n(.*?)\nRESEARCH_END"
        match = re.search(pattern, transcript, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""
