"""HydraFlow configuration via Pydantic."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, field_validator, model_validator

import file_util

logger = logging.getLogger("hydraflow.config")

# Data-driven env-var override tables.
# Each tuple: (field_name, env_var_key, default_value)
_ENV_INT_OVERRIDES: list[tuple[str, str, int]] = [
    ("min_plan_words", "HYDRAFLOW_MIN_PLAN_WORDS", 200),
    (
        "max_pre_quality_review_attempts",
        "HYDRAFLOW_MAX_PRE_QUALITY_REVIEW_ATTEMPTS",
        3,
    ),
    ("max_diff_sanity_attempts", "HYDRAFLOW_MAX_DIFF_SANITY_ATTEMPTS", 1),
    ("max_test_adequacy_attempts", "HYDRAFLOW_MAX_TEST_ADEQUACY_ATTEMPTS", 1),
    ("max_review_fix_attempts", "HYDRAFLOW_MAX_REVIEW_FIX_ATTEMPTS", 2),
    ("min_review_findings", "HYDRAFLOW_MIN_REVIEW_FINDINGS", 3),
    ("max_issue_body_chars", "HYDRAFLOW_MAX_ISSUE_BODY_CHARS", 10_000),
    ("max_review_diff_chars", "HYDRAFLOW_MAX_REVIEW_DIFF_CHARS", 15_000),
    ("gh_max_retries", "HYDRAFLOW_GH_MAX_RETRIES", 3),
    ("gh_api_concurrency", "HYDRAFLOW_GH_API_CONCURRENCY", 5),
    ("max_issue_attempts", "HYDRAFLOW_MAX_ISSUE_ATTEMPTS", 3),
    ("memory_sync_interval", "HYDRAFLOW_MEMORY_SYNC_INTERVAL", 3600),
    ("metrics_sync_interval", "HYDRAFLOW_METRICS_SYNC_INTERVAL", 7200),
    ("max_merge_conflict_fix_attempts", "HYDRAFLOW_MAX_MERGE_CONFLICT_FIX_ATTEMPTS", 3),
    ("max_ci_timeout_fix_attempts", "HYDRAFLOW_MAX_CI_TIMEOUT_FIX_ATTEMPTS", 2),
    ("data_poll_interval", "HYDRAFLOW_DATA_POLL_INTERVAL", 300),
    ("max_sessions_per_repo", "HYDRAFLOW_MAX_SESSIONS_PER_REPO", 10),
    ("manifest_refresh_interval", "HYDRAFLOW_MANIFEST_REFRESH_INTERVAL", 3600),
    ("max_manifest_prompt_chars", "HYDRAFLOW_MAX_MANIFEST_PROMPT_CHARS", 2000),
    ("max_transcript_summary_chars", "HYDRAFLOW_MAX_TRANSCRIPT_SUMMARY_CHARS", 50_000),
    ("pr_unstick_interval", "HYDRAFLOW_PR_UNSTICK_INTERVAL", 3600),
    ("report_issue_interval", "HYDRAFLOW_REPORT_ISSUE_INTERVAL", 30),
    ("epic_monitor_interval", "HYDRAFLOW_EPIC_MONITOR_INTERVAL", 1800),
    ("worktree_gc_interval", "HYDRAFLOW_WORKTREE_GC_INTERVAL", 1800),
    ("collaborator_cache_ttl", "HYDRAFLOW_COLLABORATOR_CACHE_TTL", 600),
    ("artifact_retention_days", "HYDRAFLOW_ARTIFACT_RETENTION_DAYS", 30),
    ("artifact_max_size_mb", "HYDRAFLOW_ARTIFACT_MAX_SIZE_MB", 500),
    ("runs_gc_interval", "HYDRAFLOW_RUNS_GC_INTERVAL", 3600),
    ("adr_review_interval", "HYDRAFLOW_ADR_REVIEW_INTERVAL", 86400),
    ("adr_review_approval_threshold", "HYDRAFLOW_ADR_REVIEW_APPROVAL_THRESHOLD", 2),
    ("adr_review_max_rounds", "HYDRAFLOW_ADR_REVIEW_MAX_ROUNDS", 3),
    ("pr_unstick_batch_size", "HYDRAFLOW_PR_UNSTICK_BATCH_SIZE", 10),
    ("max_subskill_attempts", "HYDRAFLOW_MAX_SUBSKILL_ATTEMPTS", 0),
    ("max_debug_attempts", "HYDRAFLOW_MAX_DEBUG_ATTEMPTS", 1),
    ("harness_insight_window", "HYDRAFLOW_HARNESS_INSIGHT_WINDOW", 20),
    ("harness_pattern_threshold", "HYDRAFLOW_HARNESS_PATTERN_THRESHOLD", 3),
    ("max_runtime_log_chars", "HYDRAFLOW_MAX_RUNTIME_LOG_CHARS", 8_000),
    ("max_ci_log_chars", "HYDRAFLOW_MAX_CI_LOG_CHARS", 12_000),
    ("max_code_scanning_chars", "HYDRAFLOW_MAX_CODE_SCANNING_CHARS", 6_000),
    ("visual_max_retries", "HYDRAFLOW_VISUAL_MAX_RETRIES", 2),
    ("agent_timeout", "HYDRAFLOW_AGENT_TIMEOUT", 3600),
    ("transcript_summary_timeout", "HYDRAFLOW_TRANSCRIPT_SUMMARY_TIMEOUT", 120),
    ("memory_compaction_timeout", "HYDRAFLOW_MEMORY_COMPACTION_TIMEOUT", 60),
    ("quality_timeout", "HYDRAFLOW_QUALITY_TIMEOUT", 3600),
    ("git_command_timeout", "HYDRAFLOW_GIT_COMMAND_TIMEOUT", 30),
    ("summarizer_timeout", "HYDRAFLOW_SUMMARIZER_TIMEOUT", 120),
    ("error_output_max_chars", "HYDRAFLOW_ERROR_OUTPUT_MAX_CHARS", 3000),
    (
        "max_troubleshooting_prompt_chars",
        "HYDRAFLOW_MAX_TROUBLESHOOTING_PROMPT_CHARS",
        3000,
    ),
    ("visual_max_screens", "HYDRAFLOW_VISUAL_MAX_SCREENS", 20),
    (
        "visual_per_screen_budget_bytes",
        "HYDRAFLOW_VISUAL_PER_SCREEN_BUDGET_BYTES",
        5_000_000,
    ),
]

_ENV_STR_OVERRIDES: list[tuple[str, str, str]] = [
    ("test_command", "HYDRAFLOW_TEST_COMMAND", "make test"),
    ("docker_image", "HYDRAFLOW_DOCKER_IMAGE", "ghcr.io/t-rav/hydraflow-agent:latest"),
    ("docker_network", "HYDRAFLOW_DOCKER_NETWORK", ""),
    ("system_model", "HYDRAFLOW_SYSTEM_MODEL", ""),
    ("background_model", "HYDRAFLOW_BACKGROUND_MODEL", ""),
    ("memory_compaction_model", "HYDRAFLOW_MEMORY_COMPACTION_MODEL", "haiku"),
    ("transcript_summary_model", "HYDRAFLOW_TRANSCRIPT_SUMMARY_MODEL", "haiku"),
    ("triage_model", "HYDRAFLOW_TRIAGE_MODEL", "haiku"),
    ("subskill_model", "HYDRAFLOW_SUBSKILL_MODEL", "haiku"),
    ("debug_model", "HYDRAFLOW_DEBUG_MODEL", "opus"),
    ("report_issue_model", "HYDRAFLOW_REPORT_ISSUE_MODEL", "haiku"),
    ("adr_review_model", "HYDRAFLOW_ADR_REVIEW_MODEL", "sonnet"),
    ("changelog_file", "HYDRAFLOW_CHANGELOG_FILE", ""),
    ("release_tag_prefix", "HYDRAFLOW_RELEASE_TAG_PREFIX", "v"),
]

_ENV_FLOAT_OVERRIDES: list[tuple[str, str, float]] = [
    ("docker_cpu_limit", "HYDRAFLOW_DOCKER_CPU_LIMIT", 2.0),
    ("docker_spawn_delay", "HYDRAFLOW_DOCKER_SPAWN_DELAY", 2.0),
    ("visual_retry_delay", "HYDRAFLOW_VISUAL_RETRY_DELAY", 2.0),
]

# Float overrides with tight [0, 1] bounds — handled separately from the
# parametrized table because the generic test adds ``default + 1.0`` which
# exceeds their upper bound.
_ENV_FLOAT_RATIO_OVERRIDES: list[tuple[str, str, float]] = [
    ("visual_warn_threshold", "HYDRAFLOW_VISUAL_WARN_THRESHOLD", 0.05),
    ("visual_fail_threshold", "HYDRAFLOW_VISUAL_FAIL_THRESHOLD", 0.15),
]

_ENV_BOOL_OVERRIDES: list[tuple[str, str, bool]] = [
    ("docker_read_only_root", "HYDRAFLOW_DOCKER_READ_ONLY_ROOT", True),
    ("docker_no_new_privileges", "HYDRAFLOW_DOCKER_NO_NEW_PRIVILEGES", True),
    (
        "transcript_summarization_enabled",
        "HYDRAFLOW_TRANSCRIPT_SUMMARIZATION_ENABLED",
        True,
    ),
    (
        "transcript_summary_as_issue",
        "HYDRAFLOW_TRANSCRIPT_SUMMARY_AS_ISSUE",
        False,
    ),
    ("memory_auto_approve", "HYDRAFLOW_MEMORY_AUTO_APPROVE", False),
    ("debug_escalation_enabled", "HYDRAFLOW_DEBUG_ESCALATION_ENABLED", True),
    ("inject_runtime_logs", "HYDRAFLOW_INJECT_RUNTIME_LOGS", False),
    ("unstick_auto_merge", "HYDRAFLOW_UNSTICK_AUTO_MERGE", True),
    ("unstick_all_causes", "HYDRAFLOW_UNSTICK_ALL_CAUSES", True),
    (
        "enable_fresh_branch_rebuild",
        "HYDRAFLOW_ENABLE_FRESH_BRANCH_REBUILD",
        True,
    ),
    ("auto_crate", "HYDRAFLOW_AUTO_CRATE", False),
    ("collaborator_check_enabled", "HYDRAFLOW_COLLABORATOR_CHECK_ENABLED", True),
    ("code_scanning_enabled", "HYDRAFLOW_CODE_SCANNING_ENABLED", False),
    ("visual_gate_enabled", "HYDRAFLOW_VISUAL_GATE_ENABLED", False),
    ("visual_gate_bypass", "HYDRAFLOW_VISUAL_GATE_BYPASS", False),
    ("visual_validation_enabled", "HYDRAFLOW_VISUAL_VALIDATION_ENABLED", True),
    ("release_on_epic_close", "HYDRAFLOW_RELEASE_ON_EPIC_CLOSE", False),
    ("adr_review_enabled", "HYDRAFLOW_ADR_REVIEW_ENABLED", False),
    (
        "screenshot_redaction_enabled",
        "HYDRAFLOW_SCREENSHOT_REDACTION_ENABLED",
        True,
    ),
    ("screenshot_gist_public", "HYDRAFLOW_SCREENSHOT_GIST_PUBLIC", False),
]

# Literal-typed env-var overrides.
# Each tuple: (field_name, env_var_key)
# The default and allowed values are read dynamically from model_fields.
_ENV_LITERAL_OVERRIDES: list[tuple[str, str]] = [
    ("execution_mode", "HYDRAFLOW_EXECUTION_MODE"),
    ("docker_network_mode", "HYDRAFLOW_DOCKER_NETWORK_MODE"),
    ("system_tool", "HYDRAFLOW_SYSTEM_TOOL"),
    ("background_tool", "HYDRAFLOW_BACKGROUND_TOOL"),
    ("implementation_tool", "HYDRAFLOW_IMPLEMENTATION_TOOL"),
    ("review_tool", "HYDRAFLOW_REVIEW_TOOL"),
    ("planner_tool", "HYDRAFLOW_PLANNER_TOOL"),
    ("triage_tool", "HYDRAFLOW_TRIAGE_TOOL"),
    ("transcript_summary_tool", "HYDRAFLOW_TRANSCRIPT_SUMMARY_TOOL"),
    ("memory_compaction_tool", "HYDRAFLOW_MEMORY_COMPACTION_TOOL"),
    ("ac_tool", "HYDRAFLOW_AC_TOOL"),
    ("verification_judge_tool", "HYDRAFLOW_VERIFICATION_JUDGE_TOOL"),
    ("subskill_tool", "HYDRAFLOW_SUBSKILL_TOOL"),
    ("debug_tool", "HYDRAFLOW_DEBUG_TOOL"),
    ("report_issue_tool", "HYDRAFLOW_REPORT_ISSUE_TOOL"),
    ("epic_merge_strategy", "HYDRAFLOW_EPIC_MERGE_STRATEGY"),
    ("release_version_source", "HYDRAFLOW_RELEASE_VERSION_SOURCE"),
]

# Deprecated env var aliases (HYDRA_ → HYDRAFLOW_).
# During the deprecation period, old names are promoted to canonical names
# with a warning at startup.
_DEPRECATED_ENV_ALIASES: dict[str, str] = {
    "HYDRA_DOCKER_IMAGE": "HYDRAFLOW_DOCKER_IMAGE",
    "HYDRA_DOCKER_NETWORK": "HYDRAFLOW_DOCKER_NETWORK",
    "HYDRA_DOCKER_SPAWN_DELAY": "HYDRAFLOW_DOCKER_SPAWN_DELAY",
}
# Reverse lookup: canonical key → deprecated key (built once at import time).
_DEPRECATED_ENV_REVERSE: dict[str, str] = {
    v: k for k, v in _DEPRECATED_ENV_ALIASES.items()
}

# Label env var overrides — maps env key → (field_name, default_value)
_ENV_LABEL_MAP: dict[str, tuple[str, list[str]]] = {
    "HYDRAFLOW_LABEL_FIND": ("find_label", ["hydraflow-find"]),
    "HYDRAFLOW_LABEL_PLAN": ("planner_label", ["hydraflow-plan"]),
    "HYDRAFLOW_LABEL_READY": ("ready_label", ["hydraflow-ready"]),
    "HYDRAFLOW_LABEL_REVIEW": ("review_label", ["hydraflow-review"]),
    "HYDRAFLOW_LABEL_HITL": ("hitl_label", ["hydraflow-hitl"]),
    "HYDRAFLOW_LABEL_HITL_ACTIVE": ("hitl_active_label", ["hydraflow-hitl-active"]),
    "HYDRAFLOW_LABEL_HITL_AUTOFIX": ("hitl_autofix_label", ["hydraflow-hitl-autofix"]),
    "HYDRAFLOW_LABEL_FIXED": ("fixed_label", ["hydraflow-fixed"]),
    "HYDRAFLOW_LABEL_IMPROVE": ("improve_label", ["hydraflow-improve"]),
    "HYDRAFLOW_LABEL_MEMORY": ("memory_label", ["hydraflow-memory"]),
    "HYDRAFLOW_LABEL_TRANSCRIPT": ("transcript_label", ["hydraflow-transcript"]),
    "HYDRAFLOW_LABEL_MANIFEST": ("manifest_label", ["hydraflow-manifest"]),
    "HYDRAFLOW_LABEL_METRICS": ("metrics_label", ["hydraflow-metrics"]),
    "HYDRAFLOW_LABEL_DUP": ("dup_label", ["hydraflow-dup"]),
    "HYDRAFLOW_LABEL_EPIC": ("epic_label", ["hydraflow-epic"]),
    "HYDRAFLOW_LABEL_EPIC_CHILD": ("epic_child_label", ["hydraflow-epic-child"]),
}


class HydraFlowConfig(BaseModel):
    """Configuration for the HydraFlow orchestrator."""

    # Issue selection
    ready_label: list[str] = Field(
        default=["hydraflow-ready"],
        description="GitHub issue labels to filter by (OR logic)",
    )
    batch_size: int = Field(default=15, ge=1, le=50, description="Issues per batch")
    repo: str = Field(
        default="",
        description="GitHub repo (owner/name); auto-detected from git remote if empty",
    )

    # Worker configuration — managed via config JSON file and dashboard UI,
    # not environment variables. All defaults are 1.
    max_workers: int = Field(default=1, ge=1, le=10, description="Concurrent agents")
    max_planners: int = Field(
        default=1, ge=1, le=10, description="Concurrent planning agents"
    )
    max_reviewers: int = Field(
        default=1, ge=1, le=10, description="Concurrent review agents"
    )
    max_triagers: int = Field(
        default=1, ge=1, le=10, description="Concurrent triage agents"
    )
    max_hitl_workers: int = Field(
        default=1, ge=1, le=5, description="Concurrent HITL correction agents"
    )
    system_tool: Literal["inherit", "claude", "codex", "pi"] = Field(
        default="inherit",
        description="Optional global default tool for system agents; 'inherit' keeps per-agent defaults",
    )
    system_model: str = Field(
        default="",
        description="Optional global default model for system agents; empty keeps per-agent defaults",
    )
    background_tool: Literal["inherit", "claude", "codex", "pi"] = Field(
        default="inherit",
        description="Optional global default tool for background workers; 'inherit' keeps per-worker defaults",
    )
    background_model: str = Field(
        default="",
        description="Optional global default model for background workers; empty keeps per-worker defaults",
    )
    implementation_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for implementation agents",
    )
    model: str = Field(default="opus", description="Model for implementation agents")

    # Review configuration
    review_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for review agents",
    )
    review_model: str = Field(default="sonnet", description="Model for review agents")

    # CI check configuration
    ci_check_timeout: int = Field(
        default=600, ge=30, le=3600, description="Seconds to wait for CI checks"
    )
    ci_poll_interval: int = Field(
        default=30, ge=5, le=120, description="Seconds between CI status polls"
    )
    max_ci_fix_attempts: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Max CI fix-and-retry cycles (0 = skip CI wait)",
    )
    max_quality_fix_attempts: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Max quality fix-and-retry cycles before marking agent as failed",
    )
    max_pre_quality_review_attempts: int = Field(
        default=3,
        ge=0,
        le=5,
        description="Max pre-quality review/correction passes before quality verification",
    )
    max_diff_sanity_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Max diff sanity check passes (0 = disabled)",
    )
    max_test_adequacy_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Max test adequacy check passes (0 = disabled)",
    )
    max_review_fix_attempts: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Max review fix-and-retry cycles before HITL escalation",
    )
    min_review_findings: int = Field(
        default=3,
        ge=0,
        le=20,
        description="Minimum review findings threshold for adversarial review",
    )
    max_merge_conflict_fix_attempts: int = Field(
        default=3,
        ge=0,
        le=5,
        description="Max merge conflict resolution retry cycles",
    )
    max_ci_timeout_fix_attempts: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Max fix attempts for CI timeout (hanging test) failures",
    )
    max_issue_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max total implementation attempts per issue before HITL escalation",
    )
    gh_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Max retry attempts for gh CLI calls",
    )
    gh_api_concurrency: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Max concurrent gh/git subprocess calls (prevents API rate limiting)",
    )

    # Task source
    task_source_type: Literal["github"] = Field(
        default="github",
        description="Task source backend. Only 'github' supported today.",
    )

    # Label lifecycle
    review_label: list[str] = Field(
        default=["hydraflow-review"],
        description="Labels for issues/PRs under review (OR logic)",
    )
    hitl_label: list[str] = Field(
        default=["hydraflow-hitl"],
        description="Labels for issues escalated to human-in-the-loop (OR logic)",
    )
    hitl_active_label: list[str] = Field(
        default=["hydraflow-hitl-active"],
        description="Labels for HITL items being actively processed (OR logic)",
    )
    hitl_autofix_label: list[str] = Field(
        default=["hydraflow-hitl-autofix"],
        description="Labels for HITL items undergoing automatic fix attempt (OR logic)",
    )
    fixed_label: list[str] = Field(
        default=["hydraflow-fixed"],
        description="Labels applied after PR is merged (OR logic)",
    )
    improve_label: list[str] = Field(
        default=["hydraflow-improve"],
        description="Labels for improvement/memory suggestion issues (OR logic)",
    )
    memory_label: list[str] = Field(
        default=["hydraflow-memory"],
        description="Labels for accepted agent learnings (OR logic)",
    )
    transcript_label: list[str] = Field(
        default=["hydraflow-transcript"],
        description="Labels for transcript-summary issues queued for memory sync (OR logic)",
    )
    manifest_label: list[str] = Field(
        default=["hydraflow-manifest"],
        description="Labels for manifest snapshot persistence issues (OR logic)",
    )
    metrics_label: list[str] = Field(
        default=["hydraflow-metrics"],
        description="Labels for the metrics persistence issue (OR logic)",
    )
    dup_label: list[str] = Field(
        default=["hydraflow-dup"],
        description="Labels applied when issue is already satisfied (no changes needed)",
    )
    epic_label: list[str] = Field(
        default=["hydraflow-epic"],
        description="Labels for epic tracking issues with linked sub-issues (OR logic)",
    )
    epic_child_label: list[str] = Field(
        default=["hydraflow-epic-child"],
        description="Labels for child issues linked to epics (OR logic)",
    )
    epic_group_planning: bool = Field(
        default=True,
        description="Group epic children for cohort planning with gap review",
    )
    epic_gap_review_max_iterations: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Max gap review + re-plan iterations (0 disables gap review)",
    )
    epic_auto_decompose: bool = Field(
        default=False,
        description="Auto-decompose large issues into epics during triage",
    )
    epic_decompose_complexity_threshold: int = Field(
        default=8,
        ge=1,
        le=10,
        description="Minimum triage complexity score to trigger decomposition",
    )
    epic_monitor_interval: int = Field(
        default=1800,
        description="Epic monitor loop interval in seconds (default 30 min)",
    )
    worktree_gc_interval: int = Field(
        default=1800,
        ge=300,
        le=86400,
        description="Worktree GC loop interval in seconds (default 30 min)",
    )
    collaborator_check_enabled: bool = Field(
        default=True,
        description="When True, skip issues from non-collaborators at fetch time",
    )
    collaborator_cache_ttl: int = Field(
        default=600,
        ge=60,
        le=7200,
        description="Collaborator list cache TTL in seconds (default 10 min)",
    )

    # Artifact retention
    artifact_retention_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Days to retain run artifacts before cleanup (default 30)",
    )
    artifact_max_size_mb: int = Field(
        default=500,
        ge=10,
        le=10_000,
        description="Max total artifact storage in MB before oldest runs are pruned (default 500)",
    )
    runs_gc_interval: int = Field(
        default=3600,
        ge=300,
        le=86400,
        description="Runs GC loop interval in seconds (default 1 hour)",
    )

    epic_stale_days: int = Field(
        default=7,
        ge=1,
        description="Days without activity before an epic is flagged as stale",
    )
    epic_merge_strategy: Literal[
        "independent", "bundled", "bundled_hitl", "ordered"
    ] = Field(
        default="independent",
        description="How to coordinate merging of epic sub-issue PRs",
    )
    auto_crate: bool = Field(
        default=False,
        description="When True, auto-package uncrated labeled issues into crates. When False, human must assign via UI.",
    )

    # Release configuration
    release_on_epic_close: bool = Field(
        default=False,
        description="Create a GitHub Release when an epic completes",
    )
    release_version_source: Literal["epic_title", "milestone", "manual"] = Field(
        default="epic_title",
        description="How to determine the release version string",
    )
    release_tag_prefix: str = Field(
        default="v",
        description="Prefix for git tags (e.g. 'v' produces 'v1.2.0')",
    )

    # Discovery / planner configuration
    find_label: list[str] = Field(
        default=["hydraflow-find"],
        description="Labels for new issues to discover and triage into planning (OR logic)",
    )
    planner_label: list[str] = Field(
        default=["hydraflow-plan"],
        description="Labels for issues needing plans (OR logic)",
    )
    planner_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for planning agents",
    )
    planner_model: str = Field(default="opus", description="Model for planning agents")
    triage_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for triage agents",
    )
    triage_model: str = Field(
        default="haiku", description="Model for triage evaluation (fast/cheap)"
    )
    min_plan_words: int = Field(
        default=200,
        ge=50,
        le=2000,
        description="Minimum word count for a valid plan",
    )
    max_new_files_warning: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Warn if plan creates more than this many new files",
    )
    lite_plan_labels: list[str] = Field(
        default=["bug", "typo", "docs"],
        description="Issue labels that trigger a lite plan (fewer required sections)",
    )
    # Metric thresholds for improvement proposals
    quality_fix_rate_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Alert if quality fix rate exceeds this (0.0-1.0)",
    )
    approval_rate_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Alert if first-pass approval rate drops below this (0.0-1.0)",
    )
    hitl_rate_threshold: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Alert if HITL escalation rate exceeds this (0.0-1.0)",
    )

    # Review insight aggregation
    review_insight_window: int = Field(
        default=10,
        ge=3,
        le=50,
        description="Number of recent reviews to analyze for patterns",
    )
    review_pattern_threshold: int = Field(
        default=3,
        ge=2,
        le=10,
        description="Minimum category frequency to trigger improvement proposal",
    )

    # Harness insight aggregation
    harness_insight_window: int = Field(
        default=20,
        ge=3,
        le=100,
        description="Number of recent failures to analyze for harness patterns",
    )
    harness_pattern_threshold: int = Field(
        default=3,
        ge=2,
        le=20,
        description="Minimum failure frequency to trigger harness improvement proposal",
    )

    # Agent prompt configuration
    subskill_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for low-tier subskill/tool-chain passes",
    )
    subskill_model: str = Field(
        default="haiku",
        description="Model used for low-tier subskill/tool-chain passes",
    )
    max_subskill_attempts: int = Field(
        default=0,
        ge=0,
        le=5,
        description="Max low-tier subskill precheck attempts per stage",
    )
    debug_escalation_enabled: bool = Field(
        default=True,
        description="Enable automatic escalation to debug model when low-tier prechecks signal risk/ambiguity",
    )
    debug_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for debug escalation passes",
    )
    debug_model: str = Field(
        default="opus",
        description="Model used for debug escalation passes",
    )
    max_debug_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Max debug escalation attempts per stage",
    )
    subskill_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum low-tier confidence before skipping debug escalation",
    )
    # Timeouts
    quality_timeout: int = Field(
        default=3600,
        ge=60,
        le=7200,
        description="Timeout in seconds for 'make quality' verification",
    )
    git_command_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout in seconds for simple git commands (rev-list, rev-parse, status)",
    )
    summarizer_timeout: int = Field(
        default=120,
        ge=30,
        le=600,
        description="Timeout in seconds for transcript summarizer subprocess",
    )
    error_output_max_chars: int = Field(
        default=3000,
        ge=500,
        le=20_000,
        description="Max characters of error output to include in prompts and messages",
    )

    test_command: str = Field(
        default="make test",
        description="Quick test command for agent prompts",
    )
    max_issue_body_chars: int = Field(
        default=10_000,
        ge=1_000,
        le=100_000,
        description="Max characters for issue body in agent prompts before truncation",
    )
    max_review_diff_chars: int = Field(
        default=15_000,
        ge=1_000,
        le=200_000,
        description="Max characters for PR diff in reviewer prompts before truncation",
    )
    max_memory_chars: int = Field(
        default=4000,
        ge=500,
        le=50_000,
        description="Max characters for memory digest before compaction",
    )
    max_memory_prompt_chars: int = Field(
        default=4000,
        ge=500,
        le=50_000,
        description="Max characters for memory digest injected into agent prompts",
    )
    max_troubleshooting_prompt_chars: int = Field(
        default=3000,
        ge=500,
        le=10_000,
        description="Max characters for learned troubleshooting patterns in CI timeout prompts",
    )
    memory_compaction_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for memory digest compaction",
    )
    memory_compaction_model: str = Field(
        default="haiku",
        description="Cheap model for summarising memory digest when over size limit",
    )

    # Memory auto-approve
    memory_auto_approve: bool = Field(
        default=False,
        description="When True, memory suggestions skip HITL and go directly to the sync queue",
    )

    memory_prune_stale_items: bool = Field(
        default=True,
        description="Remove local memory item files whose source issue is no longer active",
    )

    # Observability context injection
    inject_runtime_logs: bool = Field(
        default=False,
        description="Inject runtime application logs into agent context (opt-in)",
    )
    max_runtime_log_chars: int = Field(
        default=8_000,
        ge=1_000,
        le=100_000,
        description="Max characters for runtime log injection",
    )
    max_ci_log_chars: int = Field(
        default=12_000,
        ge=1_000,
        le=100_000,
        description="Max characters for CI failure log injection",
    )
    code_scanning_enabled: bool = Field(
        default=False,
        description="Fetch GitHub code scanning alerts and inject into review context",
    )
    max_code_scanning_chars: int = Field(
        default=6_000,
        ge=1_000,
        le=100_000,
        description="Max characters for code scanning alert injection",
    )

    # Visual gate
    visual_gate_enabled: bool = Field(
        default=False,
        description="Require visual validation gate before merge finalization",
    )
    visual_gate_bypass: bool = Field(
        default=False,
        description="Emergency bypass for visual gate (audit-logged)",
    )

    # Visual validation scope and flake mitigation
    visual_validation_enabled: bool = Field(
        default=True,
        description="Enable visual validation scope checks and runtime validation during review",
    )
    visual_diff_threshold: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Per-screen pixel diff ratio that triggers FAIL",
    )
    visual_max_screens: int = Field(
        default=20,
        ge=1,
        description="Maximum number of screens to compare",
    )
    visual_per_screen_budget_bytes: int = Field(
        default=5_000_000,
        ge=1,
        description="Maximum artifact size in bytes per screen",
    )
    visual_validation_trigger_patterns: list[str] = Field(
        default_factory=lambda: [
            "src/ui/**",
            "ui/**",
            "frontend/**",
            "web/**",
            "*.css",
            "*.scss",
            "*.tsx",
            "*.jsx",
            "*.html",
        ],
        description="Glob patterns for files that trigger visual validation requirement",
    )
    visual_required_label: str = Field(
        default="hydraflow-visual-required",
        description="Override label to force visual validation regardless of file paths",
    )
    visual_skip_label: str = Field(
        default="hydraflow-visual-skip",
        description="Override label to skip visual validation with an audit reason",
    )
    visual_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Max retries for transient visual validation failures",
    )
    visual_retry_delay: float = Field(
        default=2.0,
        ge=0.0,
        le=30.0,
        description="Seconds to wait between visual validation retries",
    )
    visual_warn_threshold: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Diff ratio above which a screen gets a WARN verdict",
    )
    visual_fail_threshold: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Diff ratio above which a screen gets a FAIL verdict",
    )

    # Screenshot security
    screenshot_redaction_enabled: bool = Field(
        default=True,
        description=(
            "Run backend secret-pattern scan before uploading dashboard screenshots. "
            "When True, payloads matching known secret patterns (GitHub tokens, AWS keys, "
            "etc.) are rejected and the screenshot is stripped from the report. "
            "Frontend DOM redaction of [data-sensitive] elements is always active "
            "and is unaffected by this setting."
        ),
    )
    screenshot_gist_public: bool = Field(
        default=False,
        description="Upload screenshot gists as public (True) or secret/unlisted (False)",
    )

    # Manifest detection
    manifest_refresh_interval: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Seconds between project manifest refresh scans (default: 1 hour)",
    )
    max_manifest_prompt_chars: int = Field(
        default=2000,
        ge=200,
        le=10_000,
        description="Max characters for project manifest injected into agent prompts",
    )

    # Transcript summarization
    transcript_summarization_enabled: bool = Field(
        default=True,
        description="Run automatic transcript summarization after each agent phase",
    )
    transcript_summary_model: str = Field(
        default="haiku",
        description="Cheap model for summarising agent transcripts into structured learnings",
    )
    transcript_summary_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for transcript summarization",
    )
    max_transcript_summary_chars: int = Field(
        default=50_000,
        ge=5_000,
        le=500_000,
        description="Max transcript characters to send for summarization (truncated from end)",
    )
    transcript_summary_as_issue: bool = Field(
        default=False,
        description="Also create standalone GitHub issues for transcript summaries (default: off)",
    )

    # Report issue worker
    report_issue_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for report-issue worker",
    )
    report_issue_model: str = Field(
        default="haiku",
        description="Model for report-issue worker (formatting task, cheap)",
    )
    report_issue_interval: int = Field(
        default=30,
        ge=10,
        le=3600,
        description="Seconds between report-issue worker polls",
    )

    # Git configuration
    main_branch: str = Field(default="main", description="Base branch name")
    git_user_name: str = Field(
        default="",
        description="Git user.name for worktree commits; falls back to global git config if empty",
    )
    git_user_email: str = Field(
        default="",
        description="Git user.email for worktree commits; falls back to global git config if empty",
    )

    # Paths (auto-detected)
    repo_root: Path = Field(default=Path("."), description="Repository root directory")
    worktree_base: Path = Field(
        default=Path("."), description="Base directory for worktrees"
    )
    data_root: Path = Field(
        default=Path("."),
        description="Directory for persistent HydraFlow data (.hydraflow)",
    )
    state_file: Path = Field(default=Path("."), description="Path to state JSON file")

    # Event persistence
    event_log_path: Path = Field(
        default=Path("."),
        description="Path to event log JSONL file",
    )
    event_log_max_size_mb: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max event log file size in MB before rotation",
    )
    event_log_retention_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="Days of event history to retain during rotation",
    )

    # Config file persistence
    config_file: Path | None = Field(
        default=None,
        description="Path to JSON config file for persisting runtime changes",
    )

    # Changelog
    changelog_file: str = Field(
        default="",
        description="Path to CHANGELOG.md file for epic completion changelog generation; "
        "empty string disables file output",
    )

    # Dashboard
    dashboard_port: int = Field(
        default=5555, ge=1024, le=65535, description="Dashboard web UI port"
    )
    dashboard_enabled: bool = Field(
        default=True, description="Enable the live web dashboard"
    )

    # Polling
    poll_interval: int = Field(
        default=30, ge=5, le=300, description="Seconds between work-queue polls"
    )
    memory_sync_interval: int = Field(
        default=3600,
        ge=10,
        le=14400,
        description="Seconds between memory sync polls (default: 1 hour)",
    )
    metrics_sync_interval: int = Field(
        default=7200,
        ge=30,
        le=14400,
        description="Seconds between metrics snapshot syncs (default: 2 hours)",
    )
    data_poll_interval: int = Field(
        default=300,
        ge=10,
        le=600,
        description="Seconds between centralized GitHub issue store polls",
    )
    pr_unstick_interval: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Seconds between PR unsticker polls",
    )
    pr_unstick_batch_size: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max PRs to unstick per cycle (fetch limit and parallel workers)",
    )
    unstick_auto_merge: bool = Field(
        default=True,
        description="Auto-merge PRs after fixing and CI passes",
    )
    unstick_all_causes: bool = Field(
        default=True,
        description="Process all HITL causes (not just merge conflicts)",
    )
    enable_fresh_branch_rebuild: bool = Field(
        default=True,
        description="After merge conflict resolution exhausts all attempts, "
        "try rebuilding on a fresh branch from main before escalating to HITL",
    )

    # ADR Council Review
    adr_review_interval: int = Field(
        default=86400,
        ge=28800,
        le=432000,
        description="Seconds between ADR review cycles",
    )
    adr_review_approval_threshold: int = Field(
        default=2,
        ge=1,
        le=3,
        description="Number of APPROVE votes needed for acceptance",
    )
    adr_review_max_rounds: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum deliberation rounds before forcing a decision",
    )
    adr_review_enabled: bool = Field(
        default=False,
        description="Enable the ADR council review background loop",
    )
    adr_review_model: str = Field(
        default="sonnet",
        description="Model for the ADR council review orchestrator",
    )

    # Session retention
    max_sessions_per_repo: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max session logs to retain per repo",
    )

    # Acceptance criteria generation
    ac_model: str = Field(
        default="sonnet",
        description="Model for acceptance criteria generation (post-merge)",
    )
    ac_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for acceptance criteria generation",
    )
    verification_judge_tool: Literal["claude", "codex", "pi"] = Field(
        default="claude",
        description="CLI backend for verification judge agents",
    )

    # UI directories (fallback for worktree node_modules symlinking)
    ui_dirs: list[str] = Field(
        default_factory=lambda: ["ui"],
        description="UI directories containing package.json; auto-detected at runtime if present",
    )

    # Retrospective
    retrospective_window: int = Field(
        default=10,
        ge=3,
        le=100,
        description="Number of recent retrospective entries to scan for patterns",
    )

    # Credit pause
    credit_pause_buffer_minutes: int = Field(
        default=1,
        ge=0,
        le=30,
        description="Extra minutes to wait after reported credit reset time",
    )

    # Process timeouts
    agent_timeout: int = Field(
        default=3600,
        ge=60,
        le=14400,
        description="Default timeout in seconds for agent process runs",
    )
    transcript_summary_timeout: int = Field(
        default=120,
        ge=30,
        le=600,
        description="Timeout in seconds for transcript summarization model calls",
    )
    memory_compaction_timeout: int = Field(
        default=60,
        ge=30,
        le=600,
        description="Timeout in seconds for memory compaction model calls",
    )

    # Execution mode
    dry_run: bool = Field(
        default=False, description="Log actions without executing them"
    )
    execution_mode: Literal["host", "docker"] = Field(
        default="host",
        description="Run agents on host or in Docker containers",
    )

    # Docker isolation
    docker_image: str = Field(
        default="ghcr.io/t-rav/hydraflow-agent:latest",
        description="Docker image for agent containers",
    )
    docker_cpu_limit: float = Field(
        default=2.0,
        ge=0.5,
        le=16.0,
        description="CPU cores per container",
    )
    docker_memory_limit: str = Field(
        default="4g",
        description="Memory limit per container",
    )
    docker_network_mode: Literal["bridge", "none", "host"] = Field(
        default="bridge",
        description="Docker network mode",
    )
    docker_spawn_delay: float = Field(
        default=2.0,
        ge=0.0,
        le=30.0,
        description="Seconds between concurrent container starts",
    )
    docker_read_only_root: bool = Field(
        default=True,
        description="Read-only root filesystem in containers",
    )
    docker_no_new_privileges: bool = Field(
        default=True,
        description="Prevent privilege escalation in containers",
    )
    docker_pids_limit: int = Field(
        default=256,
        ge=16,
        le=4096,
        description="Max PIDs per container (prevents fork bombs)",
    )
    docker_tmp_size: str = Field(
        default="1g",
        description="Tmpfs size for /tmp in containers",
    )

    docker_network: str = Field(
        default="",
        description="Docker network name (empty = default bridge)",
    )
    docker_extra_mounts: list[str] = Field(
        default=[],
        description="Additional volume mounts as host:container:mode strings",
    )

    # Baseline policy
    baseline_snapshot_patterns: list[str] = Field(
        default=["**/__snapshots__/**", "**/*.snap.png", "**/*.baseline.png"],
        description="Glob patterns matching visual baseline files in the repo",
    )
    baseline_approval_required: bool = Field(
        default=True,
        description="Whether baseline updates require explicit approval",
    )
    baseline_approvers: list[str] = Field(
        default=[],
        description="GitHub usernames allowed to approve baseline updates (empty = repo collaborators)",
    )
    baseline_max_audit_records: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Maximum baseline audit records to retain per issue",
    )

    # GitHub authentication
    gh_token: str = Field(
        default="",
        description="GitHub token for gh CLI auth (overrides shell GH_TOKEN)",
    )

    @field_validator(
        "ready_label",
        "review_label",
        "hitl_label",
        "hitl_active_label",
        "hitl_autofix_label",
        "fixed_label",
        "improve_label",
        "memory_label",
        "transcript_label",
        "manifest_label",
        "metrics_label",
        "dup_label",
        "epic_label",
        "epic_child_label",
        "find_label",
        "planner_label",
    )
    @classmethod
    def labels_must_not_be_empty(cls, v: list[str]) -> list[str]:
        """Reject empty label lists — downstream code indexes with [0]."""
        if not v:
            raise ValueError("Label list must contain at least one label")
        return v

    @field_validator("docker_memory_limit", "docker_tmp_size")
    @classmethod
    def validate_docker_size_notation(cls, v: str) -> str:
        """Validate Docker size notation (digits followed by b/k/m/g)."""
        if not re.fullmatch(r"\d+[bkmg]", v, re.IGNORECASE):
            msg = f"Invalid Docker size notation '{v}'; expected digits followed by b/k/m/g (e.g., '4g', '512m')"
            raise ValueError(msg)
        return v

    @field_validator("visual_fail_threshold")
    @classmethod
    def visual_fail_above_warn(cls, v: float, info: Any) -> float:
        """Ensure visual_fail_threshold > visual_warn_threshold."""
        warn = info.data.get("visual_warn_threshold", 0.05)
        if v <= warn:
            msg = (
                f"visual_fail_threshold ({v}) must be greater than "
                f"visual_warn_threshold ({warn})"
            )
            raise ValueError(msg)
        return v

    model_config = {"arbitrary_types_allowed": True}

    @property
    def all_pipeline_labels(self) -> list[str]:
        """Return a flat list of every pipeline-stage label (for cleanup)."""
        result: list[str] = []
        for labels in (
            self.find_label,
            self.planner_label,
            self.ready_label,
            self.review_label,
            self.hitl_label,
            self.hitl_active_label,
            self.hitl_autofix_label,
            self.fixed_label,
            self.improve_label,
            self.transcript_label,
        ):
            result.extend(labels)
        return result

    @property
    def memory_sync_labels(self) -> list[str]:
        """Return labels fetched by memory sync (memory + transcript summaries)."""
        result: list[str] = []
        for label in [*self.memory_label, *self.transcript_label]:
            if label not in result:
                result.append(label)
        return result

    @property
    def log_dir(self) -> Path:
        """Return the directory for transcript / log files."""
        return self.data_root / "logs"

    @property
    def plans_dir(self) -> Path:
        """Return the directory for saved plan files."""
        return self.data_root / "plans"

    @property
    def memory_dir(self) -> Path:
        """Return the directory for memory / review-insight files."""
        return self.data_root / "memory"

    @property
    def visual_reports_dir(self) -> Path:
        """Return the directory for visual validation reports."""
        return self.data_root / "visual-reports"

    def data_path(self, *parts: str | os.PathLike[str]) -> Path:
        """Return an absolute path inside the HydraFlow data_root."""
        return self.data_root.joinpath(*parts)

    def format_path_for_display(self, path: Path) -> str:
        """Return a human-friendly path relative to repo or data root when possible."""
        for base in (self.repo_root, self.data_root):
            with contextlib.suppress(ValueError):
                return str(path.relative_to(base))
        return str(path)

    @property
    def repo_slug(self) -> str:
        """Normalized repo identifier for path namespacing (e.g. ``org-repo``)."""
        return self.repo.replace("/", "-") if self.repo else self.repo_root.name

    @property
    def repo_data_root(self) -> Path:
        """Return the repo-scoped data directory (``data_root / repo_slug``)."""
        return self.data_root / self.repo_slug

    def branch_for_issue(self, issue_number: int) -> str:
        """Return the canonical branch name for a given issue number."""
        return f"agent/issue-{issue_number}"

    def worktree_path_for_issue(self, issue_number: int) -> Path:
        """Return the repo-scoped worktree directory path for a given issue number."""
        return self.worktree_base / self.repo_slug / f"issue-{issue_number}"

    @model_validator(mode="after")
    def resolve_defaults(self) -> HydraFlowConfig:
        """Resolve paths, repo slug, and apply env var overrides.

        Resolution order (two-phase path resolution):
          1. ``_resolve_base_paths`` — repo_root, worktree_base, data_root
          2. ``_resolve_repo_and_identity`` — repo slug, gh_token, git identity
          3. ``_resolve_repo_scoped_paths`` — state_file, event_log_path, config_file

        Base paths are resolved first because repo detection depends on repo_root,
        and repo-scoped paths depend on both data_root and the repo slug.

        Environment variables (checked when no explicit CLI value is given):
            HYDRAFLOW_GITHUB_REPO       → repo
            HYDRAFLOW_GITHUB_ASSIGNEE   → (used by slash commands only)
            HYDRAFLOW_GH_TOKEN          → gh_token
            HYDRAFLOW_GIT_USER_NAME     → git_user_name
            HYDRAFLOW_GIT_USER_EMAIL    → git_user_email
            HYDRAFLOW_MIN_PLAN_WORDS    → min_plan_words
            HYDRAFLOW_LABEL_FIND        → find_label   (discovery stage)
            HYDRAFLOW_LABEL_PLAN        → planner_label
            HYDRAFLOW_LABEL_READY       → ready_label  (implement stage)
            HYDRAFLOW_LABEL_REVIEW      → review_label
            HYDRAFLOW_LABEL_HITL        → hitl_label
            HYDRAFLOW_LABEL_HITL_ACTIVE  → hitl_active_label
            HYDRAFLOW_LABEL_HITL_AUTOFIX → hitl_autofix_label
            HYDRAFLOW_LABEL_FIXED       → fixed_label
            HYDRAFLOW_LABEL_IMPROVE     → improve_label
            HYDRAFLOW_LABEL_MEMORY      → memory_label
            HYDRAFLOW_LABEL_DUP         → dup_label
            HYDRAFLOW_LABEL_EPIC        → epic_label
            HYDRAFLOW_LABEL_EPIC_CHILD  → epic_child_label
        """
        _resolve_base_paths(self)
        _resolve_repo_and_identity(self)
        _resolve_repo_scoped_paths(self)
        _apply_env_overrides(self)
        _apply_profile_overrides(self)
        _harmonize_tool_model_defaults(self)
        _validate_docker(self)
        return self


def _apply_profile_overrides(config: HydraFlowConfig) -> None:
    """Apply grouped tool/model defaults for background and system workloads."""

    explicit_fields = set(config.__pydantic_fields_set__)

    def _apply_if_default(field: str, value: str) -> None:
        if field in explicit_fields:
            return
        if getattr(config, field) == HydraFlowConfig.model_fields[field].default:
            object.__setattr__(config, field, value)

    if config.system_tool != "inherit":
        for field in (
            "implementation_tool",
            "review_tool",
            "planner_tool",
            "ac_tool",
            "verification_judge_tool",
            "subskill_tool",
            "debug_tool",
        ):
            _apply_if_default(field, config.system_tool)

    if config.system_model.strip():
        for field in (
            "model",
            "review_model",
            "planner_model",
            "ac_model",
            "subskill_model",
            "debug_model",
        ):
            _apply_if_default(field, config.system_model)

    if config.background_tool != "inherit":
        for field in (
            "triage_tool",
            "transcript_summary_tool",
            "memory_compaction_tool",
            "report_issue_tool",
        ):
            _apply_if_default(field, config.background_tool)

    if config.background_model.strip():
        for field in (
            "triage_model",
            "transcript_summary_model",
            "memory_compaction_model",
            "report_issue_model",
        ):
            _apply_if_default(field, config.background_model)


def _harmonize_tool_model_defaults(config: HydraFlowConfig) -> None:
    """Align tool/model defaults when model remains implicit.

    Prevent Codex runs from inheriting the Claude-oriented implementation model
    default (`opus`) when no explicit implementation model was provided.
    """
    if config.implementation_tool == "codex" and config.model == "opus":
        object.__setattr__(config, "model", "gpt-5-codex")


def _resolve_base_paths(config: HydraFlowConfig) -> None:
    """Resolve repo_root, worktree_base, and data_root.

    These base paths have no dependency on the repo slug and must be resolved
    first so that ``_resolve_repo_and_identity`` can use ``repo_root`` for
    git-remote detection and ``_resolve_repo_scoped_paths`` can use ``data_root``.
    """
    if config.repo_root == Path("."):
        object.__setattr__(config, "repo_root", _find_repo_root())
    else:
        object.__setattr__(config, "repo_root", config.repo_root.expanduser().resolve())
    if config.worktree_base == Path("."):
        default_worktrees = Path("~/.hydraflow/worktrees").expanduser().resolve()
        object.__setattr__(config, "worktree_base", default_worktrees)
    else:
        object.__setattr__(
            config, "worktree_base", config.worktree_base.expanduser().resolve()
        )
    env_home = os.environ.get("HYDRAFLOW_HOME", "").strip()
    if env_home:
        data_root = Path(env_home).expanduser().resolve()
    elif config.data_root == Path("."):
        data_root = (config.repo_root / ".hydraflow").resolve()
    else:
        data_root = config.data_root.expanduser().resolve()
    object.__setattr__(config, "data_root", data_root)


_REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def _validate_repo_format(repo: str) -> None:
    """Raise ``ValueError`` if *repo* is not a valid ``owner/repo`` slug."""
    if not repo:
        return  # empty repo is handled elsewhere
    if ".." in repo:
        msg = f"Invalid repo format {repo!r} — path traversal not allowed"
        raise ValueError(msg)
    if not _REPO_SLUG_RE.fullmatch(repo):
        msg = f"Invalid repo format {repo!r} — expected 'owner/repo'"
        raise ValueError(msg)


def _resolve_repo_and_identity(config: HydraFlowConfig) -> None:
    """Resolve repo slug, GitHub token, and git identity from env vars."""
    # Repo slug: env var → git remote → empty
    if not config.repo:
        config.repo = os.environ.get("HYDRAFLOW_GITHUB_REPO", "") or _detect_repo_slug(
            config.repo_root
        )

    if config.repo:
        _validate_repo_format(config.repo)

    # GitHub token:
    # explicit value → HYDRAFLOW_GH_TOKEN env var → GH_TOKEN/GITHUB_TOKEN env vars
    # → .env fallback
    if not config.gh_token:
        env_token = (
            os.environ.get("HYDRAFLOW_GH_TOKEN", "")
            or os.environ.get("GH_TOKEN", "")
            or os.environ.get("GITHUB_TOKEN", "")
            or _dotenv_lookup(
                config.repo_root, "HYDRAFLOW_GH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"
            )
        )
        if env_token:
            object.__setattr__(config, "gh_token", env_token)

    # Git identity:
    # explicit value → HYDRAFLOW_GIT_USER_NAME/EMAIL env vars
    # → GIT_* author/committer env vars → .env fallback
    if not config.git_user_name:
        env_name = (
            os.environ.get("HYDRAFLOW_GIT_USER_NAME", "")
            or os.environ.get("GIT_AUTHOR_NAME", "")
            or os.environ.get("GIT_COMMITTER_NAME", "")
            or _dotenv_lookup(
                config.repo_root,
                "HYDRAFLOW_GIT_USER_NAME",
                "GIT_AUTHOR_NAME",
                "GIT_COMMITTER_NAME",
            )
        )
        if env_name:
            object.__setattr__(config, "git_user_name", env_name)
    if not config.git_user_email:
        env_email = (
            os.environ.get("HYDRAFLOW_GIT_USER_EMAIL", "")
            or os.environ.get("GIT_AUTHOR_EMAIL", "")
            or os.environ.get("GIT_COMMITTER_EMAIL", "")
            or _dotenv_lookup(
                config.repo_root,
                "HYDRAFLOW_GIT_USER_EMAIL",
                "GIT_AUTHOR_EMAIL",
                "GIT_COMMITTER_EMAIL",
            )
        )
        if env_email:
            object.__setattr__(config, "git_user_email", env_email)


def _resolve_repo_scoped_paths(config: HydraFlowConfig) -> None:
    """Resolve state_file, event_log_path, and config_file under repo-scoped dirs.

    Called after both ``_resolve_base_paths`` (which provides ``data_root``) and
    ``_resolve_repo_and_identity`` (which provides the repo slug).  Default paths
    are placed directly under ``data_root / <slug>`` — no intermediate flat
    defaults are created first.

    Explicitly-provided paths are left untouched (just expanded/resolved).

    Legacy flat files are migrated on first run: if the repo-scoped file does not
    exist but the legacy flat file does, a copy is made so no data is lost.
    """
    data_root = config.data_root
    slug = config.repo_slug
    explicit = config.__pydantic_fields_set__

    # Target directory: repo-scoped when a slug is available, flat otherwise.
    # NOTE: repo_slug never returns "" for a non-root repo_root, so the `else
    # data_root` branch below and the `if slug` migration guards are only
    # reached when repo_root is the filesystem root ("/").
    repo_dir = data_root / slug if slug else data_root

    # --- state_file ---
    if "state_file" not in explicit:
        target = repo_dir / "state.json"
        if slug:
            flat = data_root / "state.json"
            if not target.exists() and flat.exists():
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(flat, target)
                except OSError as exc:
                    logger.warning("Failed to migrate %s → %s: %s", flat, target, exc)
        object.__setattr__(config, "state_file", target)
    else:
        object.__setattr__(
            config, "state_file", config.state_file.expanduser().resolve()
        )

    # --- event_log_path ---
    if "event_log_path" not in explicit:
        target = repo_dir / "events.jsonl"
        if slug:
            flat = data_root / "events.jsonl"
            if not target.exists() and flat.exists():
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(flat, target)
                except OSError as exc:
                    logger.warning("Failed to migrate %s → %s: %s", flat, target, exc)
        object.__setattr__(config, "event_log_path", target)
    else:
        object.__setattr__(
            config, "event_log_path", config.event_log_path.expanduser().resolve()
        )

    # --- config_file ---
    # config_file defaults to None (persistence disabled); only resolve if explicit.
    if "config_file" in explicit and config.config_file is not None:
        object.__setattr__(
            config, "config_file", config.config_file.expanduser().resolve()
        )

    # --- sessions.jsonl (derived from state_file parent, migrate if needed) ---
    # Only migrate when state_file is at its default location; skip when the user
    # has pointed state_file at a custom path to avoid copying into arbitrary dirs.
    if "state_file" not in explicit:
        flat_sessions = data_root / "sessions.jsonl"
        scoped_sessions = config.state_file.parent / "sessions.jsonl"
        if (
            scoped_sessions != flat_sessions
            and not scoped_sessions.exists()
            and flat_sessions.exists()
        ):
            try:
                scoped_sessions.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(flat_sessions, scoped_sessions)
            except OSError as exc:
                logger.warning(
                    "Failed to migrate %s → %s: %s", flat_sessions, scoped_sessions, exc
                )


def _dotenv_lookup(repo_root: Path, *keys: str) -> str:
    """Read first matching non-empty value from ``repo_root/.env``."""
    env_file = repo_root / ".env"
    if not env_file.exists():
        return ""
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return ""
    parsed = _parse_dotenv_text(text)
    for key in keys:
        val = parsed.get(key, "").strip()
        if val:
            return val
    return ""


def _parse_dotenv_text(text: str) -> dict[str, str]:
    """Parse minimal .env key/value content for local config fallbacks."""
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            # For unquoted values, treat inline " # comment" suffixes as comments.
            # Keep literal '#' when no whitespace precedes it.
            value = re.sub(r"\s+#.*$", "", value).rstrip()
        result[key] = value
    return result


def _get_env(key: str) -> str | None:
    """Return the env var value for *key*, falling back to any deprecated alias."""
    val = os.environ.get(key)
    if val is not None:
        return val
    old_key = _DEPRECATED_ENV_REVERSE.get(key)
    if old_key is not None:
        val = os.environ.get(old_key)
        if val is not None:
            logger.warning("Deprecated env var %s; use %s instead", old_key, key)
            return val
    return None


def _apply_env_overrides(config: HydraFlowConfig) -> None:
    """Apply all data-driven and special-case env var overrides."""

    # Data-driven env var overrides (int fields)
    for field, env_key, default in _ENV_INT_OVERRIDES:
        if getattr(config, field) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                with contextlib.suppress(ValueError):
                    new_val = int(env_val)
                    for constraint in HydraFlowConfig.model_fields[field].metadata:
                        ge = getattr(constraint, "ge", None)
                        le = getattr(constraint, "le", None)
                        if ge is not None and new_val < ge:
                            raise ValueError(
                                f"{env_key}={new_val} is below minimum {ge}"
                            )
                        if le is not None and new_val > le:
                            raise ValueError(
                                f"{env_key}={new_val} is above maximum {le}"
                            )
                    object.__setattr__(config, field, new_val)

    # Data-driven env var overrides (str fields)
    for field, env_key, default in _ENV_STR_OVERRIDES:
        if getattr(config, field) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                object.__setattr__(config, field, env_val)

    # Data-driven env var overrides (float fields)
    for field, env_key, default in _ENV_FLOAT_OVERRIDES:
        if getattr(config, field) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                with contextlib.suppress(ValueError):
                    new_val = float(env_val)
                    for constraint in HydraFlowConfig.model_fields[field].metadata:
                        ge = getattr(constraint, "ge", None)
                        le = getattr(constraint, "le", None)
                        if ge is not None and new_val < ge:
                            raise ValueError(
                                f"{env_key}={new_val} is below minimum {ge}"
                            )
                        if le is not None and new_val > le:
                            raise ValueError(
                                f"{env_key}={new_val} is above maximum {le}"
                            )
                    object.__setattr__(config, field, new_val)

    # Ratio float overrides ([0, 1] bounds) — parse failures are silently ignored
    # but out-of-bounds values emit a warning so operators know their config was rejected.
    for field, env_key, default in _ENV_FLOAT_RATIO_OVERRIDES:
        if getattr(config, field) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                try:
                    new_val = float(env_val)
                except ValueError:
                    continue
                in_bounds = True
                for constraint in HydraFlowConfig.model_fields[field].metadata:
                    ge = getattr(constraint, "ge", None)
                    le = getattr(constraint, "le", None)
                    if ge is not None and new_val < ge:
                        logger.warning(
                            "%s=%s is below minimum %s; ignoring env override",
                            env_key,
                            new_val,
                            ge,
                        )
                        in_bounds = False
                        break
                    if le is not None and new_val > le:
                        logger.warning(
                            "%s=%s is above maximum %s; ignoring env override",
                            env_key,
                            new_val,
                            le,
                        )
                        in_bounds = False
                        break
                if in_bounds:
                    object.__setattr__(config, field, new_val)

    # Cross-field validation: visual_fail_threshold must remain > visual_warn_threshold
    # after env overrides (the Pydantic field_validator only fires at model construction).
    # Strategy: revert only visual_fail_threshold first; if that still violates the
    # invariant (e.g. warn was also overridden to a value >= the fail default), revert
    # visual_warn_threshold too so we always land on a valid pair.
    if config.visual_fail_threshold <= config.visual_warn_threshold:
        _fail_default: float = HydraFlowConfig.model_fields[
            "visual_fail_threshold"
        ].default
        _warn_default: float = HydraFlowConfig.model_fields[
            "visual_warn_threshold"
        ].default
        logger.warning(
            "visual_fail_threshold (%.4f) is not greater than visual_warn_threshold (%.4f) "
            "after env overrides; reverting visual_fail_threshold to default (%.4f)",
            config.visual_fail_threshold,
            config.visual_warn_threshold,
            _fail_default,
        )
        object.__setattr__(config, "visual_fail_threshold", _fail_default)
        if config.visual_fail_threshold <= config.visual_warn_threshold:
            logger.warning(
                "visual_warn_threshold (%.4f) still >= fail default (%.4f); "
                "reverting visual_warn_threshold to default (%.4f) as well",
                config.visual_warn_threshold,
                _fail_default,
                _warn_default,
            )
            object.__setattr__(config, "visual_warn_threshold", _warn_default)

    # Data-driven env var overrides (bool fields)
    for field, env_key, default in _ENV_BOOL_OVERRIDES:
        if getattr(config, field) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                object.__setattr__(
                    config,
                    field,
                    env_val.lower() not in ("0", "false", "no"),
                )

    # Data-driven env var overrides (Literal-typed fields)
    for field, env_key in _ENV_LITERAL_OVERRIDES:
        field_info = HydraFlowConfig.model_fields[field]
        if getattr(config, field) == field_info.default:
            env_val = _get_env(env_key)
            if env_val is not None:
                allowed = get_args(field_info.annotation)
                if env_val in allowed:
                    object.__setattr__(config, field, env_val)
                else:
                    logger.warning(
                        "Invalid %s=%r; expected one of %s",
                        env_key,
                        env_val,
                        allowed,
                    )

    # Visual validation float thresholds (bounded 0.0–1.0, special-case).
    for field, env_key, default in (
        ("visual_diff_threshold", "HYDRAFLOW_VISUAL_DIFF_THRESHOLD", 0.01),
    ):
        if getattr(config, field) == default:
            env_val = _get_env(env_key)
            if env_val is not None:
                with contextlib.suppress(ValueError):
                    new_val = float(env_val)
                    if 0.0 <= new_val <= 1.0:
                        object.__setattr__(config, field, new_val)

    # Backward-compat bridge: promote legacy HYDRAFLOW_DOCKER_ENABLED /
    # HYDRA_DOCKER_ENABLED to execution_mode="docker" when the canonical
    # HYDRAFLOW_EXECUTION_MODE env var was not explicitly set.
    if config.execution_mode == "host":
        _docker_enabled_raw = os.environ.get(
            "HYDRAFLOW_DOCKER_ENABLED"
        ) or os.environ.get("HYDRA_DOCKER_ENABLED")
        if _docker_enabled_raw is not None:
            _execution_mode_explicit = os.environ.get("HYDRAFLOW_EXECUTION_MODE")
            if _execution_mode_explicit is None and _docker_enabled_raw.lower() not in (
                "0",
                "false",
                "no",
            ):
                object.__setattr__(config, "execution_mode", "docker")
                logger.warning(
                    "HYDRAFLOW_DOCKER_ENABLED / HYDRA_DOCKER_ENABLED is deprecated; "
                    "use HYDRAFLOW_EXECUTION_MODE=docker instead."
                )

    # Lite plan labels (comma-separated list, special-case)
    env_lite_labels = os.environ.get("HYDRAFLOW_LITE_PLAN_LABELS")
    if env_lite_labels is not None and config.lite_plan_labels == [
        "bug",
        "typo",
        "docs",
    ]:
        parsed = [lbl.strip() for lbl in env_lite_labels.split(",") if lbl.strip()]
        if parsed:
            object.__setattr__(config, "lite_plan_labels", parsed)

    # Docker resource limit overrides (validated fields handled manually
    # because str/int overrides need format/bounds validation that
    # the data-driven tables don't provide)
    if config.docker_memory_limit == "4g":  # still at default
        env_mem = os.environ.get("HYDRAFLOW_DOCKER_MEMORY_LIMIT")
        if env_mem is not None:
            if not re.fullmatch(r"\d+[bkmg]", env_mem, re.IGNORECASE):
                msg = f"Invalid HYDRAFLOW_DOCKER_MEMORY_LIMIT '{env_mem}'; expected digits followed by b/k/m/g (e.g., '4g', '512m')"
                raise ValueError(msg)
            object.__setattr__(config, "docker_memory_limit", env_mem)

    if config.docker_tmp_size == "1g":  # still at default
        env_tmp = os.environ.get("HYDRAFLOW_DOCKER_TMP_SIZE")
        if env_tmp is not None:
            if not re.fullmatch(r"\d+[bkmg]", env_tmp, re.IGNORECASE):
                msg = f"Invalid HYDRAFLOW_DOCKER_TMP_SIZE '{env_tmp}'; expected digits followed by b/k/m/g (e.g., '1g', '512m')"
                raise ValueError(msg)
            object.__setattr__(config, "docker_tmp_size", env_tmp)

    if config.docker_pids_limit == 256:  # still at default
        env_pids = os.environ.get("HYDRAFLOW_DOCKER_PIDS_LIMIT")
        if env_pids is not None:
            try:
                pids_val = int(env_pids)
            except ValueError as exc:
                logger.warning(
                    "HYDRAFLOW_DOCKER_PIDS_LIMIT value '%s' is not an integer; keeping default %d (%s)",
                    env_pids,
                    config.docker_pids_limit,
                    exc,
                    exc_info=True,
                )
            else:
                if not (16 <= pids_val <= 4096):
                    msg = f"HYDRAFLOW_DOCKER_PIDS_LIMIT must be between 16 and 4096, got {pids_val}"
                    raise ValueError(msg)
                object.__setattr__(config, "docker_pids_limit", pids_val)

    # Label env var overrides (only apply when still at the default)
    for env_key, (field_name, default_val) in _ENV_LABEL_MAP.items():
        current = getattr(config, field_name)
        env_val = os.environ.get(env_key)
        if env_val is not None and current == default_val:
            # Split on comma, ignoring empty parts; skip override if result is empty
            labels = (
                [part.strip() for part in env_val.split(",") if part.strip()]
                if env_val
                else []
            )
            if labels:
                object.__setattr__(config, field_name, labels)


def _validate_docker(config: HydraFlowConfig) -> None:
    """Validate Docker availability when execution_mode is 'docker'."""
    if config.execution_mode != "docker":
        return

    if not config.docker_image.strip():
        # No image configured → fall back to host execution; no Docker validation needed.
        return

    if shutil.which("docker") is None:
        msg = (
            "execution_mode is 'docker' but the 'docker' command was not found on PATH"
        )
        raise ValueError(msg)

    if not config.gh_token:
        logger.warning(
            "Docker mode without GH token configured; container actions may use the local gh auth context "
            "(set HYDRAFLOW_GH_TOKEN/GH_TOKEN/GITHUB_TOKEN, e.g. in .env)."
        )
    if bool(config.git_user_name) ^ bool(config.git_user_email):
        logger.warning(
            "Docker mode git identity is incomplete (name=%r email=%r); commits may fall back to host identity.",
            config.git_user_name,
            config.git_user_email,
        )
    elif not config.git_user_name and not config.git_user_email:
        logger.warning(
            "Docker mode git identity not configured; commits may use fallback host/global git identity "
            "(set HYDRAFLOW_GIT_USER_NAME and HYDRAFLOW_GIT_USER_EMAIL, e.g. in .env)."
        )


def _find_repo_root() -> Path:
    """Walk up from cwd and return the outermost git repo root.

    This intentionally favors the top-level repository when invoked from
    nested repos/worktrees under a parent repo.
    """
    current = Path.cwd().resolve()
    found: list[Path] = []
    while current != current.parent:
        if (current / ".git").exists():
            found.append(current)
        current = current.parent
    if found:
        return found[-1]
    return Path.cwd().resolve()


def _detect_repo_slug(repo_root: Path) -> str:
    """Extract ``owner/repo`` from the git remote origin URL.

    Falls back to an empty string if detection fails.
    """
    import subprocess  # noqa: PLC0415
    from urllib.parse import urlparse

    def _from_https(remote: str) -> str:
        parsed = urlparse(remote)
        host = (parsed.hostname or "").lower()
        if host != "github.com":
            return ""
        path = parsed.path.lstrip("/").removesuffix(".git")
        return path

    def _from_ssh(remote: str) -> str:
        # Example: git@github.com:owner/repo.git
        if "@" not in remote or ":" not in remote:
            return ""
        user_host, _, remainder = remote.partition(":")
        _, _, host = user_host.partition("@")
        if host.lower() != "github.com":
            return ""
        return remainder.lstrip("/").removesuffix(".git")

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        url = result.stdout.strip()
        if not url:
            return ""
        if url.startswith("http://") or url.startswith("https://"):
            return _from_https(url)
        if url.startswith("git@"):
            return _from_ssh(url)
        return ""
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return ""


def load_config_file(path: Path | None) -> dict[str, Any]:
    """Load a JSON config file and return its contents as a dict.

    Returns an empty dict if the file is missing, unreadable, or invalid.
    """
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_config_file(path: Path | None, values: dict[str, Any]) -> None:
    """Save config values to a JSON file, merging with existing contents.

    Uses atomic write (temp file + ``os.replace``) to prevent data loss from
    concurrent writes or crashes mid-write (TOCTOU race condition).
    """
    if path is None:
        return

    existing: dict[str, Any] = {}
    try:
        existing = json.loads(path.read_text())
        if not isinstance(existing, dict):
            logger.warning(
                "Config file %s contained non-dict JSON; starting fresh", path
            )
            existing = {}
    except FileNotFoundError:
        logger.debug("Config file %s not found; will create", path)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read config file %s: %s; starting fresh", path, exc)
    existing.update(values)
    try:
        file_util.atomic_write(path, json.dumps(existing, indent=2) + "\n")
    except OSError as exc:
        logger.warning("Failed to write config file %s: %s", path, exc)
