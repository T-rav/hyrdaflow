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
        "## Optional: Memory Suggestion\n\n"
        "If you discover a reusable pattern or insight during this "
        "conflict resolution that would help future agent runs, "
        "you may output ONE suggestion:\n\n"
        "MEMORY_SUGGESTION_START\n"
        "title: Short descriptive title\n"
        "type: knowledge | config | instruction | code\n"
        "learning: What was learned and why it matters\n"
        "context: How it was discovered (reference issue/PR numbers)\n"
        "MEMORY_SUGGESTION_END\n\n"
        "Types: knowledge (passive insight), config (suggests config change), "
        "instruction (new agent instruction), code (suggests code change).\n"
        "Actionable types (config, instruction, code) will be routed for human approval.\n"
        "Only suggest genuinely valuable learnings — not trivial observations."
    )

    return "\n\n".join(sections)
