"""Hardcoded HydraFlow lifecycle labels.

All pipeline labels are fixed — no env var overrides.
"""

from __future__ import annotations

from enum import StrEnum


class Label(StrEnum):
    """HydraFlow lifecycle label identifiers."""

    FIND = "hydraflow-find"
    PLAN = "hydraflow-plan"
    READY = "hydraflow-ready"
    REVIEW = "hydraflow-review"
    HITL = "hydraflow-hitl"
    HITL_ACTIVE = "hydraflow-hitl-active"
    HITL_AUTOFIX = "hydraflow-hitl-autofix"
    FIXED = "hydraflow-fixed"
    IMPROVE = "hydraflow-improve"
    MEMORY = "hydraflow-memory"
    TRANSCRIPT = "hydraflow-transcript"
    MANIFEST = "hydraflow-manifest"
    METRICS = "hydraflow-metrics"
    DUP = "hydraflow-dup"
    EPIC = "hydraflow-epic"
    EPIC_CHILD = "hydraflow-epic-child"
    VERIFY = "hydraflow-verify"
    VISUAL_REQUIRED = "hydraflow-visual-required"
    VISUAL_SKIP = "hydraflow-visual-skip"


# Ordered list of all pipeline-stage labels (for cleanup/swap operations)
ALL_PIPELINE_LABELS: list[str] = [
    Label.FIND,
    Label.PLAN,
    Label.READY,
    Label.REVIEW,
    Label.HITL,
    Label.HITL_ACTIVE,
    Label.HITL_AUTOFIX,
    Label.FIXED,
    Label.VERIFY,
    Label.IMPROVE,
    Label.TRANSCRIPT,
]

# Labels fetched by memory sync
MEMORY_SYNC_LABELS: list[str] = [
    Label.MEMORY,
    Label.IMPROVE,
    Label.TRANSCRIPT,
]

# Label metadata for ensure_labels: Label → (color, description)
LABEL_METADATA: dict[Label, tuple[str, str]] = {
    Label.FIND: ("e4e669", "New issue for HydraFlow to discover and triage"),
    Label.PLAN: ("c5def5", "Issue needs planning before implementation"),
    Label.READY: ("0e8a16", "Issue ready for implementation"),
    Label.REVIEW: ("fbca04", "Issue/PR under review"),
    Label.HITL: ("d93f0b", "Escalated to human-in-the-loop"),
    Label.HITL_ACTIVE: ("e99695", "Being processed by HITL correction agent"),
    Label.FIXED: ("0075ca", "PR merged — issue completed"),
    Label.IMPROVE: ("7057ff", "Review insight improvement proposal"),
    Label.MEMORY: ("1d76db", "Approved memory suggestion for sync"),
    Label.TRANSCRIPT: ("bfd4f2", "Transcript summary issue for memory ingestion"),
    Label.METRICS: ("006b75", "Metrics persistence issue"),
    Label.MANIFEST: ("1185fe", "Manifest persistence issue"),
    Label.DUP: ("cfd3d7", "Issue already satisfied — no changes needed"),
    Label.EPIC: ("5319e7", "Epic tracking issue with linked sub-issues"),
    Label.EPIC_CHILD: ("9b59b6", "Child issue linked to a HydraFlow epic"),
    Label.VERIFY: ("c2e0c6", "Post-merge verification pending"),
}
