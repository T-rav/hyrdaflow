"""HITL correction agent runner — launches Claude Code to apply human guidance."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Literal

from base_runner import BaseRunner
from events import EventType, HydraFlowEvent
from models import GitHubIssue, HITLResult, HITLUpdatePayload
from phase_utils import reraise_on_credit_or_bug
from prompt_builder import PromptBuilder
from runner_constants import MEMORY_SUGGESTION_PROMPT

logger = logging.getLogger("hydraflow.hitl_runner")

HITLCauseKey = Literal["ci", "merge_conflict", "needs_info", "visual", "default"]

# Prompt instructions keyed by escalation cause category.
_CAUSE_INSTRUCTIONS: dict[HITLCauseKey, str] = {
    "ci": (
        "The CI pipeline failed on this branch.\n"
        "1. Run `make quality` to see current failures.\n"
        "2. Fix the root causes — do NOT skip or disable tests.\n"
        "3. Run `make quality` again to verify your fixes.\n"
        '4. Commit fixes with message: "hitl-fix: <description> (#{issue})".'
    ),
    "merge_conflict": (
        "The branch has merge conflicts with main.\n"
        "1. Run `git status` to see conflicted files.\n"
        "2. Resolve all conflicts, keeping both the PR intent and upstream changes.\n"
        "3. Stage and commit the resolved files.\n"
        "4. Run `make quality` to verify everything passes.\n"
        '5. Commit with message: "hitl-fix: resolve merge conflicts (#{issue})".'
    ),
    "needs_info": (
        "This issue was escalated because it lacked sufficient detail.\n"
        "The human operator has provided additional guidance below.\n"
        "1. Read the issue and the guidance carefully.\n"
        "2. Explore the codebase to understand the context.\n"
        "3. Write comprehensive tests for new and changed code.\n"
        "4. Implement the solution.\n"
        "5. Run `make quality` to verify.\n"
        '6. Commit with message: "hitl-fix: <description> (#{issue})".'
    ),
    "visual": (
        "This issue was escalated due to visual validation failure.\n"
        "Screenshot diffs exceeded the allowed threshold.\n"
        "1. Review the escalation reason above for affected screen names and diff percentages.\n"
        "2. Check the HITL dashboard for artifact links (baseline/actual/diff images).\n"
        "3. Compare baseline vs actual screenshots to identify the regression.\n"
        "4. Fix the UI code causing the visual difference.\n"
        "5. Run `make quality` to verify.\n"
        '6. Commit with message: "hitl-fix: resolve visual regression (#{issue})".'
    ),
    "default": (
        "This issue was escalated to human review.\n"
        "The human operator has provided guidance below.\n"
        "1. Read the issue and the guidance carefully.\n"
        "2. Fix the issues described.\n"
        "3. Run `make quality` to verify.\n"
        '4. Commit with message: "hitl-fix: <description> (#{issue})".'
    ),
}


def _classify_cause(cause: str) -> HITLCauseKey:
    """Map a free-text escalation cause to a prompt template key."""
    lower = cause.lower()
    # Check visual BEFORE needs_info — visual summaries can contain "needs"
    # (e.g. "login screen needs baseline update").
    if any(kw in lower for kw in ("visual", "screenshot", "diff image")):
        return "visual"
    # Check needs_info BEFORE ci — "insufficient" contains the substring "ci".
    if "insufficient" in lower or "needs" in lower or "detail" in lower:
        return "needs_info"
    if re.search(r"\bci\b", lower) or "check" in lower or "test fail" in lower:
        return "ci"
    if "merge" in lower and "conflict" in lower:
        return "merge_conflict"
    return "default"


class HITLRunner(BaseRunner):
    """Launches a ``claude -p`` process to apply HITL corrections.

    Accepts an issue, human-provided correction text, and the
    escalation cause, then builds a targeted prompt and runs the
    agent inside the issue's worktree.
    """

    _log = logger

    async def run(
        self,
        issue: GitHubIssue,
        correction: str,
        cause: str,
        worktree_path: Path,
        worker_id: int = 0,
    ) -> HITLResult:
        """Run the HITL correction agent for *issue*.

        Returns a :class:`HITLResult` with success/failure info.
        """
        start = time.monotonic()
        result = HITLResult(issue_number=issue.number)

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data=HITLUpdatePayload(
                    issue=issue.number,
                    worker=worker_id,
                    status="running",
                    action="hitl_run",
                ),
            )
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would run HITL for issue #%d", issue.number)
            result.success = True
            result.duration_seconds = time.monotonic() - start
            return result

        try:
            cmd = self._build_command(worktree_path)
            prompt, prompt_stats = await self._build_prompt_with_stats(
                issue, correction, cause
            )
            transcript = await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"issue": issue.number, "source": "hitl"},
                telemetry_stats=prompt_stats,
            )
            result.transcript = transcript

            verify = await self._verify_quality(worktree_path)
            result.success = verify.passed
            if not verify.passed:
                result.error = verify.summary

            self._save_transcript("hitl-issue", issue.number, transcript)

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.success = False
            result.error = repr(exc)
            logger.exception("HITL run failed for issue #%d: %s", issue.number, exc)

        result.duration_seconds = time.monotonic() - start

        status = "done" if result.success else "failed"
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data=HITLUpdatePayload(
                    issue=issue.number,
                    worker=worker_id,
                    status=status,
                    action="hitl_run",
                    duration=result.duration_seconds,
                ),
            )
        )

        return result

    async def _build_prompt_with_stats(
        self, issue: GitHubIssue, correction: str, cause: str
    ) -> tuple[str, dict[str, object]]:
        """Build the HITL prompt with pruning stats."""
        cause_key = _classify_cause(cause)
        instructions = _CAUSE_INSTRUCTIONS[cause_key].replace(
            "#{issue}", f"#{issue.number}"
        )
        builder = PromptBuilder()
        issue_body = builder.add_context_section(
            "Issue body", issue.body or "", self._config.max_issue_body_chars
        )
        cause_text = builder.add_history_section(
            "Escalation reason", cause or "", self._config.max_hitl_cause_chars
        )
        correction_text = builder.add_history_section(
            "Human guidance", correction or "", self._config.max_hitl_correction_chars
        )

        manifest_section, memory_section = await self._inject_manifest_and_memory(
            query_context=f"{issue.title}\n{(issue.body or '')[:200]}",
        )

        prompt = f"""You are applying a human-in-the-loop correction for GitHub issue #{issue.number}.

## Issue: {issue.title}

{issue_body}{manifest_section}{memory_section}

## Escalation Reason

{cause_text}

## Human Guidance

{correction_text}

## Instructions

{instructions}

## Rules

- Follow the project's CLAUDE.md guidelines strictly.
- NEVER delete or overwrite existing CLAUDE.md content. You may append new sections or
  modify existing sections, but you must preserve all information already present.
- Write tests for all new code — tests are mandatory.
- Do NOT push to remote. Do NOT create pull requests.
- Do NOT run `git push` or `gh pr create`.
- Ensure `make quality` passes before committing.
- Do NOT bundle unrelated refactoring with the assigned fix. For example, do not
  migrate raw model constructors to factories, rename variables, or reformat code
  in files you are not otherwise changing for the issue. Each concern is a separate PR.

{MEMORY_SUGGESTION_PROMPT.format(context="correction")}"""
        stats = builder.build_stats()
        return prompt, stats
