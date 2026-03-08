"""Planning agent runner — launches Claude Code to explore and plan issue implementation."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Literal

from agent_cli import build_agent_command
from base_runner import BaseRunner
from events import EventType, HydraFlowEvent
from models import NewIssueSpec, PlannerStatus, PlanResult, Task
from runner_constants import MEMORY_SUGGESTION_PROMPT
from subprocess_util import CreditExhaustedError

logger = logging.getLogger("hydraflow.planner")

PlanScale = Literal["lite", "full"]

# Canonical section descriptions — single source of truth for prompt generation.
# Each entry is (header, description).  Order matches the desired prompt order.
_PLAN_SECTION_DESCRIPTIONS: tuple[tuple[str, str], ...] = (
    (
        "## Files to Modify",
        "list each existing file and what changes are needed "
        "(must reference at least one file path)",
    ),
    (
        "## New Files",
        'list new files to create, or state "None" if no new files needed',
    ),
    (
        "## File Delta",
        "structured list of all planned file changes using this exact format:\n"
        "  ```\n"
        "  MODIFIED: path/to/file.py\n"
        "  ADDED: path/to/new_file.py\n"
        "  REMOVED: path/to/old_file.py\n"
        "  ```\n"
        "  Each line must start with MODIFIED:, ADDED:, or REMOVED: "
        "followed by the file path.",
    ),
    (
        "## Implementation Steps",
        "actionable implementation checklist/steps (numbered, bulleted, checkbox, or heading-style) "
        "with concrete code targets and at least one verification step",
    ),
    (
        "## Testing Strategy",
        "what tests to write and what to verify "
        "(must reference specific test file paths or patterns; do NOT defer testing)",
    ),
    (
        "## Acceptance Criteria",
        "extracted or synthesized from the issue",
    ),
    (
        "## Key Considerations",
        "edge cases, backward compatibility, dependencies",
    ),
)


class PlannerRunner(BaseRunner):
    """Launches a ``claude -p`` process to explore the codebase and create an implementation plan.

    The planner works READ-ONLY against the repo root (no worktree needed).
    It produces a structured plan that is posted as a comment on the issue.
    """

    _log = logger

    async def plan(
        self,
        task: Task,
        worker_id: int = 0,
    ) -> PlanResult:
        """Run the planning agent for *task*.

        Returns a :class:`PlanResult` with the plan and summary.

        On validation failure the planner is retried once with specific
        feedback.  If the second attempt also fails, the result carries
        ``retry_attempted=True`` so the orchestrator can escalate to HITL.
        """
        start = time.monotonic()
        result = PlanResult(issue_number=task.id)

        await self._emit_status(task.id, worker_id, PlannerStatus.PLANNING)

        if self._config.dry_run:
            logger.info("[dry-run] Would plan issue #%d", task.id)
            result.success = True
            result.summary = "Dry-run: plan skipped"
            result.duration_seconds = time.monotonic() - start
            await self._emit_status(task.id, worker_id, PlannerStatus.DONE)
            return result

        try:
            scale = self._detect_plan_scale(task)
            logger.info("Issue #%d classified as %s plan", task.id, scale)

            cmd = self._build_command()
            prompt, prompt_stats = self._build_prompt_with_stats(task, scale=scale)

            def _check_plan_complete(accumulated: str) -> bool:
                if "PLAN_END" in accumulated:
                    logger.info(
                        "Plan markers found for issue #%d — terminating planner",
                        task.id,
                    )
                    return True
                if "ALREADY_SATISFIED_END" in accumulated:
                    logger.info(
                        "Already-satisfied markers found for issue #%d — terminating planner",
                        task.id,
                    )
                    return True
                return False

            transcript = await self._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "planner"},
                on_output=_check_plan_complete,
                telemetry_stats=prompt_stats,
            )
            result.transcript = transcript

            # Check for already-satisfied before plan extraction
            satisfied_explanation = self._extract_already_satisfied(transcript)
            if satisfied_explanation:
                result.already_satisfied = True
                result.success = True
                result.summary = satisfied_explanation[:200]
                result.duration_seconds = time.monotonic() - start
                try:
                    self._save_transcript("plan-issue", task.id, result.transcript)
                except OSError:
                    logger.warning(
                        "Failed to save transcript for issue #%d",
                        task.id,
                        exc_info=True,
                        extra={"issue": task.id},
                    )
                await self._emit_status(task.id, worker_id, PlannerStatus.DONE)
                logger.info(
                    "Issue #%d already satisfied — no changes needed",
                    task.id,
                )
                return result

            result.plan = self._extract_plan(transcript)
            result.summary = self._extract_summary(transcript)
            result.new_issues = self._extract_new_issues(transcript)

            if result.plan:
                (
                    result.actionability_score,
                    result.actionability_rank,
                ) = self._score_actionability(result.plan, scale=scale)
                await self._emit_status(task.id, worker_id, PlannerStatus.VALIDATING)
                validation_errors = self._validate_plan(task, result.plan, scale=scale)
                if scale == "lite":
                    gate_errors: list[str] = []
                else:
                    gate_errors, _gate_warnings = self._run_phase_minus_one_gates(
                        result.plan
                    )
                all_errors = validation_errors + gate_errors
                result.validation_errors = all_errors

                if not all_errors:
                    result.success = True
                else:
                    # --- Retry once with feedback ---
                    logger.warning(
                        "Plan for issue #%d failed validation (%d errors) — retrying",
                        task.id,
                        len(all_errors),
                    )
                    await self._emit_status(task.id, worker_id, PlannerStatus.RETRYING)
                    retry_prompt, retry_stats = self._build_retry_prompt(
                        task, result.plan, all_errors, scale=scale
                    )
                    retry_transcript = await self._execute(
                        cmd,
                        retry_prompt,
                        self._config.repo_root,
                        {"issue": task.id, "source": "planner"},
                        on_output=_check_plan_complete,
                        telemetry_stats=retry_stats,
                    )
                    result.transcript += "\n\n--- RETRY ---\n\n" + retry_transcript

                    retry_plan = self._extract_plan(retry_transcript)
                    if retry_plan:
                        (
                            result.actionability_score,
                            result.actionability_rank,
                        ) = self._score_actionability(retry_plan, scale=scale)
                        retry_validation = self._validate_plan(
                            task, retry_plan, scale=scale
                        )
                        if scale == "lite":
                            retry_gate_errors: list[str] = []
                        else:
                            retry_gate_errors, _ = self._run_phase_minus_one_gates(
                                retry_plan
                            )
                        retry_all_errors = retry_validation + retry_gate_errors
                        if not retry_all_errors:
                            result.plan = retry_plan
                            result.summary = self._extract_summary(retry_transcript)
                            result.new_issues = self._extract_new_issues(
                                retry_transcript
                            )
                            result.validation_errors = []
                            result.success = True
                        else:
                            result.validation_errors = retry_all_errors
                            result.retry_attempted = True
                            result.success = False
                    else:
                        result.retry_attempted = True
                        result.success = False
            else:
                result.success = False

            status = PlannerStatus.DONE if result.success else PlannerStatus.FAILED
            await self._emit_status(task.id, worker_id, status)

        except CreditExhaustedError:
            raise
        except Exception as exc:
            result.success = False
            result.error = str(exc)
            logger.error(
                "Planner failed for issue #%d: %s",
                task.id,
                exc,
                extra={"issue": task.id},
            )
            await self._emit_status(task.id, worker_id, PlannerStatus.FAILED)

        result.duration_seconds = time.monotonic() - start
        try:
            self._save_transcript("plan-issue", task.id, result.transcript)
        except OSError:
            logger.warning(
                "Failed to save transcript for issue #%d",
                task.id,
                exc_info=True,
                extra={"issue": task.id},
            )
        if result.success and result.plan:
            try:
                self._save_plan(task.id, result.plan, result.summary)
            except OSError:
                logger.warning(
                    "Failed to save plan for issue #%d",
                    task.id,
                    exc_info=True,
                    extra={"issue": task.id},
                )
        return result

    def _build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Construct the CLI invocation for planning.

        The *_worktree_path* parameter is accepted for API compatibility with
        ``BaseRunner._build_command`` but is unused — the planner always runs
        against ``self._config.repo_root``, not an isolated worktree.
        """
        return build_agent_command(
            tool=self._config.planner_tool,
            model=self._config.planner_model,
            disallowed_tools="Write,Edit,NotebookEdit",
        )

    # Maximum characters for comments in the prompt.
    # Keep conservative to avoid hitting Claude CLI's internal text-splitter
    # limits (RecursiveCharacterTextSplitter fails on very long unsplittable lines).
    _MAX_COMMENT_CHARS = 1_000
    _MAX_LINE_CHARS = 500

    @staticmethod
    def _truncate_text(text: str, char_limit: int, line_limit: int) -> str:
        """Truncate *text* at a line boundary, also breaking long lines.

        Lines exceeding *line_limit* are hard-truncated to avoid producing
        unsplittable chunks that crash Claude CLI's text splitter.
        """
        lines: list[str] = []
        total = 0
        for raw_line in text.splitlines():
            capped = (
                raw_line[:line_limit] + "…" if len(raw_line) > line_limit else raw_line
            )
            if total + len(capped) + 1 > char_limit:
                break
            lines.append(capped)
            total += len(capped) + 1  # +1 for newline
        result = "\n".join(lines)
        if len(result) < len(text):
            result += "\n\n…(truncated)"
        return result

    # Patterns for detecting images in issue bodies (markdown and HTML).
    _IMAGE_RE = re.compile(r"!\[.*?\]\(.*?\)|<img\s[^>]*>", re.IGNORECASE)

    @classmethod
    def _format_sections_list(cls, scale: PlanScale = "full") -> str:
        """Return a formatted bullet list of required sections for *scale*.

        Filters :data:`_PLAN_SECTION_DESCRIPTIONS` to only include sections
        present in :attr:`LITE_REQUIRED_SECTIONS` when *scale* is ``"lite"``,
        or :attr:`REQUIRED_SECTIONS` for any other value (including ``"full"``).
        """
        required = (
            cls.LITE_REQUIRED_SECTIONS if scale == "lite" else cls.REQUIRED_SECTIONS
        )
        required_set = set(required)
        lines = []
        for header, desc in _PLAN_SECTION_DESCRIPTIONS:
            if header in required_set:
                lines.append(f"- `{header}` \u2014 {desc}")
        return "\n".join(lines)

    def _build_prompt(self, issue: Task, *, scale: PlanScale = "full") -> str:
        """Build the planning prompt for the agent.

        Compatibility wrapper that returns only the prompt string.
        """
        prompt, _stats = self._build_prompt_with_stats(issue, scale=scale)
        return prompt

    def _build_prompt_with_stats(
        self, issue: Task, *, scale: PlanScale = "full"
    ) -> tuple[str, dict[str, object]]:
        """Build the planning prompt and pruning stats.

        *scale* is ``"lite"`` or ``"full"``.  The prompt adjusts which
        sections are required and whether to include the pre-mortem step.
        """
        comments_section = ""
        history_before = sum(len(c) for c in issue.comments)
        history_after = 0
        if issue.comments:
            max_comments = 6
            selected_comments = issue.comments[:max_comments]
            truncated = [
                self._truncate_text(c, self._MAX_COMMENT_CHARS, self._MAX_LINE_CHARS)
                for c in selected_comments
            ]
            formatted = "\n".join(f"- {c}" for c in truncated)
            history_after = len(formatted)
            comments_section = f"\n\n## Discussion\n{formatted}"
            if len(issue.comments) > max_comments:
                comments_section += f"\n- ... ({len(issue.comments) - max_comments} more comments omitted)"

        body_raw = issue.body or ""
        body = self._truncate_text(
            issue.body or "", self._config.max_issue_body_chars, self._MAX_LINE_CHARS
        )

        # Detect attached images and add a note for the planner.
        image_note = ""
        if self._IMAGE_RE.search(issue.body or ""):
            image_note = (
                "\n\n**Note:** This issue contains attached images providing "
                "visual context. The images cannot be rendered here, but "
                "the surrounding text describes what they show."
            )

        manifest_section, memory_section = self._inject_manifest_and_memory()

        find_label = self._config.find_label[0]

        # --- Scale-adaptive schema section ---
        sections_bullet_list = self._format_sections_list(scale)
        if scale == "lite":
            mode_note = (
                "**Plan mode: LITE** — This is a small issue (bug fix, typo, or docs). "
                "Only the core sections are required.\n\n"
            )
            schema_section = (
                "## Plan Format — LITE SCHEMA\n\n"
                "Your plan MUST include ALL of the following sections with these EXACT headers.\n"
                "Plans missing any required section will be rejected and you will be asked to retry.\n\n"
                f"{sections_bullet_list}"
            )
            pre_mortem_section = ""
        else:
            mode_note = (
                "**Plan mode: FULL** — This issue requires a comprehensive plan "
                "with all sections.\n\n"
            )
            schema_section = (
                "## Plan Format — REQUIRED SCHEMA\n\n"
                "Your plan MUST include ALL of the following sections with these EXACT headers.\n"
                "Plans missing any required section will be rejected and you will be asked to retry.\n\n"
                f"{sections_bullet_list}"
            )
            pre_mortem_section = (
                "\n\n## Pre-Mortem\n\n"
                "Before finalizing your plan, conduct a brief pre-mortem: assume this implementation\n"
                "failed. What are the top 3 most likely reasons for failure? Add these as risks in the\n"
                "`## Key Considerations` section."
            )

        prompt = f"""You are a planning agent for GitHub issue #{issue.id}.

## Issue: {issue.title}

{body}{image_note}{comments_section}{manifest_section}{memory_section}

## Instructions

{mode_note}You are in READ-ONLY mode. Do NOT create, modify, or delete any files.
Do NOT run any commands that change state (no git commit, no file writes, no installs).

Your job: explore code and produce a concrete implementation plan.

## Exploration Strategy — USE SEMANTIC TOOLS

Use semantic tools first (before grep):
- `claude-context search_code` to find relevant code by intent.
- `claude-context index_codebase` only if search says index is missing.
- `cclsp` (`find_definition`, `find_references`, `find_implementation`,
  `get_incoming_calls`, `get_outgoing_calls`, `find_workspace_symbols`) to trace impact.

### UI Exploration (when the issue involves UI changes)

- Search `src/ui/src/components/` to inventory existing components and their patterns
- Check `src/ui/src/constants.js`, `src/ui/src/types.js`, and `src/ui/src/theme.js` for shared definitions
- Examine existing component styles for spacing, color palette (theme tokens), and layout approach
- Note whether existing components handle responsive behavior

## Planning Steps

1. Restate the issue in your own words.
2. Explore relevant code with semantic tools.
3. Identify concrete file-level deltas.
4. Define testing strategy and edge cases.
5. For UI work, call out reusable components/shared modules (`constants.js`, `types.js`, `theme.js`).

## Required Output

Output your plan between these exact markers:

PLAN_START
<your detailed implementation plan here>
PLAN_END

Then provide a one-line summary:
SUMMARY: <brief one-line description of the plan>

{schema_section}{pre_mortem_section}

## Handling Uncertainty

If a requirement is ambiguous, add
`[NEEDS CLARIFICATION: <brief description>]` instead of guessing.
Plans with 0-3 markers are acceptable; 4+ will escalate to human review.

## Optional: Discovered Issues

If you discover bugs/tech debt/out-of-scope work, optionally propose issues:

NEW_ISSUES_START
- title: Short issue title
  body: Detailed description of the issue (at least 2-3 sentences). Include what the
    problem is, where in the codebase it occurs, and what the expected behavior should be.
  labels: {find_label}
- title: Another issue
  body: Another detailed description with enough context for someone to understand
    and act on it without additional research.
  labels: {find_label}
NEW_ISSUES_END

Only include this section for real findings.
Each issue body must be detailed (>=50 chars) with file/context.
Use only label `{find_label}`.

## Already Satisfied

IMPORTANT: This should be used VERY RARELY. Only if the EXACT feature described in the
issue is ALREADY fully implemented, tested, and working. You must be able to prove it.

Before marking as already satisfied, verify ALL of the following:
1. The specific functions/classes requested in the issue ALREADY EXIST (cite exact file:line)
2. Existing tests ALREADY COVER the described behavior (cite test names)
3. The acceptance criteria in the issue are ALL already met by existing code

DO NOT mark as already satisfied if:
- The feature is similar to something that exists but not identical
- The infrastructure exists but the specific feature does not
- Related code exists but the issue asks for NEW functionality
- You are unsure — when in doubt, produce a plan

If ALL verification checks above pass, output:

ALREADY_SATISFIED_START
Evidence:
- Feature: <exact function/class name at file:line that implements this>
- Tests: <exact test names that verify this behavior>
- Criteria: <how each acceptance criterion is already met>
ALREADY_SATISFIED_END

This closes the issue automatically. False positives waste significant human time.

{MEMORY_SUGGESTION_PROMPT.format(context="planning")}"""
        stats = {
            "history_chars_before": history_before,
            "history_chars_after": history_after,
            "context_chars_before": len(body_raw),
            "context_chars_after": len(body),
            "pruned_chars_total": max(0, history_before - history_after)
            + max(0, len(body_raw) - len(body)),
            "section_chars": {
                "issue_body_before": len(body_raw),
                "issue_body_after": len(body),
                "discussion_before": history_before,
                "discussion_after": history_after,
            },
        }
        return prompt, stats

    # Required plan sections — each must appear as a ## header.
    REQUIRED_SECTIONS: tuple[str, ...] = (
        "## Files to Modify",
        "## New Files",
        "## File Delta",
        "## Implementation Steps",
        "## Testing Strategy",
        "## Acceptance Criteria",
        "## Key Considerations",
    )

    # Lite plans require only these three sections.
    LITE_REQUIRED_SECTIONS: tuple[str, ...] = (
        "## Files to Modify",
        "## Implementation Steps",
        "## Testing Strategy",
    )

    # Body length threshold for scale detection heuristic.
    _LITE_BODY_THRESHOLD = 500

    # Title keywords suggesting a small fix (used with body length heuristic).
    _SMALL_FIX_WORDS: frozenset[str] = frozenset(
        {"fix", "typo", "correct", "patch", "update", "rename", "bump", "tweak"}
    )

    # Pattern for detecting deferred testing strategy.
    _TEST_LATER_RE = re.compile(
        r"\b(later|tbd|todo|to\s+be\s+determined|will\s+be\s+added\s+later)\b",
        re.IGNORECASE,
    )

    def _detect_plan_scale(self, issue: Task) -> PlanScale:
        """Determine whether *issue* needs a ``"lite"`` or ``"full"`` plan.

        Lite plans are used for small issues (bug fixes, typos, docs).
        Full plans are the default for features and multi-file changes.
        """
        lite_labels = {lbl.lower() for lbl in self._config.lite_plan_labels}
        for label in issue.tags:
            if label.lower() in lite_labels:
                return "lite"

        body_len = len(issue.body or "")
        if body_len < self._LITE_BODY_THRESHOLD:
            title_words = {w.lower() for w in issue.title.split()}
            if title_words & self._SMALL_FIX_WORDS:
                return "lite"

        return "full"

    @staticmethod
    def _significant_words(text: str, min_length: int = 4) -> set[str]:
        """Return lowercase words from *text* that are at least *min_length* chars.

        Filters out common stop words to focus on meaningful terms.
        """
        stop = {
            "this",
            "that",
            "with",
            "from",
            "have",
            "been",
            "will",
            "should",
            "would",
            "could",
            "about",
            "into",
            "when",
            "them",
            "then",
            "than",
            "also",
            "more",
            "some",
            "only",
            "each",
            "make",
            "like",
            "need",
            "does",
        }
        words = set()
        for w in re.findall(r"[a-zA-Z]+", text.lower()):
            if len(w) >= min_length and w not in stop:
                words.add(w)
        return words

    def _validate_plan(
        self, issue: Task, plan: str, scale: PlanScale = "full"
    ) -> list[str]:
        """Validate that *plan* has all required sections and minimum content.

        *scale* is ``"lite"`` or ``"full"``.  Lite plans only require three
        sections and skip the minimum word count check.

        Returns a list of validation error strings.  An empty list means the
        plan is valid.
        """
        errors: list[str] = []

        required = (
            self.LITE_REQUIRED_SECTIONS if scale == "lite" else self.REQUIRED_SECTIONS
        )

        # --- Required sections ---
        for section in required:
            if not re.search(re.escape(section), plan, re.IGNORECASE):
                errors.append(f"Missing required section: {section}")

        # --- Files to Modify must reference at least one file path ---
        ftm_match = re.search(
            r"## Files to Modify\s*\n(.*?)(?=\n## |\Z)", plan, re.DOTALL | re.IGNORECASE
        )
        if ftm_match:
            ftm_body = ftm_match.group(1)
            # Look for path-like patterns: word/word or word.ext
            if not re.search(r"[\w\-]+(?:/[\w\-]+)+|[\w\-]+\.[\w]+", ftm_body):
                errors.append(
                    "## Files to Modify must reference at least one file path"
                )

        # --- Testing Strategy must reference at least one test file/pattern ---
        ts_match = re.search(
            r"## Testing Strategy\s*\n(.*?)(?=\n## |\Z)",
            plan,
            re.DOTALL | re.IGNORECASE,
        )
        if ts_match:
            ts_body = ts_match.group(1)
            if not re.search(r"test[\w\-]*\.[\w]+|tests/", ts_body, re.IGNORECASE):
                errors.append(
                    "## Testing Strategy must reference at least one test file or pattern"
                )

        # --- Implementation Steps must contain at least one actionable step ---
        is_match = re.search(
            r"## Implementation Steps\s*\n(.*?)(?=\n## |\Z)",
            plan,
            re.DOTALL | re.IGNORECASE,
        )
        if is_match:
            is_body = is_match.group(1)
            step_texts = self._extract_implementation_step_texts(is_body)
            if not step_texts:
                errors.append(
                    "## Implementation Steps must include at least one actionable step"
                )
            else:
                if scale != "lite" and len(step_texts) < 2:
                    errors.append(
                        "## Implementation Steps must include at least 2 steps for full plans"
                    )
                shallow_steps = [
                    s for s in step_texts if len(re.findall(r"\b\w+\b", s)) < 3
                ]
                if shallow_steps:
                    errors.append(
                        "## Implementation Steps must include enough detail per step "
                        "(at least 3 words each)"
                    )
                if scale != "lite":
                    has_concrete_target = any(
                        re.search(
                            r"[\w\-]+(?:/[\w\-]+)+|[\w\-]+\.[\w]+|`[^`]+`|\w+\(",
                            s,
                        )
                        for s in step_texts
                    )
                    if not has_concrete_target:
                        errors.append(
                            "## Implementation Steps must reference at least one concrete code target "
                            "(file path, symbol, or callable)"
                        )

        # --- Minimum word count (full plans only) ---
        if scale != "lite":
            word_count = len(plan.split())
            min_words = self._config.min_plan_words
            if word_count < min_words:
                errors.append(f"Plan has {word_count} words, minimum is {min_words}")

        # --- [NEEDS CLARIFICATION] marker count ---
        clarification_markers = re.findall(
            r"\[NEEDS CLARIFICATION(?::\s*[^\]]+)?\]", plan, re.IGNORECASE
        )
        if len(clarification_markers) >= 4:
            errors.append(
                f"Plan has {len(clarification_markers)} [NEEDS CLARIFICATION] markers "
                f"(max 3) — issue needs more detail before implementation"
            )

        # --- Soft word-overlap check (warning only) ---
        title_words = self._significant_words(issue.title)
        plan_words = self._significant_words(plan)
        overlap = title_words & plan_words
        if not overlap and title_words:
            logger.warning(
                "Plan for issue #%d may not address the issue title %r "
                "(no significant word overlap)",
                issue.id,
                issue.title,
            )

        return errors

    def _extract_implementation_step_texts(self, section_body: str) -> list[str]:
        """Extract step text from Implementation Steps section body."""
        list_steps = re.findall(
            r"^\s*(?:\d+[\.\)]|[-*+]|\[[ xX]\])\s+(.+)$",
            section_body,
            re.MULTILINE,
        )
        heading_steps = re.findall(
            r"^\s*#{2,6}\s*(?:Step\s*\d+[:\.\-]?\s+(.+)|\d+[\.\)]\s+(.+))$",
            section_body,
            re.MULTILINE | re.IGNORECASE,
        )
        step_texts = [s.strip() for s in list_steps]
        step_texts.extend((s1 or s2).strip() for s1, s2 in heading_steps)
        return [s for s in step_texts if s]

    def _score_actionability(
        self, plan: str, *, scale: PlanScale = "full"
    ) -> tuple[int, str]:
        """Return actionability ``(score, rank)`` for *plan*."""
        score = 0
        is_match = re.search(
            r"## Implementation Steps\s*\n(.*?)(?=\n## |\Z)",
            plan,
            re.DOTALL | re.IGNORECASE,
        )
        step_texts = (
            self._extract_implementation_step_texts(is_match.group(1))
            if is_match
            else []
        )

        if step_texts:
            score += 20
        if scale != "lite" and len(step_texts) >= 2:
            score += 15
        elif scale == "lite" and step_texts:
            score += 10

        has_concrete_target = any(
            re.search(r"[\w\-]+(?:/[\w\-]+)+|[\w\-]+\.[\w]+|`[^`]+`|\w+\(", s)
            for s in step_texts
        )
        if has_concrete_target:
            score += 25

        if step_texts:
            shallow_steps = [
                s for s in step_texts if len(re.findall(r"\b\w+\b", s)) < 3
            ]
            if not shallow_steps:
                score += 10
            avg_words = sum(len(re.findall(r"\b\w+\b", s)) for s in step_texts) / len(
                step_texts
            )
            if avg_words >= 6:
                score += 10

        fd_match = re.search(
            r"## File Delta\s*\n(.*?)(?=\n## |\Z)", plan, re.DOTALL | re.IGNORECASE
        )
        if fd_match and re.search(
            r"^\s*(MODIFIED|ADDED|REMOVED):\s+\S", fd_match.group(1), re.MULTILINE
        ):
            score += 10

        ts_match = re.search(
            r"## Testing Strategy\s*\n(.*?)(?=\n## |\Z)",
            plan,
            re.DOTALL | re.IGNORECASE,
        )
        if ts_match and re.search(
            r"test[\w\-]*\.[\w]+|tests/|pytest|unit test|integration test",
            ts_match.group(1),
            re.IGNORECASE,
        ):
            score += 10

        score = max(0, min(100, score))
        if score >= 85:
            rank = "high"
        elif score >= 65:
            rank = "medium"
        else:
            rank = "low"
        return score, rank

    def _run_phase_minus_one_gates(self, plan: str) -> tuple[list[str], list[str]]:
        """Run Phase -1 gates on *plan*.

        Returns ``(blocking_errors, warnings)``.  Blocking errors prevent
        the plan from being accepted; warnings are logged but non-blocking.
        """
        blocking: list[str] = []
        warnings: list[str] = []

        # --- Simplicity gate: warn if > max_new_files_warning new files ---
        nf_match = re.search(
            r"## New Files\s*\n(.*?)(?=\n## |\Z)", plan, re.DOTALL | re.IGNORECASE
        )
        if nf_match:
            nf_body = nf_match.group(1)
            # Count path-like entries (lines starting with - or * followed by path-like text)
            new_file_entries = re.findall(
                r"[\w\-]+(?:/[\w\-]+)+\.[\w]+|[\w\-]+\.[\w]+", nf_body
            )
            threshold = self._config.max_new_files_warning
            if len(new_file_entries) > threshold:
                warnings.append(
                    f"Simplicity gate: plan creates {len(new_file_entries)} new files "
                    f"(threshold is {threshold})"
                )

        # --- Testing gate: reject if Testing Strategy is empty or deferred ---
        ts_match = re.search(
            r"## Testing Strategy\s*\n(.*?)(?=\n## |\Z)",
            plan,
            re.DOTALL | re.IGNORECASE,
        )
        if ts_match:
            ts_body = ts_match.group(1).strip()
            if not ts_body or ts_body.lower() in ("none", "n/a", "-"):
                blocking.append("Testing gate: Testing Strategy section is empty")
            elif self._TEST_LATER_RE.search(ts_body):
                blocking.append(
                    "Testing gate: Testing Strategy defers tests (e.g. 'later', 'TBD')"
                )
        else:
            # Section missing entirely — already caught by _validate_plan
            pass

        # --- Constitution gate: check against constitution.md ---
        constitution_path = self._config.repo_root / "constitution.md"
        if constitution_path.is_file():
            try:
                constitution_text = constitution_path.read_text()
                principles = [
                    line.strip().lstrip("-*").strip()
                    for line in constitution_text.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                plan_lower = plan.lower()
                for principle in principles:
                    if principle and principle.lower() in plan_lower:
                        blocking.append(
                            f"Constitution gate: plan may violate principle: "
                            f"{principle!r}"
                        )
            except OSError:
                logger.warning("Could not read constitution.md")

        # Log warnings
        for w in warnings:
            logger.warning(w)

        return blocking, warnings

    def _extract_plan(self, transcript: str) -> str:
        """Extract the plan from between PLAN_START/PLAN_END markers.

        Returns an empty string when the markers are absent — this prevents
        error output (e.g. budget-exceeded messages) from being treated as
        a valid plan.
        """
        pattern = r"PLAN_START\s*\n(.*?)\nPLAN_END"
        match = re.search(pattern, transcript, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def _extract_summary(self, transcript: str) -> str:
        """Extract the summary line from the planner transcript."""
        pattern = r"SUMMARY:\s*(.+)"
        match = re.search(pattern, transcript, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Fallback: last non-empty line
        lines = [ln.strip() for ln in transcript.splitlines() if ln.strip()]
        return lines[-1][:200] if lines else "No summary provided"

    @staticmethod
    def validate_already_satisfied_evidence(
        summary: str,
        issue_body: str = "",
        repo_root: Path | None = None,
    ) -> list[str]:
        """Validate that an already-satisfied summary contains required evidence.

        Returns a list of error strings.  An empty list means the evidence is valid.

        When *issue_body* and *repo_root* are provided, the validator also
        checks for new files mentioned in the issue (``ADDED:`` lines in a
        File Delta section, or items under a ``## New Files`` heading).
        If any referenced file does not exist on disk, the claim is rejected.
        """
        errors: list[str] = []
        if not summary or not summary.strip():
            errors.append("Evidence is empty")
            return errors

        # Check for required fields
        feature_match = re.search(r"Feature:\s*(.+)", summary)
        tests_match = re.search(r"Tests:\s*(.+)", summary)
        criteria_match = re.search(r"Criteria:\s*(.+)", summary)

        if not feature_match or not feature_match.group(1).strip():
            errors.append("Missing or empty 'Feature:' field")
        else:
            # Must contain file:line reference (e.g. src/foo.py:42),
            # but not a URL port like http://example.com:8080
            file_line = re.search(r"\S+:\d+", feature_match.group(1))
            if not file_line or "://" in file_line.group():
                errors.append("'Feature:' field must include a file:line reference")

        if not tests_match or not tests_match.group(1).strip():
            errors.append("Missing or empty 'Tests:' field")

        if not criteria_match or not criteria_match.group(1).strip():
            errors.append("Missing or empty 'Criteria:' field")

        # Reject when issue describes many acceptance criteria — complex
        # issues are almost never "already satisfied"
        if issue_body:
            criteria_count = len(re.findall(r"^- \[ \]", issue_body, re.MULTILINE))
            if criteria_count >= 5:
                errors.append(
                    f"Issue has {criteria_count} unchecked acceptance criteria "
                    f"— too complex to be already satisfied"
                )

        # Check for new files described in the issue that don't exist yet
        if issue_body and repo_root:
            missing = PlannerRunner._check_new_files_exist(issue_body, repo_root)
            if missing:
                files_list = ", ".join(missing[:5])
                errors.append(
                    f"Issue describes new files that do not exist: {files_list}"
                )

        return errors

    @staticmethod
    def _check_new_files_exist(issue_body: str, repo_root: Path) -> list[str]:
        """Extract new file paths from an issue body and check existence.

        Looks for ``ADDED: path/to/file`` lines in a File Delta section
        and bare file paths under ``## New Files`` headings.

        Returns a list of file paths that do not exist on disk.
        """
        new_files: list[str] = []

        # Match "ADDED: path/to/file.ext" lines
        for match in re.finditer(r"^ADDED:\s*(\S+\.\w+)", issue_body, re.MULTILINE):
            new_files.append(match.group(1))

        # Match file paths under "## New Files" section
        in_new_files = False
        for line in issue_body.splitlines():
            stripped = line.strip()
            if re.match(r"^##\s+New Files", stripped):
                in_new_files = True
                continue
            if in_new_files and re.match(r"^##\s+", stripped):
                break
            if in_new_files:
                # Extract backtick-delimited paths
                for m in re.findall(r"`([^`]+\.\w+)`", stripped):
                    new_files.append(m)
                # Extract bold paths
                for m in re.findall(r"\*\*([^*]+\.\w+)\*\*", stripped):
                    new_files.append(m)
                # Extract bare list-item paths: - path/to/file.ext
                bare = re.match(r"^[-*]\s+(\S+\.\w+)", stripped)
                if bare and not bare.group(1).startswith("`"):
                    new_files.append(bare.group(1))

        # Deduplicate and check existence
        seen: set[str] = set()
        missing: list[str] = []
        for fp in new_files:
            if fp in seen:
                continue
            seen.add(fp)
            if not (repo_root / fp).exists():
                missing.append(fp)

        return missing

    @staticmethod
    def _extract_already_satisfied(transcript: str) -> str:
        """Extract the already-satisfied explanation from the transcript.

        Returns the explanation text if the markers are present, empty string otherwise.
        """
        pattern = r"ALREADY_SATISFIED_START\s*\n(.*?)\nALREADY_SATISFIED_END"
        match = re.search(pattern, transcript, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _extract_new_issues(transcript: str) -> list[NewIssueSpec]:
        """Parse NEW_ISSUES_START/NEW_ISSUES_END markers into issue specs."""
        pattern = r"NEW_ISSUES_START\s*\n(.*?)\nNEW_ISSUES_END"
        match = re.search(pattern, transcript, re.DOTALL)
        if not match:
            return []

        block = match.group(1)
        issues: list[NewIssueSpec] = []
        current: dict[str, str] = {}

        last_key = ""
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("- title:"):
                if current.get("title"):
                    issues.append(
                        NewIssueSpec(
                            title=current["title"],
                            body=current.get("body", ""),
                            labels=[
                                lbl.strip()
                                for lbl in current.get("labels", "").split(",")
                                if lbl.strip()
                            ],
                        )
                    )
                current = {"title": stripped[len("- title:") :].strip()}
                last_key = "title"
            elif stripped.startswith("body:"):
                current["body"] = stripped[len("body:") :].strip()
                last_key = "body"
            elif stripped.startswith("labels:"):
                current["labels"] = stripped[len("labels:") :].strip()
                last_key = "labels"
            elif stripped and last_key == "body":
                # Continuation line for multi-line body
                current["body"] = current.get("body", "") + " " + stripped

        # Don't forget the last entry
        if current.get("title"):
            issues.append(
                NewIssueSpec(
                    title=current["title"],
                    body=current.get("body", ""),
                    labels=[
                        lbl.strip()
                        for lbl in current.get("labels", "").split(",")
                        if lbl.strip()
                    ],
                )
            )

        return issues

    def _build_retry_prompt(
        self,
        issue: Task,
        failed_plan: str,
        validation_errors: list[str],
        *,
        scale: PlanScale = "full",
    ) -> tuple[str, dict[str, object]]:
        """Build a retry prompt that includes the original issue, the failed plan, and validation feedback."""
        error_list = "\n".join(f"- {e}" for e in validation_errors[:12])
        sections_list = self._format_sections_list(scale)
        raw_body = issue.body or ""
        compact_body = self._truncate_text(
            raw_body, self._config.max_issue_body_chars, self._MAX_LINE_CHARS
        )
        compact_failed_plan = self._truncate_text(
            failed_plan, 4_000, self._MAX_LINE_CHARS
        )

        prompt = f"""You previously generated a plan for GitHub issue #{issue.id} but it failed validation.

## Issue: {issue.title}

{compact_body}

## Previous Plan (FAILED VALIDATION)

{compact_failed_plan}

## Validation Errors

{error_list}

## Instructions

Please fix the plan to address ALL of the validation errors above.
Your plan MUST include ALL of the following sections with these EXACT headers:

{sections_list}

If any requirement is ambiguous, mark it with `[NEEDS CLARIFICATION: <description>]`
rather than guessing. Plans with 4+ markers will be escalated for human review.

Output your corrected plan between these exact markers:

PLAN_START
<your corrected implementation plan here>
PLAN_END

Then provide a one-line summary:
SUMMARY: <brief one-line description of the plan>
"""
        before = (
            len(raw_body) + len(failed_plan) + sum(len(e) for e in validation_errors)
        )
        after = len(compact_body) + len(compact_failed_plan) + len(error_list)
        stats: dict[str, object] = {
            "context_chars_before": before,
            "context_chars_after": after,
            "pruned_chars_total": max(0, before - after),
            "section_chars": {
                "retry_issue_body_before": len(raw_body),
                "retry_issue_body_after": len(compact_body),
                "retry_failed_plan_before": len(failed_plan),
                "retry_failed_plan_after": len(compact_failed_plan),
                "retry_validation_errors_after": len(error_list),
            },
        }
        return prompt, stats

    async def _emit_status(
        self, issue_number: int, worker_id: int, status: PlannerStatus
    ) -> None:
        """Publish a planner status event."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.PLANNER_UPDATE,
                data={
                    "issue": issue_number,
                    "worker": worker_id,
                    "status": status.value,
                    "role": "planner",
                },
            )
        )

    def _save_plan(self, issue_number: int, plan: str, summary: str) -> None:
        """Write the extracted plan to .hydraflow/plans/ for the implementation worker."""
        plan_dir = self._config.plans_dir
        try:
            plan_dir.mkdir(parents=True, exist_ok=True)
            path = plan_dir / f"issue-{issue_number}.md"
            path.write_text(
                f"# Plan for Issue #{issue_number}\n\n{plan}\n\n---\n**Summary:** {summary}\n"
            )
            logger.info("Plan saved to %s", path, extra={"issue": issue_number})
        except OSError:
            logger.warning(
                "Could not save plan to %s",
                plan_dir,
                exc_info=True,
                extra={"issue": issue_number},
            )

    # ------------------------------------------------------------------
    # Epic gap review
    # ------------------------------------------------------------------

    async def run_gap_review(
        self,
        epic_number: int,
        child_plans: dict[int, str],
        child_titles: dict[int, str],
    ) -> str:
        """Run a gap/conflict review across epic children's plans.

        Returns the raw transcript for the caller to parse.
        """
        plans_section = "\n\n".join(
            f"### Issue #{num}: {child_titles.get(num, 'Untitled')}\n\n{plan}"
            for num, plan in child_plans.items()
        )
        prompt = (
            f"You are reviewing the implementation plans for all children of "
            f"Epic #{epic_number}. Your goal is to identify gaps, conflicts, "
            f"ordering issues, and duplication across these plans.\n\n"
            f"## Child Plans\n\n{plans_section}\n\n"
            f"## Instructions\n\n"
            f"Analyze the plans above and produce a structured review. "
            f"Wrap your entire review between GAP_REVIEW_START and "
            f"GAP_REVIEW_END markers.\n\n"
            f"Include these sections:\n"
            f"- **## Findings** — describe any gaps, conflicts, ordering "
            f"issues, or duplicated work across the plans\n"
            f"- **## Re-plan Required** — list the issue numbers (one per "
            f"line, as `#NNN`) that need re-planning to resolve the findings. "
            f"If all plans are coherent, write 'None'.\n"
            f"- **## Guidance** — specific instructions for re-planning the "
            f"flagged issues to resolve conflicts and fill gaps\n\n"
            f"GAP_REVIEW_START\n"
        )

        cmd = self._build_command()

        def _check_complete(accumulated: str) -> bool:
            return "GAP_REVIEW_END" in accumulated

        transcript = await self._execute(
            cmd,
            prompt,
            self._config.repo_root,
            {"epic": epic_number, "source": "planner-gap-review"},
            on_output=_check_complete,
        )
        return transcript
