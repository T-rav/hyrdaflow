"""PR review agent runner — launches Claude Code to review and fix PRs."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from execution import get_default_runner
from memory import load_memory_digest
from models import GitHubIssue, PRInfo, ReviewerStatus, ReviewResult, ReviewVerdict
from runner_utils import stream_claude_process, terminate_processes
from subprocess_util import CreditExhaustedError

if TYPE_CHECKING:
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.reviewer")

# Compiled patterns that indicate a transcript line is internal tool output,
# not a human-readable review summary.
_JUNK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[→←]"),  # Tool arrows (e.g. "→ TaskOutput: ...")
    re.compile(r"^\s*\{.*\}\s*$"),  # Raw JSON objects
    re.compile(r"<[a-zA-Z/][^>]*>"),  # HTML tags
    re.compile(r"^```"),  # Code fence markers
    re.compile(r"^Co-Authored-By:", re.IGNORECASE),  # Git trailers
    re.compile(r"^Signed-off-by:", re.IGNORECASE),  # Git trailers
    re.compile(r"^\s*\d+[\s,]+\d+"),  # Metric lines (e.g. "1234 5678")
    re.compile(r"^(tokens|cost|duration)\s*:", re.IGNORECASE),  # Metric labels
]


class ReviewRunner:
    """Launches a ``claude -p`` process to review a pull request.

    The reviewer reads the PR diff, checks code quality and test
    coverage, optionally makes fixes, and returns a verdict.
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

    async def review(
        self,
        pr: PRInfo,
        issue: GitHubIssue,
        worktree_path: Path,
        diff: str,
        worker_id: int = 0,
    ) -> ReviewResult:
        """Run the review agent for *pr*.

        Returns a :class:`ReviewResult` with the verdict and summary.
        """
        start = time.monotonic()
        result = ReviewResult(
            pr_number=pr.number,
            issue_number=issue.number,
        )

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.REVIEW_UPDATE,
                data={
                    "pr": pr.number,
                    "issue": issue.number,
                    "worker": worker_id,
                    "status": ReviewerStatus.REVIEWING.value,
                    "role": "reviewer",
                },
            )
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would review PR #%d", pr.number)
            result.verdict = ReviewVerdict.APPROVE
            result.summary = "Dry-run: auto-approved"
            result.duration_seconds = time.monotonic() - start
            return result

        try:
            cmd = self._build_command(worktree_path)
            prompt = self._build_review_prompt(pr, issue, diff)
            before_sha = await self._get_head_sha(worktree_path)
            transcript = await self._execute(cmd, prompt, worktree_path, pr.number)
            result.transcript = transcript

            # Parse the verdict from the transcript
            result.verdict = self._parse_verdict(transcript)
            result.summary = self._extract_summary(transcript)

            # Check if the reviewer made any commits or left uncommitted changes
            result.fixes_made = await self._has_changes(worktree_path, before_sha)

            # Persist to disk
            self._save_transcript(pr.number, transcript)

        except CreditExhaustedError:
            raise
        except Exception as exc:
            result.verdict = ReviewVerdict.COMMENT
            result.summary = f"Review failed: {exc}"
            logger.error("Review failed for PR #%d: %s", pr.number, exc)

        result.duration_seconds = time.monotonic() - start

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.REVIEW_UPDATE,
                data={
                    "pr": pr.number,
                    "issue": issue.number,
                    "worker": worker_id,
                    "status": ReviewerStatus.DONE.value,
                    "verdict": result.verdict.value,
                    "duration": result.duration_seconds,
                    "role": "reviewer",
                },
            )
        )

        return result

    async def fix_ci(
        self,
        pr: PRInfo,
        issue: GitHubIssue,
        worktree_path: Path,
        failure_summary: str,
        attempt: int = 1,
        worker_id: int = 0,
    ) -> ReviewResult:
        """Run an agent to fix CI failures.

        Mirrors the :meth:`review` structure: build command, execute,
        parse verdict, check commits.  Returns a :class:`ReviewResult`
        with verdict APPROVE (fixed) or REQUEST_CHANGES (could not fix).
        """
        start = time.monotonic()
        result = ReviewResult(
            pr_number=pr.number,
            issue_number=issue.number,
        )

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.CI_CHECK,
                data={
                    "pr": pr.number,
                    "issue": issue.number,
                    "worker": worker_id,
                    "status": ReviewerStatus.FIXING.value,
                    "attempt": attempt,
                },
            )
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would fix CI for PR #%d", pr.number)
            result.verdict = ReviewVerdict.APPROVE
            result.summary = "Dry-run: CI fix skipped"
            result.duration_seconds = time.monotonic() - start
            return result

        try:
            cmd = self._build_command(worktree_path)
            prompt = self._build_ci_fix_prompt(pr, issue, failure_summary, attempt)
            before_sha = await self._get_head_sha(worktree_path)
            transcript = await self._execute(cmd, prompt, worktree_path, pr.number)
            result.transcript = transcript
            result.verdict = self._parse_verdict(transcript)
            result.summary = self._extract_summary(transcript)
            result.fixes_made = await self._has_changes(worktree_path, before_sha)
            self._save_transcript(pr.number, transcript)
        except CreditExhaustedError:
            raise
        except Exception as exc:
            result.verdict = ReviewVerdict.REQUEST_CHANGES
            result.summary = f"CI fix failed: {exc}"
            logger.error("CI fix failed for PR #%d: %s", pr.number, exc)

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.CI_CHECK,
                data={
                    "pr": pr.number,
                    "issue": issue.number,
                    "worker": worker_id,
                    "status": ReviewerStatus.FIX_DONE.value,
                    "attempt": attempt,
                    "verdict": result.verdict.value,
                },
            )
        )

        result.duration_seconds = time.monotonic() - start
        return result

    def _build_ci_fix_prompt(
        self,
        pr: PRInfo,
        issue: GitHubIssue,
        failure_summary: str,
        attempt: int,
    ) -> str:
        """Build a focused prompt for fixing CI failures."""
        test_cmd = self._config.test_command
        return f"""You are fixing CI failures on PR #{pr.number} (issue #{issue.number}: {issue.title}).

## CI Failure Summary

{failure_summary}

## Fix Attempt {attempt}

1. Read the failing CI output above.
2. Fix the root causes — do NOT skip or disable tests.
3. Run `make lint` and `{test_cmd}` to verify locally.
4. Commit fixes with message: "ci-fix: <description> (PR #{pr.number})"

## Required Output

End your response with EXACTLY one of these verdict lines:
- VERDICT: APPROVE   (if CI failures are fixed)
- VERDICT: REQUEST_CHANGES  (if you could not fix them)

Then a brief summary on the next line starting with "SUMMARY: ".
"""

    def _build_command(self, worktree_path: Path) -> list[str]:
        """Construct the ``claude`` CLI invocation for review.

        The working directory is set via ``cwd`` in the subprocess call,
        not via a CLI flag.
        """
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--model",
            self._config.review_model,
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
        ]
        if self._config.review_budget_usd > 0:
            cmd.extend(["--max-budget-usd", str(self._config.review_budget_usd)])
        return cmd

    def _build_review_prompt(self, pr: PRInfo, issue: GitHubIssue, diff: str) -> str:
        """Build the review prompt for the agent."""
        ci_enabled = self._config.max_ci_fix_attempts > 0
        test_cmd = self._config.test_command
        ui_criteria = ""
        if "ui/" in diff:
            ui_criteria = """
7. **UI-specific checks** (PR modifies frontend code):
   - DRY: No duplicated constants, types, or styles — import from `constants.js`, `types.js`, `theme.js`.
   - Responsive: Layout containers set `minWidth`; flex items handle shrinking (`minWidth: 0` or `overflow: hidden`).
   - Style consistency: Spacing uses 4px grid multiples; colors come from `theme.js`, not hardcoded values.
   - Component reuse: No new component that duplicates an existing one in `ui/src/components/`.
   - Shared code: New constants/types belong in centralized files, not inline.
"""

        if ci_enabled:
            verify_step = (
                "5. Do NOT run `make lint`, `make test`, or `make quality` — "
                "CI will verify these automatically after review."
            )
            fix_verify = "2. Do NOT run tests locally — CI will verify after push."
        else:
            verify_step = (
                f"5. Run `make lint` and `{test_cmd}` to verify everything passes."
            )
            fix_verify = f"2. Run `make lint` and `{test_cmd}`."

        # Truncate diff with warning
        max_diff = self._config.max_review_diff_chars
        if len(diff) > max_diff:
            logger.warning(
                "PR #%d diff truncated from %d to %d chars",
                pr.number,
                len(diff),
                max_diff,
            )
            diff_text = (
                diff[:max_diff]
                + f"\n\n[Diff truncated at {max_diff:,} chars"
                + " — review may be incomplete for large PRs]"
            )
        else:
            diff_text = diff

        min_findings = self._config.min_review_findings

        # Memory digest injection
        memory_section = ""
        digest = load_memory_digest(self._config)
        if digest:
            memory_section = f"\n\n## Accumulated Learnings\n\n{digest}"

        return f"""You are reviewing PR #{pr.number} which implements issue #{issue.number}.

## Issue: {issue.title}

{issue.body}{memory_section}

## PR Diff

```diff
{diff_text}
```

## Review Dimensions

Review this PR across three dimensions:

### 1. Correctness
- Does the code work as intended? Are there edge cases?
- Proper error handling? No off-by-one errors?
- Are all branches tested?

### 2. Completeness
- Does the implementation address ALL requirements from the issue?
- Were any requirements silently dropped or partially implemented?
- Cross-reference the issue body's requirements list against the diff.
- If any requirement from the issue body is not addressed, flag it as a completeness gap.

### 3. Quality
- Code style, type annotations, naming conventions?
- Comprehensive test coverage (tests are MANDATORY per CLAUDE.md)?
- Security concerns? Performance issues?
- CLAUDE.md compliance: linting, formatting, no secrets committed?

## Review Instructions

1. Check each of the three dimensions above thoroughly.
2. You MUST examine the code critically. Look for: correctness issues, edge cases, missing error handling, security concerns, test coverage gaps, style/convention violations, and performance issues.
3. You MUST find at least {min_findings} issues across all categories. If you find fewer, re-examine the code more carefully.
4. If after thorough examination you genuinely find fewer than {min_findings} issues, you MUST include a THOROUGH_REVIEW_COMPLETE block justifying why each category had no findings. Format:
```
THOROUGH_REVIEW_COMPLETE
Correctness: No issues — <justification>
Completeness: No issues — <justification>
Quality: No issues — <justification>
```
{verify_step}
6. Run the project's audit commands on the changed code:
   - Review code quality patterns (SRP, type hints, naming, complexity)
   - Review test quality (3As structure, factories, edge cases)
   - Check for security issues (injection, crypto, auth)
{ui_criteria}
## If Issues Found

If you find issues that you can fix:
1. Make the fixes directly.
{fix_verify}
3. Commit with message: "review: fix <description> (PR #{pr.number})"

## Required Output

End your response with EXACTLY one of these verdict lines:
- VERDICT: APPROVE
- VERDICT: REQUEST_CHANGES
- VERDICT: COMMENT

Then a brief summary on the next line starting with "SUMMARY: ".

Example:
VERDICT: APPROVE
SUMMARY: Implementation looks good, tests are comprehensive, all checks pass.

## Optional: Memory Suggestion

If you discover a reusable pattern or insight during this review that would help future agent runs, you may output ONE suggestion:

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

    def _parse_verdict(self, transcript: str) -> ReviewVerdict:
        """Extract the verdict from the reviewer transcript."""
        pattern = r"VERDICT:\s*(APPROVE|REQUEST_CHANGES|COMMENT)"
        match = re.search(pattern, transcript, re.IGNORECASE)
        if match:
            raw = match.group(1).upper().replace("_", "-")
            # Map the parsed string to the enum
            mapping = {
                "APPROVE": ReviewVerdict.APPROVE,
                "REQUEST-CHANGES": ReviewVerdict.REQUEST_CHANGES,
                "COMMENT": ReviewVerdict.COMMENT,
            }
            return mapping.get(raw, ReviewVerdict.COMMENT)
        return ReviewVerdict.COMMENT

    @staticmethod
    def _sanitize_summary(candidate: str) -> str | None:
        """Return *candidate* if it looks like a real summary, else ``None``.

        Rejects strings that match any :data:`_JUNK_PATTERNS` or are
        shorter than 10 characters (likely not meaningful).  Valid
        summaries are truncated to 200 characters.
        """
        text = candidate.strip()
        if len(text) < 10:
            return None
        for pat in _JUNK_PATTERNS:
            if pat.search(text):
                return None
        return text[:200]

    def _extract_summary(self, transcript: str) -> str:
        """Extract the summary line from the reviewer transcript."""
        pattern = r"SUMMARY:\s*(.+)"
        match = re.search(pattern, transcript, re.IGNORECASE)
        if match:
            sanitized = self._sanitize_summary(match.group(1).strip())
            if sanitized:
                return sanitized

        # Fallback: walk lines in reverse, skipping garbage
        for line in reversed(transcript.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            sanitized = self._sanitize_summary(stripped)
            if sanitized:
                return sanitized

        return "No summary provided"

    def terminate(self) -> None:
        """Kill all active reviewer subprocesses."""
        terminate_processes(self._active_procs)

    async def _execute(
        self,
        cmd: list[str],
        prompt: str,
        worktree_path: Path,
        pr_number: int,
    ) -> str:
        """Run the claude review process."""
        return await stream_claude_process(
            cmd=cmd,
            prompt=prompt,
            cwd=worktree_path,
            active_procs=self._active_procs,
            event_bus=self._bus,
            event_data={"pr": pr_number, "source": "reviewer"},
            logger=logger,
            runner=self._runner,
        )

    def _save_transcript(self, pr_number: int, transcript: str) -> None:
        """Write the review transcript to .hydraflow/logs/ for post-mortem review."""
        log_dir = self._config.repo_root / ".hydraflow" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"review-pr-{pr_number}.txt"
            path.write_text(transcript)
            logger.info("Review transcript saved to %s", path, extra={"pr": pr_number})
        except OSError:
            logger.warning(
                "Could not save transcript to %s",
                log_dir,
                exc_info=True,
                extra={"pr": pr_number},
            )

    async def _get_head_sha(self, worktree_path: Path) -> str | None:
        """Return the current HEAD commit SHA in the worktree."""
        try:
            result = await self._runner.run_simple(
                ["git", "rev-parse", "HEAD"],
                cwd=str(worktree_path),
                timeout=30,
            )
        except (TimeoutError, FileNotFoundError):
            return None
        if result.returncode == 0:
            return result.stdout
        return None

    async def _has_changes(self, worktree_path: Path, before_sha: str | None) -> bool:
        """Check if the agent made commits or left uncommitted changes."""
        try:
            # Check 1: new commits (HEAD moved)
            current_sha = await self._get_head_sha(worktree_path)
            if current_sha and before_sha and current_sha != before_sha:
                return True

            # Check 2: uncommitted changes (staged or unstaged)
            result = await self._runner.run_simple(
                ["git", "status", "--porcelain"],
                cwd=str(worktree_path),
                timeout=30,
            )
            return result.returncode == 0 and bool(result.stdout)
        except (TimeoutError, FileNotFoundError):
            return False
