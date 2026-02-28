"""PR review agent runner — launches Claude Code to review and fix PRs."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agent_cli import build_agent_command
from base_runner import BaseRunner
from events import EventType, HydraFlowEvent
from models import (
    PRInfo,
    ReviewerStatus,
    ReviewResult,
    ReviewVerdict,
    Task,
)
from precheck import run_precheck_context
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
    _MAX_CI_LOG_PROMPT_CHARS = 6_000

    async def review(
        self,
        pr: PRInfo,
        issue: Task,
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
            issue_number=issue.id,
        )

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.REVIEW_UPDATE,
                data={
                    "pr": pr.number,
                    "issue": issue.id,
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
            prompt, prompt_stats = self._build_review_prompt_with_stats(
                pr, issue, diff, precheck_context=precheck_context
            )
            before_sha = await self._get_head_sha(worktree_path)
            transcript = await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"pr": pr.number, "issue": issue.id, "source": "reviewer"},
                telemetry_stats=prompt_stats,
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
                    "issue": issue.id,
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
        issue: Task,
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
            issue_number=issue.id,
        )

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.CI_CHECK,
                data={
                    "pr": pr.number,
                    "issue": issue.id,
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
            prompt, prompt_stats = self._build_ci_fix_prompt(
                pr, issue, failure_summary, attempt, ci_logs=ci_logs
            )
            before_sha = await self._get_head_sha(worktree_path)
            transcript = await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"pr": pr.number, "issue": issue.id, "source": "reviewer"},
                telemetry_stats=prompt_stats,
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
                    "issue": issue.id,
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
        issue: Task,
        failure_summary: str,
        attempt: int,
        ci_logs: str = "",
    ) -> tuple[str, dict[str, object]]:
        """Build a focused prompt for fixing CI failures."""
        raw_ci_logs = ci_logs or ""
        compact_ci_logs = raw_ci_logs
        if len(compact_ci_logs) > self._MAX_CI_LOG_PROMPT_CHARS:
            compact_ci_logs = (
                compact_ci_logs[: self._MAX_CI_LOG_PROMPT_CHARS]
                + f"\n\n[CI logs truncated from {len(raw_ci_logs):,} chars]"
            )

        ci_logs_section = ""
        if compact_ci_logs:
            ci_logs_section = (
                f"\n\n## Full CI Failure Logs\n\n```\n{compact_ci_logs}\n```"
            )

        test_cmd = self._config.test_command
        prompt = f"""You are fixing CI failures on PR #{pr.number} (issue #{issue.id}: {issue.title}).

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
        before = len(failure_summary) + len(raw_ci_logs)
        after = len(failure_summary) + len(compact_ci_logs)
        stats: dict[str, object] = {
            "context_chars_before": before,
            "context_chars_after": after,
            "pruned_chars_total": max(0, before - after),
            "section_chars": {
                "ci_failure_summary": len(failure_summary),
                "ci_logs_before": len(raw_ci_logs),
                "ci_logs_after": len(compact_ci_logs),
            },
        }
        return prompt, stats

    def _build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Construct the review CLI invocation.

        The working directory is set via ``cwd`` in the subprocess call,
        not via a CLI flag.
        """
        return build_agent_command(
            tool=self._config.review_tool,
            model=self._config.review_model,
        )

    def _summarize_issue_body(self, body: str) -> str:
        """Return compact issue context to reduce prompt size."""
        text = (body or "").strip()
        if not text:
            return "(No issue body provided)"

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        cue_lines = [
            ln
            for ln in lines
            if re.match(r"^([-*]|\d+\.)\s+", ln) or ln.lower().startswith("acceptance")
        ]
        selected = cue_lines[:8] if cue_lines else lines[:8]
        compact = "\n".join(f"- {ln[:200]}" for ln in selected)
        compacted = len(text) > self._config.max_issue_body_chars
        note = (
            f"[Body summarized from {len(text):,} chars to reduce prompt size]"
            if compacted
            else "[Body summarized for prompt efficiency]"
        )
        return f"Issue body summarized for token efficiency:\n{compact}\n\n{note}"

    def _summarize_diff(self, pr_number: int, diff: str) -> str:
        """Return compact diff context with file/change summary and excerpts."""
        max_diff = self._config.max_review_diff_chars
        source = diff
        truncated = False
        if len(source) > max_diff:
            logger.warning(
                "PR #%d diff truncated from %d to %d chars",
                pr_number,
                len(source),
                max_diff,
            )
            source = source[:max_diff]
            truncated = True

        files: list[str] = []
        file_stats: dict[str, dict[str, int]] = {}
        current_file = ""
        added = 0
        removed = 0
        excerpt_lines: list[str] = []
        excerpt_chars = 0
        hunk_changes = 0
        excerpt_limit = min(1600, max_diff)
        max_files_in_summary = 10

        for line in source.splitlines():
            if line.startswith("diff --git "):
                m = re.search(r" b/(.+)$", line)
                current_file = m.group(1) if m else ""
                if current_file and current_file not in files:
                    files.append(current_file)
                    file_stats[current_file] = {"added": 0, "removed": 0}
                hunk_changes = 0
                if excerpt_chars < excerpt_limit:
                    excerpt_lines.append(line)
                    excerpt_chars += len(line) + 1
                continue

            if line.startswith("@@"):
                hunk_changes = 0
                if excerpt_chars < excerpt_limit:
                    excerpt_lines.append(line)
                    excerpt_chars += len(line) + 1
                continue

            if line.startswith(("+++", "---")):
                continue

            if line.startswith("+"):
                added += 1
                if current_file:
                    file_stats.setdefault(current_file, {"added": 0, "removed": 0})[
                        "added"
                    ] += 1
                if hunk_changes < 4 and excerpt_chars < excerpt_limit:
                    excerpt_lines.append(line)
                    excerpt_chars += len(line) + 1
                hunk_changes += 1
                continue

            if line.startswith("-"):
                removed += 1
                if current_file:
                    file_stats.setdefault(current_file, {"added": 0, "removed": 0})[
                        "removed"
                    ] += 1
                if hunk_changes < 4 and excerpt_chars < excerpt_limit:
                    excerpt_lines.append(line)
                    excerpt_chars += len(line) + 1
                hunk_changes += 1

        top_files: list[tuple[str, dict[str, int]]] = sorted(
            file_stats.items(),
            key=lambda item: item[1]["added"] + item[1]["removed"],
            reverse=True,
        )[:max_files_in_summary]
        if top_files:
            file_lines = "\n".join(
                f"- {path}: +{stats['added']} / -{stats['removed']}"
                for path, stats in top_files
            )
        else:
            file_lines = "- (could not detect files)"
        truncated_note = ""
        if truncated:
            truncated_note = f"\n[Diff truncated at {max_diff:,} chars — review may be incomplete for large PRs]"
        else:
            truncated_note = "\n[Diff summarized to reduce prompt size]"

        excerpt_block = (
            "\n".join(excerpt_lines).strip() or "(No excerpt lines captured)"
        )
        return (
            "### Diff Summary\n"
            f"- Files changed (detected): {len(files)}\n"
            f"- Added lines (detected): {added}\n"
            f"- Removed lines (detected): {removed}\n"
            "- Top changed files:\n"
            f"{file_lines}\n\n"
            "### Diff Excerpts\n"
            f"```diff\n{excerpt_block}\n```"
            f"{truncated_note}"
        )

    def _build_review_prompt(
        self,
        pr: PRInfo,
        issue: Task,
        diff: str,
        precheck_context: str = "",
    ) -> str:
        """Build the review prompt for the agent."""
        prompt, _stats = self._build_review_prompt_with_stats(
            pr, issue, diff, precheck_context=precheck_context
        )
        return prompt

    def _build_review_prompt_with_stats(
        self,
        pr: PRInfo,
        issue: Task,
        diff: str,
        precheck_context: str = "",
    ) -> tuple[str, dict[str, object]]:
        """Build the review prompt and pruning stats."""
        ci_enabled = self._config.max_ci_fix_attempts > 0
        test_cmd = self._config.test_command
        ui_criteria = ""
        if "ui/" in diff:
            ui_criteria = """
