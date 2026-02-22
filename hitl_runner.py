"""HITL correction agent runner — launches Claude Code to apply human guidance."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from execution import get_default_runner
from manifest import load_project_manifest
from memory import load_memory_digest
from models import GitHubIssue, HITLResult
from runner_utils import stream_claude_process, terminate_processes
from subprocess_util import CreditExhaustedError

if TYPE_CHECKING:
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.hitl_runner")

# Prompt instructions keyed by escalation cause category.
_CAUSE_INSTRUCTIONS: dict[str, str] = {
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
        "3. Write comprehensive tests FIRST (TDD approach).\n"
        "4. Implement the solution.\n"
        "5. Run `make quality` to verify.\n"
        '6. Commit with message: "hitl-fix: <description> (#{issue})".'
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


def _classify_cause(cause: str) -> str:
    """Map a free-text escalation cause to a prompt template key."""
    lower = cause.lower()
    # Check needs_info BEFORE ci — "insufficient" contains the substring "ci".
    if "insufficient" in lower or "needs" in lower or "detail" in lower:
        return "needs_info"
    if "ci" in lower or "check" in lower or "test fail" in lower:
        return "ci"
    if "merge" in lower and "conflict" in lower:
        return "merge_conflict"
    return "default"


class HITLRunner:
    """Launches a ``claude -p`` process to apply HITL corrections.

    Accepts an issue, human-provided correction text, and the
    escalation cause, then builds a targeted prompt and runs the
    agent inside the issue's worktree.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._runner = runner or get_default_runner()

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
                data={
                    "issue": issue.number,
                    "worker": worker_id,
                    "status": "running",
                    "action": "hitl_run",
                },
            )
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would run HITL for issue #%d", issue.number)
            result.success = True
            result.duration_seconds = time.monotonic() - start
            return result

        try:
            cmd = self._build_command(worktree_path)
            prompt = self._build_prompt(issue, correction, cause)
            transcript = await self._execute(cmd, prompt, worktree_path, issue.number)
            result.transcript = transcript

            success, verify_msg = await self._verify_quality(worktree_path)
            result.success = success
            if not success:
                result.error = verify_msg

            self._save_transcript(issue.number, transcript)

        except CreditExhaustedError:
            raise
        except Exception as exc:
            result.success = False
            result.error = str(exc)
            logger.error("HITL run failed for issue #%d: %s", issue.number, exc)

        result.duration_seconds = time.monotonic() - start

        status = "done" if result.success else "failed"
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data={
                    "issue": issue.number,
                    "worker": worker_id,
                    "status": status,
                    "action": "hitl_run",
                    "duration": result.duration_seconds,
                },
            )
        )

        return result

    def _build_command(self, worktree_path: Path) -> list[str]:
        """Construct the ``claude`` CLI invocation for HITL."""
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--model",
            self._config.model,
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
        ]
        if self._config.max_budget_usd > 0:
            cmd.extend(["--max-budget-usd", str(self._config.max_budget_usd)])
        return cmd

    def _build_prompt(self, issue: GitHubIssue, correction: str, cause: str) -> str:
        """Build the HITL prompt with cause-specific instructions and human guidance."""
        cause_key = _classify_cause(cause)
        instructions = _CAUSE_INSTRUCTIONS[cause_key].replace(
            "#{issue}", f"#{issue.number}"
        )

        # Project manifest injection
        manifest_section = ""
        manifest = load_project_manifest(self._config)
        if manifest:
            manifest_section = f"\n\n## Project Context\n\n{manifest}"

        # Memory digest injection
        memory_section = ""
        digest = load_memory_digest(self._config)
        if digest:
            memory_section = f"\n\n## Accumulated Learnings\n\n{digest}"

        return f"""You are applying a human-in-the-loop correction for GitHub issue #{issue.number}.

## Issue: {issue.title}

{issue.body}{manifest_section}{memory_section}

## Escalation Reason

{cause}

## Human Guidance

{correction}

## Instructions

{instructions}

## Rules

- Follow the project's CLAUDE.md guidelines strictly.
- Write tests for all new code — tests are mandatory.
- Do NOT push to remote. Do NOT create pull requests.
- Do NOT run `git push` or `gh pr create`.
- Ensure `make quality` passes before committing.

## Optional: Memory Suggestion

If you discover a reusable pattern or insight during this correction that would help future agent runs, you may output ONE suggestion:

MEMORY_SUGGESTION_START
title: Short descriptive title
type: knowledge | config | instruction | code
learning: What was learned and why it matters
context: How it was discovered (reference issue/PR numbers)
MEMORY_SUGGESTION_END

Types: knowledge (passive insight), config (suggests config change), instruction (new agent instruction), code (suggests code change).
Actionable types (config, instruction, code) will be routed for human approval.
Only suggest genuinely valuable learnings — not trivial observations.
"""

    def terminate(self) -> None:
        """Kill all active HITL subprocesses."""
        terminate_processes(self._active_procs)

    async def _execute(
        self,
        cmd: list[str],
        prompt: str,
        worktree_path: Path,
        issue_number: int,
    ) -> str:
        """Run the claude process and stream its output."""
        return await stream_claude_process(
            cmd=cmd,
            prompt=prompt,
            cwd=worktree_path,
            active_procs=self._active_procs,
            event_bus=self._bus,
            event_data={"issue": issue_number, "source": "hitl"},
            logger=logger,
            runner=self._runner,
        )

    async def _verify_quality(self, worktree_path: Path) -> tuple[bool, str]:
        """Run ``make quality`` and return ``(success, error_output)``."""
        try:
            result = await self._runner.run_simple(
                ["make", "quality"],
                cwd=str(worktree_path),
                timeout=3600,
            )
        except FileNotFoundError:
            return False, "make not found — cannot run quality checks"
        except TimeoutError:
            return False, "make quality timed out after 3600s"
        if result.returncode != 0:
            output = "\n".join(filter(None, [result.stdout, result.stderr]))
            return False, f"`make quality` failed:\n{output[-3000:]}"
        return True, "OK"

    def _save_transcript(self, issue_number: int, transcript: str) -> None:
        """Write the HITL transcript to .hydraflow/logs/ for post-mortem review."""
        log_dir = self._config.repo_root / ".hydraflow" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"hitl-issue-{issue_number}.txt"
            path.write_text(transcript)
            logger.info(
                "HITL transcript saved to %s", path, extra={"issue": issue_number}
            )
        except OSError:
            logger.warning(
                "Could not save transcript to %s",
                log_dir,
                exc_info=True,
                extra={"issue": issue_number},
            )
