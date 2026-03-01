"""Visual validation scope rules and skip policy.

Provides a deterministic trigger matrix that decides whether visual
validation is required or skipped for a given PR, based on:

1. Path-based trigger patterns (configurable globs).
2. Override labels (``hydraflow-visual-required`` / ``hydraflow-visual-skip``)
   which force-run or force-skip with a mandatory audit reason.
"""

from __future__ import annotations

import fnmatch
import logging
import re

from config import HydraFlowConfig
from models import VisualValidationDecision, VisualValidationPolicy

logger = logging.getLogger("hydraflow.visual_validation")

# Regex to extract changed file paths from a unified diff.
_DIFF_FILE_RE = re.compile(r"^\+\+\+\s+b/(.+)$", re.MULTILINE)


def _extract_changed_files(diff: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    return _DIFF_FILE_RE.findall(diff)


def _match_patterns(file_path: str, patterns: list[str]) -> list[str]:
    """Return patterns that match the given file path."""
    matched: list[str] = []
    for pattern in patterns:
        if fnmatch.fnmatch(file_path, pattern):
            matched.append(pattern)
    return matched


def _find_override_label(
    labels: list[str],
    required_label: str,
    skip_label: str,
) -> str | None:
    """Return the override label if present, or None.

    REQUIRED always takes precedence over SKIP regardless of list order.
    """
    label_set = set(labels)
    if required_label in label_set:
        return required_label
    if skip_label in label_set:
        return skip_label
    return None


def _extract_override_reason(comments: list[str], label: str) -> str:
    """Extract the audit reason for an override label from issue comments.

    Looks for a comment containing the label name followed by a reason,
    e.g. "hydraflow-visual-skip: No UI changes in this PR".
    """
    for comment in reversed(comments):
        for line in comment.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith(label.lower() + ":"):
                reason = stripped[len(label) + 1 :].strip()
                if reason:
                    return reason
    return ""


def compute_visual_validation(
    config: HydraFlowConfig,
    diff: str,
    issue_labels: list[str],
    issue_comments: list[str] | None = None,
) -> VisualValidationDecision:
    """Compute a deterministic visual validation decision.

    Priority order:
    1. Feature disabled → skip.
    2. Override label ``visual_required_label`` → required.
    3. Override label ``visual_skip_label`` → skipped (with audit reason).
    4. Path-based trigger patterns → required if any file matches.
    5. No matches → skipped.
    """
    comments = issue_comments or []

    # 1. Feature gate
    if not config.visual_validation_enabled:
        return VisualValidationDecision(
            policy=VisualValidationPolicy.SKIPPED,
            reason="Visual validation is disabled in config",
        )

    # 2–3. Check for override labels
    override = _find_override_label(
        issue_labels,
        config.visual_required_label,
        config.visual_skip_label,
    )

    if override is not None and override == config.visual_required_label:
        audit_reason = _extract_override_reason(comments, override)
        return VisualValidationDecision(
            policy=VisualValidationPolicy.REQUIRED,
            reason=audit_reason or "Override label applied",
            override_label=override,
        )

    if override is not None and override == config.visual_skip_label:
        audit_reason = _extract_override_reason(comments, override)
        if not audit_reason:
            logger.warning(
                "Visual skip override applied without audit reason; "
                "add a comment with '%s: <reason>'",
                config.visual_skip_label,
            )
        return VisualValidationDecision(
            policy=VisualValidationPolicy.SKIPPED,
            reason=audit_reason or "Override label applied (no reason given)",
            override_label=override,
        )

    # 4. Path-based trigger
    changed_files = _extract_changed_files(diff)
    all_matched: list[str] = []
    for fpath in changed_files:
        matched = _match_patterns(fpath, config.visual_validation_trigger_patterns)
        for m in matched:
            if m not in all_matched:
                all_matched.append(m)

    if all_matched:
        return VisualValidationDecision(
            policy=VisualValidationPolicy.REQUIRED,
            reason=f"Changed files match visual trigger patterns: {', '.join(all_matched)}",
            triggered_patterns=all_matched,
        )

    # 5. No triggers matched
    return VisualValidationDecision(
        policy=VisualValidationPolicy.SKIPPED,
        reason="No changed files match visual validation trigger patterns",
    )


def format_visual_validation_comment(decision: VisualValidationDecision) -> str:
    """Format a PR comment section for the visual validation decision."""
    if decision.policy == VisualValidationPolicy.REQUIRED:
        status = "**REQUIRED**"
    else:
        status = "**SKIPPED**"

    lines = [
        "## Visual Validation",
        "",
        f"Status: {status}",
        f"Reason: {decision.reason}",
    ]

    if decision.override_label:
        lines.append(f"Override: `{decision.override_label}`")

    if decision.triggered_patterns:
        lines.append(
            f"Triggered patterns: {', '.join(f'`{p}`' for p in decision.triggered_patterns)}"
        )

    return "\n".join(lines)