7. **UI-specific checks** (PR modifies frontend code):
   - DRY: No duplicated constants, types, or styles — import from `constants.js`, `types.js`, `theme.js`.
   - Responsive: Layout containers set `minWidth`; flex items handle shrinking (`minWidth: 0` or `overflow: hidden`).
   - Style consistency: Spacing uses 4px grid multiples; colors come from `theme.js`, not hardcoded values.
   - Component reuse: No new component that duplicates an existing one in `src/ui/src/components/`.
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

        diff_context = self._summarize_diff(pr.number, diff)

        min_findings = self._config.min_review_findings

        manifest_section, memory_section = self._inject_manifest_and_memory()

        # Runtime log injection (opt-in)
        log_section = ""
        if self._config.inject_runtime_logs:
            from log_context import load_runtime_logs  # noqa: PLC0415

            logs = load_runtime_logs(self._config)
            if logs:
                log_section = f"\n\n## Recent Application Logs\n\n```\n{logs}\n```"

        issue_body = self._summarize_issue_body(issue.body)

        prompt = f"""You are reviewing PR #{pr.number} which implements issue #{issue.id}.

## Issue: {issue.title}

{issue_body}{manifest_section}{memory_section}{log_section}

## Precheck Context

{precheck_context or "No low-tier precheck context provided."}

## PR Diff

{diff_context}

## Review Instructions

1. Evaluate three dimensions: correctness, completeness, and quality.
2. Look for edge cases, missing error handling, security risks, test gaps, and style violations.
3. You MUST find at least {min_findings} issues across all categories. If you find fewer, re-examine the code more carefully.
4. If you genuinely find fewer than {min_findings} issues, include THOROUGH_REVIEW_COMPLETE:
```
THOROUGH_REVIEW_COMPLETE
Correctness: No issues — <justification>
Completeness: No issues — <justification>
Quality: No issues — <justification>
```
{verify_step}
6. Run project audits on changed code:
   - Review code quality patterns (SRP, type hints, naming, complexity)
   - Review test quality (3As structure, factories, edge cases)
   - Check for security issues (injection, crypto, auth)
{ui_criteria}
## If Issues Found

If you find issues that you can fix:
1. Make the fixes directly.
{fix_verify}
3. Commit with message: "review: fix <description> (PR #{pr.number})"

## Findings Format

List findings in this compact schema:
`[SEVERITY] file[:line] - issue - expected fix`
Use `HIGH|MEDIUM|LOW`.

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
        stats = {
            "context_chars_before": len(issue.body or "") + len(diff),
            "context_chars_after": len(issue_body) + len(diff_context),
            "pruned_chars_total": max(
                0,
                (len(issue.body or "") + len(diff))
                - (len(issue_body) + len(diff_context)),
            ),
            "section_chars": {
                "issue_body_before": len(issue.body or ""),
                "issue_body_after": len(issue_body),
                "diff_before": len(diff),
                "diff_after": len(diff_context),
            },
        }
        return prompt, stats

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

    def _build_precheck_prompt(self, pr: PRInfo, issue: Task, diff: str) -> str:
        max_diff = min(len(diff), 3000, self._config.max_review_diff_chars)
        diff_snippet = diff[:max_diff]
        return f"""Run a compact review precheck for PR #{pr.number} (issue #{issue.id}).

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

    async def _run_precheck_context(
        self, pr: PRInfo, issue: Task, diff: str, worktree_path: Path
    ) -> str:
        prompt = self._build_precheck_prompt(pr, issue, diff)

        async def execute(cmd: list[str], p: str) -> str:
            telemetry_stats = {
                "context_chars_before": len(issue.body or "") + len(diff),
                "context_chars_after": len(p),
                "pruned_chars_total": max(
                    0, (len(issue.body or "") + len(diff)) - len(p)
                ),
            }
            return await self._execute(
                cmd,
                p,
                worktree_path,
                {"pr": pr.number, "issue": issue.id, "source": "reviewer"},
                telemetry_stats=telemetry_stats,
            )

        return await run_precheck_context(
            config=self._config,
            prompt=prompt,
            diff=diff,
            execute=execute,
            debug_message="DEBUG MODE: Focus on root causes and concrete risky files.",
            logger=logger,
        )

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
