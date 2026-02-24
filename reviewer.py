"""PR review agent runner — launches Claude Code to review and fix PRs."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agent_cli import build_agent_command
from base_runner import BaseRunner
from escalation_gate import high_risk_diff_touched, should_escalate_debug
from events import EventType, HydraFlowEvent
from models import GitHubIssue, PRInfo, ReviewerStatus, ReviewResult, ReviewVerdict
from runner_constants import MEMORY_SUGGESTION_PROMPT
from subprocess_util import CreditExhaustedError

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


class ReviewRunner(BaseRunner):
    """Launches a ``claude -p`` process to review a pull request.

    The reviewer reads the PR diff, checks code quality and test
    coverage, optionally makes fixes, and returns a verdict.
    """

    _log = logger

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
            precheck_context = await self._run_precheck_context(
                pr, issue, diff, worktree_path
            )
            cmd = self._build_command(worktree_path)
            prompt = self._build_review_prompt(
                pr, issue, diff, precheck_context=precheck_context
            )
            before_sha = await self._get_head_sha(worktree_path)
            transcript = await self._execute(
                cmd, prompt, worktree_path, {"pr": pr.number, "source": "reviewer"}
            )
            result.transcript = transcript

            # Parse the verdict from the transcript
            result.verdict = self._parse_verdict(transcript)
            result.summary = self._extract_summary(transcript)

            # Check if the reviewer made any commits or left uncommitted changes
            result.fixes_made = await self._has_changes(worktree_path, before_sha)

            # Persist to disk
            self._save_transcript("review-pr", pr.number, transcript)

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
        ci_logs: str = "",
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
            prompt = self._build_ci_fix_prompt(
                pr, issue, failure_summary, attempt, ci_logs=ci_logs
            )
            before_sha = await self._get_head_sha(worktree_path)
            transcript = await self._execute(
                cmd, prompt, worktree_path, {"pr": pr.number, "source": "reviewer"}
            )
            result.transcript = transcript
            result.verdict = self._parse_verdict(transcript)
            result.summary = self._extract_summary(transcript)
            result.fixes_made = await self._has_changes(worktree_path, before_sha)
            self._save_transcript("review-pr", pr.number, transcript)
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
        ci_logs: str = "",
    ) -> str:
        """Build a focused prompt for fixing CI failures."""
        ci_logs_section = ""
        if ci_logs:
            ci_logs_section = f"\n\n## Full CI Failure Logs\n\n```\n{ci_logs}\n```"

        test_cmd = self._config.test_command
        return f"""You are fixing CI failures on PR #{pr.number} (issue #{issue.number}: {issue.title}).

## CI Failure Summary

