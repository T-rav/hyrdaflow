"""Goal-driven PR unsticker — resolves ALL HITL causes autonomously."""

from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from models import ConflictResolutionResult
from phase_utils import safe_file_memory_suggestion
from prompt_stats import build_prompt_stats, truncate_with_notice

if TYPE_CHECKING:
    from agent import AgentRunner
    from config import HydraFlowConfig
    from events import EventBus
    from hitl_runner import HITLRunner
    from issue_fetcher import IssueFetcher
    from merge_conflict_resolver import MergeConflictResolver
    from models import GitHubIssue, HITLItem, UnstickResult
    from pr_manager import PRManager
    from state import StateTracker
    from troubleshooting_store import (
        TroubleshootingPattern,
        TroubleshootingPatternStore,
    )
    from worktree import WorktreeManager

logger = logging.getLogger("hydraflow.pr_unsticker")

# Keywords that indicate a merge conflict cause
_MERGE_CONFLICT_KEYWORDS = ("merge conflict", "conflict")

# Keywords for CI / quality failures
_CI_FAILURE_KEYWORDS = (
    "ci fail",
    "ci_fail",
    "check fail",
    "test fail",
    "lint fail",
    "type",
)

# Keywords for CI timeout (checked before CI failure since cause may contain both)
_CI_TIMEOUT_KEYWORDS = ("timeout", "timed out")

# Keywords for review fix cap exceeded
_REVIEW_CAP_KEYWORDS = ("review fix", "fix attempt", "fix cap", "review cap")
_MAX_UNSTICKER_CAUSE_CHARS = 3000


class FailureCause(StrEnum):
    """Classification of HITL escalation causes."""

    MERGE_CONFLICT = "merge_conflict"
    CI_TIMEOUT = "ci_timeout"
    CI_FAILURE = "ci_failure"
    REVIEW_FIX_CAP = "review_fix_cap"
    GENERIC = "generic"


# Priority order: lower index = processed first
_CAUSE_PRIORITY = {
    FailureCause.MERGE_CONFLICT: 0,
    FailureCause.CI_TIMEOUT: 1,
    FailureCause.CI_FAILURE: 2,
    FailureCause.REVIEW_FIX_CAP: 3,
    FailureCause.GENERIC: 4,
}


def _classify_cause(cause: str) -> FailureCause:
    """Classify a free-text HITL cause into a FailureCause enum value."""
    lower = cause.lower()
    if any(kw in lower for kw in _MERGE_CONFLICT_KEYWORDS):
        return FailureCause.MERGE_CONFLICT
    # Check timeout before CI failure — cause like "CI failed...: Timeout..."
    # contains both "ci fail" and "timeout" keywords.
    if any(kw in lower for kw in _CI_TIMEOUT_KEYWORDS):
        return FailureCause.CI_TIMEOUT
    if any(kw in lower for kw in _CI_FAILURE_KEYWORDS):
        return FailureCause.CI_FAILURE
    if any(kw in lower for kw in _REVIEW_CAP_KEYWORDS):
        return FailureCause.REVIEW_FIX_CAP
    return FailureCause.GENERIC


