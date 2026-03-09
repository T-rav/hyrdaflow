"""Background worker definitions and constants for the dashboard."""

from __future__ import annotations

# Each entry is (name, label, description).
BG_WORKER_DEFS: list[tuple[str, str, str]] = [
    (
        "triage",
        "Triage",
        "Classifies freshly discovered issues and routes them into the pipeline.",
    ),
    (
        "plan",
        "Plan",
        "Builds implementation plans for triaged issues that are ready to execute.",
    ),
    (
        "implement",
        "Implement",
        "Runs coding agents to implement planned issues and open pull requests.",
    ),
    (
        "review",
        "Review",
        "Reviews PRs, applies fixes, and merges approved work when checks pass.",
    ),
    (
        "memory_sync",
        "Memory Manager",
        "Ingests memory and transcript issues into durable learnings and proposals.",
    ),
    (
        "retrospective",
        "Retrospective",
        "Captures post-merge outcomes and identifies recurring delivery patterns.",
    ),
    (
        "metrics",
        "Metrics",
        "Refreshes operational metrics and dashboards from state and GitHub data.",
    ),
    (
        "review_insights",
        "Review Insights",
        "Aggregates recurring review feedback into improvement opportunities.",
    ),
    (
        "pipeline_poller",
        "Pipeline Poller",
        "Refreshes live pipeline snapshots for dashboard queue/status rendering.",
    ),
    (
        "pr_unsticker",
        "PR Unsticker",
        "Requeues stalled HITL PRs by validating requirements and reopening flow.",
    ),
    (
        "report_issue",
        "Report Issue",
        "Processes queued bug reports into GitHub issues via the configured agent.",
    ),
    (
        "adr_reviewer",
        "ADR Reviewer",
        "Reviews proposed ADRs via a 3-judge council and routes to accept, reject, or escalate.",
    ),
]

# Workers that have independent configurable intervals
INTERVAL_WORKERS: set[str] = {
    "memory_sync",
    "metrics",
    "pr_unsticker",
    "pipeline_poller",
    "report_issue",
}

# Pipeline loops share poll_interval (read-only display)
PIPELINE_WORKERS: set[str] = {"triage", "plan", "implement", "review"}

WORKER_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "plan": ("planner",),
    "implement": ("agent",),
    "review": ("reviewer", "merge_conflict", "fresh_rebuild"),
}

# Interval bounds per editable worker.
# memory_sync, metrics, pr_unsticker, adr_reviewer bounds must match config.py Field constraints.
# pipeline_poller has no config Field; 5s minimum matches the hardcoded default.
INTERVAL_BOUNDS: dict[str, tuple[int, int]] = {
    "memory_sync": (10, 14400),
    "metrics": (30, 14400),
    "pr_unsticker": (60, 86400),
    "pipeline_poller": (5, 14400),
    "adr_reviewer": (28800, 432000),
}