{failure_summary}{ci_logs_section}

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

    def _build_command(self, worktree_path: Path | None = None) -> list[str]:
        """Construct the review CLI invocation.

        The working directory is set via ``cwd`` in the subprocess call,
        not via a CLI flag.
        """
        return build_agent_command(
            tool=self._config.review_tool,
            model=self._config.review_model,
        )

    def _build_review_prompt(
        self,
        pr: PRInfo,
        issue: GitHubIssue,
        diff: str,
        precheck_context: str = "",
    ) -> str:
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

        manifest_section, memory_section = self._inject_manifest_and_memory()

        # Runtime log injection (opt-in)
        log_section = ""
        if self._config.inject_runtime_logs:
            from log_context import load_runtime_logs  # noqa: PLC0415

            logs = load_runtime_logs(self._config)
            if logs:
                log_section = f"\n\n## Recent Application Logs\n\n```\n{logs}\n```"

        return f"""You are reviewing PR #{pr.number} which implements issue #{issue.number}.

## Issue: {issue.title}

{issue.body}{manifest_section}{memory_section}{log_section}

## Precheck Context

{precheck_context or "No low-tier precheck context provided."}

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

{MEMORY_SUGGESTION_PROMPT.format(context="review")}"""

    def _build_subskill_command(self) -> list[str]:
        return build_agent_command(
            tool=self._config.subskill_tool,
            model=self._config.subskill_model,
        )

    def _build_debug_command(self) -> list[str]:
        return build_agent_command(
            tool=self._config.debug_tool,
            model=self._config.debug_model,
        )

    def _build_precheck_prompt(self, pr: PRInfo, issue: GitHubIssue, diff: str) -> str:
        max_diff = min(len(diff), 6000)
        diff_snippet = diff[:max_diff]
        return f"""Run a compact review precheck for PR #{pr.number} (issue #{issue.number}).

Goal:
- estimate risk and confidence
- list top findings (max 5)
- recommend whether debug escalation is needed

Return EXACTLY:
PRECHECK_RISK: low|medium|high
PRECHECK_CONFIDENCE: <0.0-1.0>
PRECHECK_ESCALATE: yes|no
PRECHECK_SUMMARY: <one line>

Issue title: {issue.title}
Diff snippet:
```diff
{diff_snippet}
```
"""

    @staticmethod
    def _parse_precheck_transcript(
        transcript: str,
    ) -> tuple[str, float, bool, str, bool]:
        risk_match = re.search(
            r"PRECHECK_RISK:\s*(low|medium|high)",
            transcript,
            re.IGNORECASE,
        )
        confidence_match = re.search(
            r"PRECHECK_CONFIDENCE:\s*([0-9]*\.?[0-9]+)",
            transcript,
            re.IGNORECASE,
        )
        escalate_match = re.search(
            r"PRECHECK_ESCALATE:\s*(yes|no)",
            transcript,
            re.IGNORECASE,
        )
        summary_match = re.search(
            r"PRECHECK_SUMMARY:\s*(.*)",
            transcript,
            re.IGNORECASE,
        )
        parse_failed = not (
            risk_match and confidence_match and escalate_match and summary_match
        )
        risk = risk_match.group(1).lower() if risk_match else "medium"
        confidence = float(confidence_match.group(1)) if confidence_match else 0.0
        escalate = bool(escalate_match and escalate_match.group(1).lower() == "yes")
        summary = summary_match.group(1).strip() if summary_match else ""
        return risk, confidence, escalate, summary, parse_failed

    async def _run_precheck_context(
        self, pr: PRInfo, issue: GitHubIssue, diff: str, worktree_path: Path
    ) -> str:
        if self._config.max_subskill_attempts <= 0:
            return "Low-tier precheck disabled."
        prompt = self._build_precheck_prompt(pr, issue, diff)
        summary = ""
        parse_failed = False
        risk = "medium"
        confidence = self._config.subskill_confidence_threshold
        max_subskill = self._config.max_subskill_attempts

        try:
            for _attempt in range(1, max_subskill + 1):
                transcript = await self._execute(
                    self._build_subskill_command(),
                    prompt,
                    worktree_path,
                    {"pr": pr.number, "source": "reviewer"},
                )
                (
                    risk,
                    confidence,
                    _escalate_signal,
                    summary,
                    parse_failed,
                ) = self._parse_precheck_transcript(transcript)
                if not parse_failed:
                    break
        except Exception:  # noqa: BLE001
            return "Low-tier precheck failed; continuing without precheck context."

        decision = should_escalate_debug(
            enabled=self._config.debug_escalation_enabled,
            confidence=confidence,
            confidence_threshold=self._config.subskill_confidence_threshold,
            parse_failed=parse_failed,
            retry_count=max_subskill,
            max_subskill_attempts=max_subskill,
            risk=risk,
            high_risk_files_touched=high_risk_diff_touched(diff),
        )

        context_lines = [
            f"Precheck risk: {risk}",
            f"Precheck confidence: {confidence:.2f}",
            f"Precheck summary: {summary or 'N/A'}",
            f"Debug escalation: {'yes' if decision.escalate else 'no'}",
        ]

        if decision.escalate and self._config.max_debug_attempts > 0:
            debug_prompt = (
                prompt
                + "\n\nDEBUG MODE: Focus on root causes and concrete risky files."
            )
            debug_transcript = await self._execute(
                self._build_debug_command(),
                debug_prompt,
                worktree_path,
                {"pr": pr.number, "source": "reviewer"},
            )
            context_lines.append("Debug precheck transcript:")
            context_lines.append(debug_transcript[:1000])
            context_lines.append(f"Escalation reasons: {', '.join(decision.reasons)}")

        return "\n".join(context_lines)

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

    async def _get_head_sha(self, worktree_path: Path) -> str | None:
        """Return the current HEAD commit SHA in the worktree."""
        try:
            result = await self._runner.run_simple(
                ["git", "rev-parse", "HEAD"],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
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
                timeout=self._config.git_command_timeout,
            )
            return result.returncode == 0 and bool(result.stdout)
        except (TimeoutError, FileNotFoundError):
            return False