class PRUnsticker:
    """Goal-driven system that resolves ALL HITL causes autonomously.

    Processing flow:
    1. Fetch and classify HITL items by cause
    2. Fix in parallel (semaphore-limited)
    3. Merge sequentially (one at a time)
    4. Re-rebase remaining items after each merge
    5. Repeat until done or all remaining are stuck
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        event_bus: EventBus,
        pr_manager: PRManager,
        agents: AgentRunner,
        worktrees: WorktreeManager,
        fetcher: IssueFetcher,
        hitl_runner: HITLRunner | None = None,
        stop_event: asyncio.Event | None = None,
        resolver: MergeConflictResolver | None = None,
        troubleshooting_store: TroubleshootingPatternStore | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._bus = event_bus
        self._prs = pr_manager
        self._agents = agents
        self._worktrees = worktrees
        self._fetcher = fetcher
        self._hitl_runner = hitl_runner
        self._stop_event = stop_event or asyncio.Event()
        self._resolver = resolver
        self._troubleshooting_store = troubleshooting_store

    async def unstick(self, hitl_items: list[HITLItem]) -> UnstickResult:
        """Process HITL items and return stats.

        Returns a dict with keys: ``processed``, ``resolved``, ``failed``,
        ``skipped``, ``merged``.
        """
        from events import EventType, HydraFlowEvent

        stats: UnstickResult = {
            "processed": 0,
            "resolved": 0,
            "failed": 0,
            "skipped": 0,
            "merged": 0,
        }

        if not hitl_items:
            return stats

        # Filter by cause mode
        if self._config.unstick_all_causes:
            candidates = list(hitl_items)
        else:
            candidates = [
                item
                for item in hitl_items
                if self._is_merge_conflict(self._state.get_hitl_cause(item.issue) or "")
            ]

        # Sort by cause priority (merge conflicts first)
        candidates.sort(
            key=lambda item: _CAUSE_PRIORITY.get(
                _classify_cause(self._state.get_hitl_cause(item.issue) or ""),
                99,
            )
        )

        # Apply batch size limit
        batch_size = self._config.pr_unstick_batch_size
        batch = candidates[:batch_size]
        stats["skipped"] = len(hitl_items) - len(batch)

        # --- PARALLEL FIX PHASE ---
        semaphore = asyncio.Semaphore(batch_size)
        fixed: list[HITLItem] = []
        stuck: list[HITLItem] = []

        async def _fix_one(item: HITLItem) -> tuple[HITLItem, bool]:
            async with semaphore:
                if self._stop_event.is_set():
                    return item, False
                return item, await self._process_item(item)

        tasks = [asyncio.create_task(_fix_one(item)) for item in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            stats["processed"] += 1
            if isinstance(result, BaseException):
                stats["failed"] += 1
                continue
            item, success = result
            if success:
                fixed.append(item)
                stats["resolved"] += 1
            else:
                stuck.append(item)
                stats["failed"] += 1

            action = "unstick_resolved" if success else "unstick_failed"
            issue_num = item.issue if not isinstance(result, BaseException) else 0
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.HITL_UPDATE,
                    data={
                        "issue": issue_num,
                        "action": action,
                        "source": "pr_unsticker",
                    },
                )
            )

        # --- SEQUENTIAL MERGE PHASE ---
        if self._config.unstick_auto_merge and fixed:
            merged_count = await self._merge_phase(fixed)
            stats["merged"] = merged_count

        return stats

    async def _merge_phase(self, fixed_items: list[HITLItem]) -> int:
        """Merge fixed items one at a time, re-rebasing remaining after each."""
        merged = 0
        remaining = list(fixed_items)

        while remaining:
            if self._stop_event.is_set():
                break

            item = remaining.pop(0)
            success = await self._wait_and_merge(item)

            if success:
                merged += 1
                # Pull main and re-rebase remaining items
                if remaining:
                    await self._prs.pull_main()
                    await self._re_rebase_remaining(remaining)
            # If merge failed, item already released back to HITL

        return merged

    async def _process_item(self, item: HITLItem) -> bool:
        """Attempt to resolve issues for a single HITL item.

        Returns *True* if the fix was successful and branch was pushed.
        """
        issue_number = item.issue
        branch = self._config.branch_for_issue(issue_number)
        cause_str = self._state.get_hitl_cause(issue_number) or ""
        cause = _classify_cause(cause_str)

        # Claim: swap labels
        claim_kwargs: dict[str, int] = {}
        if item.pr is not None and item.pr > 0:
            claim_kwargs["pr_number"] = item.pr
        await self._prs.swap_pipeline_labels(
            issue_number, self._config.hitl_active_label[0], **claim_kwargs
        )

        cause_desc = cause.value.replace("_", " ")
        await self._prs.post_comment(
            issue_number,
            f"**PR Unsticker** attempting to resolve {cause_desc}...\n\n"
            "---\n*Automated by HydraFlow PR Unsticker*",
        )

        try:
            # Fetch full issue for prompt context
            issue = await self._fetcher.fetch_issue_by_number(issue_number)
            if not issue:
                logger.warning("Could not fetch issue #%d for unsticker", issue_number)
                await self._release_back_to_hitl(
                    issue_number,
                    "Could not fetch issue",
                    pr_number=item.pr,
                )
                return False

            # Get or create worktree
            wt_path = self._config.worktree_path_for_issue(issue_number)
            if not wt_path.is_dir():
                wt_path = await self._worktrees.create(issue_number, branch)
            self._state.set_worktree(issue_number, str(wt_path))

            # Dispatch to cause-specific resolver
            resolution = await self._resolve_by_cause(
                cause,
                issue_number,
                issue,
                wt_path,
                branch,
                item.prUrl,
                pr_number=item.pr,
            )

            if resolution.success:
                # Push the fixed branch
                if resolution.used_rebuild:
                    new_wt = self._config.worktree_path_for_issue(issue_number)
                    await self._prs.push_branch(new_wt, branch, force=True)
                else:
                    await self._prs.push_branch(wt_path, branch)

                if not self._config.unstick_auto_merge:
                    # Restore origin label when not auto-merging
                    origin = self._state.get_hitl_origin(issue_number)
                    if origin:
                        origin_kwargs: dict[str, int] = {}
                        if item.pr is not None and item.pr > 0:
                            origin_kwargs["pr_number"] = item.pr
                        await self._prs.swap_pipeline_labels(
                            issue_number, origin, **origin_kwargs
                        )
                    else:
                        for lbl in self._config.hitl_active_label:
                            await self._prs.remove_label(issue_number, lbl)

                    self._state.remove_hitl_origin(issue_number)
                    self._state.remove_hitl_cause(issue_number)
                    self._state.reset_issue_attempts(issue_number)

                    await self._prs.post_comment(
                        issue_number,
                        f"**PR Unsticker** resolved {cause_desc} successfully.\n\n"
                        f"Returning issue to `{origin or 'pipeline'}` stage."
                        "\n\n---\n*Automated by HydraFlow PR Unsticker*",
                    )
                # When auto-merge is on, state cleanup happens after merge

                logger.info(
                    "PR Unsticker resolved %s for issue #%d",
                    cause_desc,
                    issue_number,
                )
                return True
            else:
                await self._release_back_to_hitl(
                    issue_number,
                    f"All {cause_desc} resolution attempts exhausted",
                    pr_number=item.pr,
                )
                return False

        except Exception:
            logger.exception("PR Unsticker failed for issue #%d", issue_number)
            await self._release_back_to_hitl(
                issue_number,
                "Unexpected error during resolution",
                pr_number=item.pr,
            )
            return False

    async def _resolve_by_cause(
        self,
        cause: FailureCause,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
        pr_url: str,
        pr_number: int = 0,
    ) -> ConflictResolutionResult:
        """Dispatch to the appropriate resolver based on cause classification.

        Returns a :class:`ConflictResolutionResult` — *used_rebuild* is True
        when the fresh-branch rebuild path was taken (caller should force-push).
        """
        if cause == FailureCause.MERGE_CONFLICT:
            if self._resolver is None:
                logger.error(
                    "#%d: no resolver configured, cannot resolve conflict", issue_number
                )
                return ConflictResolutionResult(success=False, used_rebuild=False)
            from models import PRInfo

            pr = PRInfo(
                number=pr_number,
                issue_number=issue_number,
                branch=branch,
                url=pr_url,
            )
            return await self._resolver.resolve_merge_conflicts(
                pr, issue.to_task(), wt_path, worker_id=None, source="pr_unsticker"
            )
        if cause == FailureCause.CI_TIMEOUT:
            success = await self._resolve_ci_timeout(
                issue_number, issue, wt_path, branch, pr_url=pr_url, pr_number=pr_number
            )
            return ConflictResolutionResult(success=success, used_rebuild=False)
        if cause in (FailureCause.CI_FAILURE, FailureCause.REVIEW_FIX_CAP):
            success = await self._resolve_ci_or_quality(
                issue_number, issue, wt_path, branch, pr_url=pr_url, pr_number=pr_number
            )
            return ConflictResolutionResult(success=success, used_rebuild=False)
        success = await self._resolve_generic(issue_number, issue, wt_path, branch)
        return ConflictResolutionResult(success=success, used_rebuild=False)

    async def _resolve_ci_or_quality(
        self,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
        pr_url: str,
        pr_number: int = 0,
    ) -> bool:
        """Rebase on main and run agent with a CI/quality fix prompt."""
        # First rebase on main
        clean = await self._worktrees.start_merge_main(wt_path, branch)
        if not clean:
            # If there are conflicts during rebase, try to resolve them first
            await self._worktrees.abort_merge(wt_path)

        cause_str = self._state.get_hitl_cause(issue_number) or ""
        prompt, prompt_stats = self._build_ci_fix_prompt(issue, pr_url, cause_str)

        try:
            cmd = self._agents._build_command(wt_path)
            transcript = await self._agents._execute(
                cmd,
                prompt,
                wt_path,
                {"issue": issue_number, "source": "pr_unsticker"},
                telemetry_stats=prompt_stats,
            )
            if self._resolver is not None:
                self._resolver.save_conflict_transcript(
                    pr_number, issue_number, 1, transcript, source="unsticker"
                )
            else:
                logger.warning(
                    "No resolver configured; CI fix transcript for issue #%d not saved",
                    issue_number,
                )

            await safe_file_memory_suggestion(
                transcript,
                "pr_unsticker",
                f"issue #{issue_number}",
                self._config,
                self._prs,
                self._state,
            )

            success, error_msg = await self._agents._verify_result(wt_path, branch)
            if success:
                return True

            logger.warning(
                "CI/quality fix failed for issue #%d: %s",
                issue_number,
                error_msg[:200] if error_msg else "",
            )
            return False
        except Exception as exc:
            logger.error(
                "Unsticker CI fix agent failed for issue #%d: %s",
                issue_number,
                exc,
            )
            return False

    async def _resolve_generic(
        self,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
    ) -> bool:
        """Use HITLRunner for generic/unknown causes."""
        if not self._hitl_runner:
            logger.warning(
                "No HITL runner available for generic fix on issue #%d",
                issue_number,
            )
            return False

        cause_str = self._state.get_hitl_cause(issue_number) or ""
        correction = f"Automated fix attempt by PR Unsticker. Cause: {cause_str}"

        result = await self._hitl_runner.run(
            issue=issue,
            correction=correction,
            cause=cause_str,
            worktree_path=wt_path,
        )
        return result.success

    def _build_ci_fix_prompt(
        self, issue: GitHubIssue, pr_url: str, cause: str
    ) -> tuple[str, dict[str, object]]:
        """Build a targeted prompt for CI/quality fix and pruning stats."""
        cause_text, cause_before, cause_after = truncate_with_notice(
            cause or "", _MAX_UNSTICKER_CAUSE_CHARS, label="Escalation reason"
        )
        prompt = f"""You are fixing CI/quality failures for a pull request.

