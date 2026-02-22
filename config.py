"""HydraFlow configuration via Pydantic."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger("hydraflow.config")

# Data-driven env-var override tables.
# Each tuple: (field_name, env_var_key, default_value)
_ENV_INT_OVERRIDES: list[tuple[str, str, int]] = [
    ("min_plan_words", "HYDRAFLOW_MIN_PLAN_WORDS", 200),
    ("max_review_fix_attempts", "HYDRAFLOW_MAX_REVIEW_FIX_ATTEMPTS", 2),
    ("min_review_findings", "HYDRAFLOW_MIN_REVIEW_FINDINGS", 3),
    ("max_issue_body_chars", "HYDRAFLOW_MAX_ISSUE_BODY_CHARS", 10_000),
    ("max_review_diff_chars", "HYDRAFLOW_MAX_REVIEW_DIFF_CHARS", 15_000),
    ("gh_max_retries", "HYDRAFLOW_GH_MAX_RETRIES", 3),
    ("max_issue_attempts", "HYDRAFLOW_MAX_ISSUE_ATTEMPTS", 3),
    ("memory_sync_interval", "HYDRAFLOW_MEMORY_SYNC_INTERVAL", 3600),
    ("metrics_sync_interval", "HYDRAFLOW_METRICS_SYNC_INTERVAL", 7200),
    ("max_merge_conflict_fix_attempts", "HYDRAFLOW_MAX_MERGE_CONFLICT_FIX_ATTEMPTS", 3),
    ("data_poll_interval", "HYDRAFLOW_DATA_POLL_INTERVAL", 60),
    ("max_sessions_per_repo", "HYDRAFLOW_MAX_SESSIONS_PER_REPO", 10),
    ("max_transcript_summary_chars", "HYDRAFLOW_MAX_TRANSCRIPT_SUMMARY_CHARS", 50_000),
    ("pr_unstick_interval", "HYDRAFLOW_PR_UNSTICK_INTERVAL", 3600),
    ("pr_unstick_batch_size", "HYDRAFLOW_PR_UNSTICK_BATCH_SIZE", 10),
]

_ENV_STR_OVERRIDES: list[tuple[str, str, str]] = [
    ("test_command", "HYDRAFLOW_TEST_COMMAND", "make test"),
    ("docker_image", "HYDRAFLOW_DOCKER_IMAGE", "ghcr.io/t-rav/hydraflow-agent:latest"),
    ("transcript_summary_model", "HYDRAFLOW_TRANSCRIPT_SUMMARY_MODEL", "haiku"),
]

_ENV_FLOAT_OVERRIDES: list[tuple[str, str, float]] = [
    ("docker_cpu_limit", "HYDRAFLOW_DOCKER_CPU_LIMIT", 2.0),
    ("docker_spawn_delay", "HYDRAFLOW_DOCKER_SPAWN_DELAY", 2.0),
]

_ENV_BOOL_OVERRIDES: list[tuple[str, str, bool]] = [
    ("docker_read_only_root", "HYDRAFLOW_DOCKER_READ_ONLY_ROOT", True),
    ("docker_no_new_privileges", "HYDRAFLOW_DOCKER_NO_NEW_PRIVILEGES", True),
    (
        "transcript_summarization_enabled",
        "HYDRAFLOW_TRANSCRIPT_SUMMARIZATION_ENABLED",
        True,
    ),
]

# Label env var overrides — maps env key → (field_name, default_value)
_ENV_LABEL_MAP: dict[str, tuple[str, list[str]]] = {
    "HYDRAFLOW_LABEL_FIND": ("find_label", ["hydraflow-find"]),
    "HYDRAFLOW_LABEL_PLAN": ("planner_label", ["hydraflow-plan"]),
    "HYDRAFLOW_LABEL_READY": ("ready_label", ["hydraflow-ready"]),
    "HYDRAFLOW_LABEL_REVIEW": ("review_label", ["hydraflow-review"]),
    "HYDRAFLOW_LABEL_HITL": ("hitl_label", ["hydraflow-hitl"]),
    "HYDRAFLOW_LABEL_HITL_ACTIVE": ("hitl_active_label", ["hydraflow-hitl-active"]),
    "HYDRAFLOW_LABEL_FIXED": ("fixed_label", ["hydraflow-fixed"]),
    "HYDRAFLOW_LABEL_IMPROVE": ("improve_label", ["hydraflow-improve"]),
    "HYDRAFLOW_LABEL_MEMORY": ("memory_label", ["hydraflow-memory"]),
    "HYDRAFLOW_LABEL_METRICS": ("metrics_label", ["hydraflow-metrics"]),
    "HYDRAFLOW_LABEL_DUP": ("dup_label", ["hydraflow-dup"]),
    "HYDRAFLOW_LABEL_EPIC": ("epic_label", ["hydraflow-epic"]),
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

    # Worker configuration
    max_workers: int = Field(default=3, ge=1, le=10, description="Concurrent agents")
    max_planners: int = Field(
        default=1, ge=1, le=10, description="Concurrent planning agents"
    )
    max_reviewers: int = Field(
        default=5, ge=1, le=10, description="Concurrent review agents"
    )
    max_hitl_workers: int = Field(
        default=1, ge=1, le=5, description="Concurrent HITL correction agents"
    )
    max_budget_usd: float = Field(
        default=0, ge=0, description="USD cap per implementation agent (0 = unlimited)"
    )
    model: str = Field(default="opus", description="Model for implementation agents")

    # Review configuration
    review_model: str = Field(default="opus", description="Model for review agents")
    review_budget_usd: float = Field(
        default=0, ge=0, description="USD cap per review agent (0 = unlimited)"
    )

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

    # Discovery / planner configuration
    find_label: list[str] = Field(
        default=["hydraflow-find"],
        description="Labels for new issues to discover and triage into planning (OR logic)",
    )
    planner_label: list[str] = Field(
        default=["hydraflow-plan"],
        description="Labels for issues needing plans (OR logic)",
    )
    planner_model: str = Field(default="opus", description="Model for planning agents")
    planner_budget_usd: float = Field(
        default=0, ge=0, description="USD cap per planning agent (0 = unlimited)"
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

    # Agent prompt configuration
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
    memory_compaction_model: str = Field(
        default="haiku",
        description="Cheap model for summarising memory digest when over size limit",
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
    max_transcript_summary_chars: int = Field(
        default=50_000,
        ge=5_000,
        le=500_000,
        description="Max transcript characters to send for summarization (truncated from end)",
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
        default=60,
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
        description="Max HITL items to process per unsticker cycle",
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
    ac_budget_usd: float = Field(
        default=0, ge=0, description="USD cap for AC generation agent (0 = unlimited)"
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

    # Docker execution (PR #545)
    docker_enabled: bool = Field(
        default=False,
        description="Run agent subprocesses inside Docker containers",
    )
    docker_network: str = Field(
        default="",
        description="Docker network name (empty = default bridge)",
    )
    docker_extra_mounts: list[str] = Field(
        default=[],
        description="Additional volume mounts as host:container:mode strings",
    )

    # GitHub authentication
    gh_token: str = Field(
        default="",
        description="GitHub token for gh CLI auth (overrides shell GH_TOKEN)",
    )

    @field_validator("docker_memory_limit", "docker_tmp_size")
    @classmethod
    def validate_docker_size_notation(cls, v: str) -> str:
        """Validate Docker size notation (digits followed by b/k/m/g)."""
        if not re.fullmatch(r"\d+[bkmg]", v, re.IGNORECASE):
            msg = f"Invalid Docker size notation '{v}'; expected digits followed by b/k/m/g (e.g., '4g', '512m')"
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
            self.fixed_label,
            self.improve_label,
        ):
            result.extend(labels)
        return result

    def branch_for_issue(self, issue_number: int) -> str:
        """Return the canonical branch name for a given issue number."""
        return f"agent/issue-{issue_number}"

    def worktree_path_for_issue(self, issue_number: int) -> Path:
        """Return the worktree directory path for a given issue number."""
        return self.worktree_base / f"issue-{issue_number}"

    @model_validator(mode="after")
    def resolve_defaults(self) -> HydraFlowConfig:
        """Resolve paths, repo slug, and apply env var overrides.

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
            HYDRAFLOW_LABEL_HITL_ACTIVE → hitl_active_label
            HYDRAFLOW_LABEL_FIXED       → fixed_label
            HYDRAFLOW_LABEL_IMPROVE     → improve_label
            HYDRAFLOW_LABEL_MEMORY      → memory_label
            HYDRAFLOW_LABEL_DUP         → dup_label
        """
        _resolve_paths(self)
        _resolve_repo_and_identity(self)
        _apply_env_overrides(self)
        _validate_docker(self)
        return self


def _resolve_paths(config: HydraFlowConfig) -> None:
    """Resolve repo_root, worktree_base, state_file, and event_log_path."""
    if config.repo_root == Path("."):
        config.repo_root = _find_repo_root()
    if config.worktree_base == Path("."):
        config.worktree_base = config.repo_root.parent / "hydraflow-worktrees"
    if config.state_file == Path("."):
        config.state_file = config.repo_root / ".hydraflow" / "state.json"
    if config.event_log_path == Path("."):
        config.event_log_path = config.repo_root / ".hydraflow" / "events.jsonl"


def _resolve_repo_and_identity(config: HydraFlowConfig) -> None:
    """Resolve repo slug, GitHub token, and git identity from env vars."""
    # Repo slug: env var → git remote → empty
    if not config.repo:
        config.repo = os.environ.get("HYDRAFLOW_GITHUB_REPO", "") or _detect_repo_slug(
            config.repo_root
        )

    # GitHub token: explicit value → HYDRAFLOW_GH_TOKEN env var → inherited GH_TOKEN
    if not config.gh_token:
        env_token = os.environ.get("HYDRAFLOW_GH_TOKEN", "")
        if env_token:
            object.__setattr__(config, "gh_token", env_token)

    # Git identity: explicit value → HYDRAFLOW_GIT_USER_NAME/EMAIL env var
    if not config.git_user_name:
        env_name = os.environ.get("HYDRAFLOW_GIT_USER_NAME", "")
        if env_name:
            object.__setattr__(config, "git_user_name", env_name)
    if not config.git_user_email:
        env_email = os.environ.get("HYDRAFLOW_GIT_USER_EMAIL", "")
        if env_email:
            object.__setattr__(config, "git_user_email", env_email)


def _apply_env_overrides(config: HydraFlowConfig) -> None:
    """Apply all data-driven and special-case env var overrides."""
    # Data-driven env var overrides (int fields)
    for field, env_key, default in _ENV_INT_OVERRIDES:
        if getattr(config, field) == default:
            env_val = os.environ.get(env_key)
            if env_val is not None:
                with contextlib.suppress(ValueError):
                    object.__setattr__(config, field, int(env_val))

    # Data-driven env var overrides (str fields)
    for field, env_key, default in _ENV_STR_OVERRIDES:
        if getattr(config, field) == default:
            env_val = os.environ.get(env_key)
            if env_val is not None:
                object.__setattr__(config, field, env_val)

    # Data-driven env var overrides (float fields)
    for field, env_key, default in _ENV_FLOAT_OVERRIDES:
        if getattr(config, field) == default:
            env_val = os.environ.get(env_key)
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

    # Data-driven env var overrides (bool fields)
    for field, env_key, default in _ENV_BOOL_OVERRIDES:
        if getattr(config, field) == default:
            env_val = os.environ.get(env_key)
            if env_val is not None:
                object.__setattr__(
                    config,
                    field,
                    env_val.lower() not in ("0", "false", "no"),
                )

    # Literal-typed env var overrides (validated before setting)
    if config.execution_mode == "host":
        env_exec = os.environ.get("HYDRAFLOW_EXECUTION_MODE")
        if env_exec in ("host", "docker"):
            object.__setattr__(config, "execution_mode", env_exec)

    if config.docker_network_mode == "bridge":
        env_net = os.environ.get("HYDRAFLOW_DOCKER_NETWORK_MODE")
        if env_net in ("bridge", "none", "host"):
            object.__setattr__(config, "docker_network_mode", env_net)

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
            except ValueError:
                pass
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
            # Empty string → empty list (scan-all mode); otherwise split on comma
            labels = (
                [part.strip() for part in env_val.split(",") if part.strip()]
                if env_val
                else []
            )
            object.__setattr__(config, field_name, labels)

    # Docker execution overrides (PR #545)
    env_docker_enabled = os.environ.get("HYDRA_DOCKER_ENABLED")
    if env_docker_enabled is not None and config.docker_enabled is False:
        object.__setattr__(
            config,
            "docker_enabled",
            env_docker_enabled.lower() in ("1", "true", "yes"),
        )

    env_docker_image = os.environ.get("HYDRA_DOCKER_IMAGE")
    if (
        env_docker_image is not None
        and config.docker_image == "ghcr.io/t-rav/hydraflow-agent:latest"
    ):
        object.__setattr__(config, "docker_image", env_docker_image)

    env_docker_network = os.environ.get("HYDRA_DOCKER_NETWORK")
    if env_docker_network is not None and not config.docker_network:
        object.__setattr__(config, "docker_network", env_docker_network)

    if config.docker_spawn_delay == 2.0:  # still at default
        env_spawn_delay = os.environ.get("HYDRA_DOCKER_SPAWN_DELAY")
        if env_spawn_delay is not None:
            with contextlib.suppress(ValueError):
                object.__setattr__(config, "docker_spawn_delay", float(env_spawn_delay))


def _validate_docker(config: HydraFlowConfig) -> None:
    """Validate Docker availability when execution_mode is 'docker'."""
    if config.execution_mode == "docker":
        import shutil  # noqa: PLC0415

        if shutil.which("docker") is None:
            msg = (
                "execution_mode is 'docker' but the 'docker' command "
                "was not found on PATH"
            )
            raise ValueError(msg)


def _find_repo_root() -> Path:
    """Walk up from cwd to find the git repo root."""
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return Path.cwd().resolve()


def _detect_repo_slug(repo_root: Path) -> str:
    """Extract ``owner/repo`` from the git remote origin URL.

    Falls back to an empty string if detection fails.
    """
    import subprocess  # noqa: PLC0415

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        url = result.stdout.strip()
        if not url:
            return ""
        # Handle HTTPS: https://github.com/owner/repo.git
        # Handle SSH:   git@github.com:owner/repo.git
        url = url.removesuffix(".git")
        if "github.com/" in url:
            return url.split("github.com/")[-1]
        if "github.com:" in url:
            return url.split("github.com:")[-1]
        return ""
    except (FileNotFoundError, OSError):
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
    """Save config values to a JSON file, merging with existing contents."""
    if path is None:
        return
    existing: dict[str, Any] = {}
    try:
        existing = json.loads(path.read_text())
        if not isinstance(existing, dict):
            existing = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    existing.update(values)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2) + "\n")
    except OSError:
        logger.warning("Failed to write config file %s", path)
