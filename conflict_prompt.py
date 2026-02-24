"""Shared conflict resolution prompt builder for HydraFlow.

Used by both :mod:`pr_unsticker` and :mod:`review_phase` to produce
a concise prompt that points the conflict-resolution agent at the
relevant issue and PR URLs.  The agent has full filesystem access
(CLAUDE.md, .claude/ memory, git history) and can pull whatever
additional context it needs via ``gh`` CLI.
"""

from __future__ import annotations

from config import HydraFlowConfig
from manifest import load_project_manifest
from memory import load_memory_digest
from runner_constants import MEMORY_SUGGESTION_PROMPT

# Max characters of error output to include in conflict resolution prompts.
_ERROR_OUTPUT_MAX_CHARS: int = 3000


def build_conflict_prompt(
    issue_url: str,
    pr_url: str,
    last_error: str | None,
    attempt: int,
    *,
    config: HydraFlowConfig | None = None,
) -> str:
    """Build a conflict resolution prompt.

    Parameters
    ----------
    issue_url:
        Full GitHub URL for the issue (e.g. ``https://github.com/…/issues/42``).
    pr_url:
        Full GitHub URL for the pull request.
    last_error:
        Error output from the previous failed attempt, or *None*.
    attempt:
        Current attempt number (1-based).
    """
    sections: list[str] = []

    # --- Header ---
    sections.append(
        "There are merge conflicts on this branch.\n\n"
        f"- Issue: {issue_url}\n"
        f"- PR: {pr_url}\n\n"
        "Resolve all conflicts, then run `make quality` to verify "
        "everything passes. Do not push."
    )

    # --- Project manifest & memory digest ---
    if config is not None:
        manifest = load_project_manifest(config)
        if manifest:
            sections.append(f"## Project Context\n\n{manifest}")
        digest = load_memory_digest(config)
        if digest:
            sections.append(f"## Accumulated Learnings\n\n{digest}")

    # --- Previous attempt error ---
    if last_error and attempt > 1:
        max_chars = (
            config.error_output_max_chars
            if config is not None
            else _ERROR_OUTPUT_MAX_CHARS
        )
        sections.append(
            f"## Previous Attempt Failed\n\n"
            f"Attempt {attempt - 1} resolved the conflicts but "
            f"failed verification:\n"
            f"```\n{last_error[-max_chars:]}\n```\n"
            f"Please resolve the conflicts again, paying attention "
            f"to the above errors."
        )

    # --- Optional memory suggestion ---
    sections.append(
        MEMORY_SUGGESTION_PROMPT.format(context="conflict resolution").rstrip()
    )

    return "\n\n".join(sections)


def build_rebuild_prompt(
    issue_url: str,
    pr_url: str,
    issue_number: int,
    pr_diff: str,
    *,
    config: HydraFlowConfig | None = None,
) -> str:
    """Build a prompt for re-applying PR changes on a fresh branch from main.

    Parameters
    ----------
    issue_url:
        Full GitHub URL for the issue.
    pr_url:
        Full GitHub URL for the pull request.
    issue_number:
        Issue number for the commit message.
    pr_diff:
        The diff of the original PR (truncated to ``max_review_diff_chars``).
    config:
        Optional config for injecting project manifest and memory digest.
    """
    max_diff_chars = config.max_review_diff_chars if config is not None else 15_000
    truncated_diff = pr_diff[:max_diff_chars]

    sections: list[str] = []

    # --- Header ---
    sections.append(
        "You are re-applying changes from a pull request onto a fresh branch "
        "from main.\n\n"
        "The original PR had merge conflicts that could not be resolved "
        "automatically. You are now on a **clean branch from current main** "
        "— no conflicts.\n\n"
        f"- Issue: {issue_url}\n"
        f"- PR: {pr_url}"
    )

    # --- Project manifest & memory digest ---
    if config is not None:
        manifest = load_project_manifest(config)
        if manifest:
            sections.append(f"## Project Context\n\n{manifest}")
        digest = load_memory_digest(config)
        if digest:
            sections.append(f"## Accumulated Learnings\n\n{digest}")

    # --- Original PR diff ---
    sections.append(
        "## Original PR Diff\n\n"
        "Below is the diff of what the PR changed. Re-apply these logical "
        "changes to the current codebase. The code on main may have evolved, "
        "so adapt accordingly — do NOT blindly paste.\n\n"
        f"```diff\n{truncated_diff}\n```"
    )

    # --- Instructions ---
    sections.append(
        "## Instructions\n\n"
        "1. Study the diff to understand what the PR accomplished.\n"
        "2. Read the issue for full requirements context.\n"
        "3. Apply the same logical changes to the current codebase.\n"
        "4. Write or update tests as needed.\n"
        "5. Run `make quality` to verify everything passes.\n"
        f'6. Commit with message: "Rebuild: Fixes #{issue_number}"'
    )

    # --- Rules ---
    sections.append(
        "## Rules\n\n"
        "- Follow CLAUDE.md strictly.\n"
        "- Tests are mandatory.\n"
        "- Do NOT push or create PRs.\n"
        "- Ensure `make quality` passes."
    )

    # --- Optional memory suggestion ---
    sections.append(MEMORY_SUGGESTION_PROMPT.format(context="rebuild").rstrip())

    return "\n\n".join(sections)