## Issue: {issue.title}
Issue URL: {issue.url}
PR URL: {pr_url}

## Escalation Reason

{cause_text}

## Instructions

Plan before fixing. Run `make quality` to see failures, then read the
failing code and its context to understand the root cause. Check git log
to see if a recent merge introduced the problem. You can read any file
in the repo or use `gh` CLI for additional context.

Common causes after a merge-main: duplicate Pydantic Field definitions,
duplicate function parameters, or stale test assertions. grep for the
field or string name if you suspect duplicates.

Fix root causes — do NOT skip, disable, or weaken any tests or checks.
Run `make quality` again to verify. Before committing, review your own
diff — you may catch things `make quality` won't.

## Rules

- Follow the project's CLAUDE.md guidelines strictly.
- Write tests for all new code — tests are mandatory.
- Do NOT push to remote. Do NOT create pull requests.
- Do NOT run `git push` or `gh pr create`.
- Ensure `make quality` passes before committing.
"""
        stats = build_prompt_stats(
            history_before=cause_before,
            history_after=cause_after,
            section_chars={
                "cause_before": cause_before,
                "cause_after": cause_after,
            },
        )
        return prompt, stats

    async def _resolve_ci_timeout(
        self,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
        pr_url: str,
        pr_number: int = 0,
    ) -> bool:
        """Rebase on main, isolate the hanging test, and run agent to fix it.

        Retries up to ``max_ci_timeout_fix_attempts`` times before giving up.
        """
        max_attempts = self._config.max_ci_timeout_fix_attempts

        # Read path: load learned patterns from store
        learned_section = ""
        language = "general"
        if self._troubleshooting_store is not None:
            language = self._detect_language(wt_path)
            patterns = self._troubleshooting_store.load_patterns(
                language=language,
                limit=10,
            )
            if patterns:
                from troubleshooting_store import format_patterns_for_prompt

                learned_section = format_patterns_for_prompt(
                    patterns,
                    max_chars=self._config.max_troubleshooting_prompt_chars,
                )

        for attempt in range(1, max_attempts + 1):
            # Rebase on main
            clean = await self._worktrees.start_merge_main(wt_path, branch)
            if not clean:
                await self._worktrees.abort_merge(wt_path)

            # Isolate which test hangs
            isolation_output = await self._isolate_hanging_tests(wt_path)

            cause_str = self._state.get_hitl_cause(issue_number) or ""
            prompt, prompt_stats = self._build_ci_timeout_fix_prompt(
                issue,
                pr_url,
                cause_str,
                isolation_output,
                learned_patterns_section=learned_section,
            )

            try:
                cmd = self._agents._build_command(wt_path)
                transcript = await self._agents._execute(
                    cmd,
                    prompt,
                    wt_path,
                    {"issue": issue_number, "source": "pr_unsticker"},
                    telemetry_stats=prompt_stats,
                )
                if self._resolver is not None:
                    self._resolver.save_conflict_transcript(
                        pr_number, issue_number, attempt, transcript, source="unsticker"
                    )

                await safe_file_memory_suggestion(
                    transcript,
                    "pr_unsticker",
                    f"issue #{issue_number}",
                    self._config,
                    self._prs,
                    self._state,
                )

                success, error_msg = await self._agents._verify_result(wt_path, branch)
                if success:
                    # Write path: persist pattern from transcript
                    await self._persist_troubleshooting_pattern(
                        transcript, issue_number, language
                    )
                    return True

                logger.warning(
                    "CI timeout fix attempt %d/%d failed for issue #%d: %s",
                    attempt,
                    max_attempts,
                    issue_number,
                    error_msg[:200] if error_msg else "",
                )
            except Exception as exc:
                logger.error(
                    "Unsticker CI timeout agent failed for issue #%d (attempt %d): %s",
                    issue_number,
                    attempt,
                    exc,
                )

        return False

    def _detect_language(self, wt_path: Path) -> str:
        """Detect the project language from the worktree path."""
        try:
            from polyglot_prep import detect_prep_stack

            return detect_prep_stack(wt_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Falling back to 'general' language classification for %s: %s",
                wt_path,
                exc,
                exc_info=True,
            )
            return "general"

    async def _persist_troubleshooting_pattern(
        self, transcript: str, issue_number: int, language: str
    ) -> None:
        """Extract and persist a troubleshooting pattern from a successful fix.

        Two-stage approach:
        1. Check for an explicit ``TROUBLESHOOTING_PATTERN`` block (free, instant).
        2. If none found, run a cheap model reflection to extract the insight
           and check novelty against the existing store.
        """
        if self._troubleshooting_store is None:
            return
        try:
            from troubleshooting_store import extract_troubleshooting_pattern

            # Stage 1: explicit block from agent
            pattern = extract_troubleshooting_pattern(
                transcript, issue_number, language
            )
            if pattern is not None:
                self._troubleshooting_store.append_pattern(pattern)
                logger.info(
                    "Persisted troubleshooting pattern '%s' from issue #%d (explicit)",
                    pattern.pattern_name,
                    issue_number,
                )
                return

            # Stage 2: self-reflection via cheap model
            pattern = await self._reflect_on_fix(transcript, issue_number, language)
            if pattern is not None:
                self._troubleshooting_store.append_pattern(pattern)
                logger.info(
                    "Persisted troubleshooting pattern '%s' from issue #%d (reflection)",
                    pattern.pattern_name,
                    issue_number,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to persist troubleshooting pattern for issue #%d: %s",
                issue_number,
                exc,
                exc_info=True,
            )

    async def _reflect_on_fix(
        self,
        transcript: str,
        issue_number: int,
        language: str,
    ) -> TroubleshootingPattern | None:
        """Run a cheap model to extract a troubleshooting pattern from the transcript.

        Compares against known patterns in the store and only returns a pattern
        if it identifies something novel.  Returns ``None`` if the model call
        fails or nothing new is found.
        """
        from troubleshooting_store import extract_troubleshooting_pattern

        store = self._troubleshooting_store
        if store is None:
            return None

        known = store.load_patterns(limit=50)
        known_block = "\n".join(f"- {p.pattern_name}: {p.description}" for p in known)

        # Truncate transcript to keep the prompt small
        max_transcript = 6000
        trimmed = (
            transcript[-max_transcript:]
            if len(transcript) > max_transcript
            else transcript
        )

        prompt = f"""You are analyzing a successful CI timeout fix to extract reusable troubleshooting knowledge.

## Transcript (tail)

{trimmed}

## Already-known patterns

{known_block or "(none)"}

## Task

If the fix above addresses a hang pattern that is NOT already covered by the known patterns,
emit a structured block. If the fix is just a variant of an existing pattern, output NOTHING.

Only emit a block if the root cause is genuinely distinct from every known pattern above.

```
TROUBLESHOOTING_PATTERN_START
pattern_name: <short_snake_case_key>
description: <what causes the hang — one sentence>
fix_strategy: <how to fix it — one sentence>
TROUBLESHOOTING_PATTERN_END
```

If nothing novel, output exactly: NO_NEW_PATTERN"""

        from subprocess_util import make_clean_env

        tool = self._config.background_tool
        if tool == "inherit":
            tool = "claude"
        model = self._config.background_model or "haiku"

        if tool == "codex":
            cmd = [
                "codex",
                "exec",
                "--json",
                "--model",
                model,
                "--sandbox",
                "danger-full-access",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                prompt,
            ]
            cmd_input = None
        else:
            cmd = [tool, "-p", prompt, "--model", model]
            cmd_input = None

        env = make_clean_env(self._config.gh_token)

        try:
            result = await self._agents._runner.run_simple(
                cmd,
                env=env,
                input=cmd_input,
                timeout=60.0,
            )
            if result.returncode != 0:
                logger.debug(
                    "Troubleshooting reflection model failed (rc=%d)",
                    result.returncode,
                )
                return None

            output = result.stdout or ""
            if "NO_NEW_PATTERN" in output:
                logger.debug(
                    "Reflection found no novel pattern for issue #%d", issue_number
                )
                return None

            return extract_troubleshooting_pattern(output, issue_number, language)
        except (TimeoutError, OSError, FileNotFoundError) as exc:
            logger.debug("Troubleshooting reflection unavailable: %s", exc)
            return None

    async def _isolate_hanging_tests(self, wt_path: Path) -> str:
        """Run the project's test command with a short subprocess timeout.

        Uses the configured ``test_command`` so it works for any language.
        Sets ``PYTHONPATH`` for Python projects (harmless for others).

        Returns a string describing test output before the timeout hit,
        or an error message if isolation itself failed.
        """
        import os
        import shlex

        src_dir = str(wt_path / "src")
        existing = os.environ.get("PYTHONPATH", "")
        env = {
            **os.environ,
            "PYTHONPATH": f"{src_dir}{os.pathsep}{existing}" if existing else src_dir,
        }

        test_cmd = self._config.test_command
        cmd = shlex.split(test_cmd) if test_cmd else ["make", "test"]

        try:
            result = await self._agents._runner.run_simple(
                cmd,
                cwd=str(wt_path),
                timeout=120.0,
                env=env,
            )
            return (
                f"Test command `{test_cmd}` completed (rc={result.returncode}):\n"
                f"{result.stdout[-2000:]}"
            )
        except TimeoutError:
            return (
                f"Test command `{test_cmd}` timed out after 120s — "
                "tests are hanging. Check the test output for the last test "
                "that started running before the timeout."
            )
        except Exception as exc:
            return f"Test isolation failed ({test_cmd}): {exc}"

    def _build_ci_timeout_fix_prompt(
        self,
        issue: GitHubIssue,
        pr_url: str,
        cause: str,
        isolation_output: str,
        *,
        learned_patterns_section: str = "",
    ) -> tuple[str, dict[str, object]]:
        """Build a targeted prompt for fixing hanging tests."""
        cause_text, cause_before, cause_after = truncate_with_notice(
            cause or "", _MAX_UNSTICKER_CAUSE_CHARS, label="Escalation reason"
        )
        isolation_text, iso_before, iso_after = truncate_with_notice(
            isolation_output or "", _MAX_UNSTICKER_CAUSE_CHARS, label="Test isolation"
        )

        learned_block = (
            f"\n{learned_patterns_section}\n" if learned_patterns_section else ""
        )

        prompt = f"""You are fixing a CI timeout caused by hanging tests in a pull request.

## Issue: {issue.title}
Issue URL: {issue.url}
PR URL: {pr_url}

## Escalation Reason

{cause_text}

## Test Isolation Output

{isolation_text}

## Common Causes of Hanging Tests

**General (any language):**
- **Infinite polling loops**: Test mocks return a truthy "work available" value on every call, \
so a loop that skips sleep when work is done never yields. Fix: ensure mocks return "no work" \
(falsy/empty) by default.
- **Unresolved async waits**: Tests await on events, futures, promises, or channels that \
never complete. Fix: ensure the mock or test setup triggers the completion signal.
- **Deadlocks**: Multiple concurrent tasks/threads waiting on each other's locks or results.
- **Missing teardown**: Servers, listeners, or background threads started in tests that \
never get shut down, preventing the test process from exiting.

**Python-specific:**
- **Truthy AsyncMock**: `AsyncMock()` without `return_value` returns a truthy MagicMock, \
causing `while await work_fn()` or `did_work = bool(await fn())` loops to spin forever. \
Fix: set `return_value` to a falsy value matching the function's return type — \
`return_value=0` for int, `return_value=[]` for list, `return_value=False` for bool.
- **Missing event.set()**: Tests that wait on `asyncio.Event` objects that never get set.
{learned_block}
## Instructions

1. Identify which test is hanging from the test output above (the last test that started running).
2. Read the hanging test and the code it exercises.
3. Fix the **root cause** — do NOT mask the problem with timeouts or skip markers.
4. **Search the same file for other occurrences of the same pattern** (e.g., other mocks \
with the same issue). Fix ALL instances, not just the one that hangs — unfixed siblings \
will hang on the next CI run.
5. Run `make quality` to verify all tests pass and no new issues are introduced.
6. Commit fixes with a descriptive message.

## Pattern Reporting

If you identify a new hang pattern not already listed above, emit a structured block so it \
can be learned for future fixes:

```
TROUBLESHOOTING_PATTERN_START
pattern_name: <short_key, e.g. truthy_asyncmock>
description: <what causes the hang>
fix_strategy: <how to fix it>
TROUBLESHOOTING_PATTERN_END
```

## Rules

- Follow the project's CLAUDE.md guidelines strictly.
- Write tests for all new code — tests are mandatory.
- Do NOT push to remote. Do NOT create pull requests.
- Do NOT run `git push` or `gh pr create`.
- Ensure `make quality` passes before committing.
"""
        stats = build_prompt_stats(
            history_before=cause_before + iso_before,
            history_after=cause_after + iso_after,
            section_chars={
                "cause_before": cause_before,
                "cause_after": cause_after,
                "isolation_before": iso_before,
                "isolation_after": iso_after,
            },
        )
        return prompt, stats

    async def _wait_and_merge(self, item: HITLItem) -> bool:
        """Wait for CI to pass, then squash-merge the PR.

        Returns *True* if the merge succeeded.
        """
        issue_number = item.issue
        pr_number = item.pr

        if not pr_number:
            logger.warning("No PR number for issue #%d — skipping merge", issue_number)
            # Still clean up state
            self._finalize_resolved(issue_number)
            return False

        # Wait for CI
        passed, summary = await self._prs.wait_for_ci(
            pr_number,
            self._config.ci_check_timeout,
            self._config.ci_poll_interval,
            self._stop_event,
        )

        if not passed:
            logger.warning(
                "CI failed for PR #%d (issue #%d): %s",
                pr_number,
                issue_number,
                summary,
            )
            await self._release_back_to_hitl(
                issue_number,
                f"CI failed after fix: {summary}",
                pr_number=pr_number,
            )
            return False

        # Squash merge
        success = await self._prs.merge_pr(pr_number)
        if success:
            self._finalize_resolved(issue_number, merged=True)
            await self._prs.post_comment(
                issue_number,
                "**PR Unsticker** merged PR successfully after fix.\n\n"
                "---\n*Automated by HydraFlow PR Unsticker*",
            )
            logger.info(
                "PR Unsticker merged PR #%d for issue #%d",
                pr_number,
                issue_number,
            )
            return True
        else:
            await self._release_back_to_hitl(
                issue_number,
                f"Merge failed for PR #{pr_number}",
                pr_number=pr_number,
            )
            return False

    def _finalize_resolved(self, issue_number: int, *, merged: bool = False) -> None:
        """Clean up HITL state after successful resolution."""
        self._state.remove_hitl_origin(issue_number)
        self._state.remove_hitl_cause(issue_number)
        self._state.reset_issue_attempts(issue_number)
        if merged:
            self._state.record_pr_merged()

    async def _re_rebase_remaining(self, remaining: list[HITLItem]) -> None:
        """Rebase remaining fixed items on updated main after a merge.

        When a merge introduces conflicts, the merge is aborted and the
        item is flagged so the next unstick cycle can resolve it properly
        rather than silently losing the failure.
        """
        for item in remaining:
            issue_number = item.issue
            branch = self._config.branch_for_issue(issue_number)
            wt_path = self._config.worktree_path_for_issue(issue_number)

            if not wt_path.is_dir():
                continue

            try:
                clean = await self._worktrees.start_merge_main(wt_path, branch)
                if not clean:
                    await self._worktrees.abort_merge(wt_path)
                    logger.warning(
                        "Re-rebase for issue #%d hit conflicts after sibling "
                        "merge — will resolve on next unstick cycle",
                        issue_number,
                    )
                    self._state.set_hitl_cause(
                        issue_number,
                        "Cascade conflict: merge main after sibling PR merged",
                    )
            except Exception:
                logger.warning(
                    "Re-rebase failed for issue #%d after merge",
                    issue_number,
                    exc_info=True,
                )

    async def _release_back_to_hitl(
        self, issue_number: int, reason: str, *, pr_number: int | None = None
    ) -> None:
        """Remove active label and re-add HITL label."""
        release_kwargs: dict[str, int] = {}
        if pr_number is not None and pr_number > 0:
            release_kwargs["pr_number"] = pr_number
        await self._prs.swap_pipeline_labels(
            issue_number,
            self._config.hitl_label[0],
            **release_kwargs,
        )
        await self._prs.post_comment(
            issue_number,
            f"**PR Unsticker** could not resolve: {reason}\n\n"
            "Returning to HITL for manual intervention."
            "\n\n---\n*Automated by HydraFlow PR Unsticker*",
        )

    def _is_merge_conflict(self, cause: str) -> bool:
        """Return *True* if *cause* indicates a merge conflict."""
        lower = cause.lower()
        return any(kw in lower for kw in _MERGE_CONFLICT_KEYWORDS)
