"""Data models for HydraFlow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Literal,
    NamedTuple,
    NotRequired,
    Protocol,
)
from uuid import uuid4

from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)
from typing_extensions import TypedDict

if TYPE_CHECKING:
    from pathlib import Path

# --- Shared validated types ---


def _check_url(v: str) -> str:
    """Accept empty strings or valid http(s):// URLs."""
    if v and not v.startswith(("http://", "https://")):
        msg = f"URL must be empty or start with http(s)://, got: {v!r}"
        raise ValueError(msg)
    return v


def _check_iso_timestamp(v: str) -> str:
    """Accept empty strings or valid ISO 8601 timestamps."""
    if v:
        try:
            datetime.fromisoformat(v)
        except (ValueError, TypeError) as exc:
            msg = f"Invalid ISO 8601 timestamp: {v!r}"
            raise ValueError(msg) from exc
    return v


HttpUrl = Annotated[str, AfterValidator(_check_url)]
IsoTimestamp = Annotated[str, AfterValidator(_check_iso_timestamp)]

# --- Task (source-agnostic task abstraction) ---


class TaskLinkKind(StrEnum):
    """Relationship kind between two tasks."""

    RELATES_TO = "relates_to"
    DUPLICATES = "duplicates"
    SUPERSEDES = "supersedes"
    REPLIES_TO = "replies_to"
    BLOCKS = "blocks"
    BLOCKED_BY = "blocked_by"


class TaskLink(BaseModel):
    """A directed relationship from one task to another."""

    kind: TaskLinkKind
    target_id: int
    target_url: str = ""


# Compiled patterns: (pattern, kind). Order matters — first match per target_id wins.
_LINK_PATTERNS: list[tuple[re.Pattern[str], TaskLinkKind]] = [
    (re.compile(r"\brelates?\s+to\s+#(\d+)", re.IGNORECASE), TaskLinkKind.RELATES_TO),
    (re.compile(r"\brelated:?\s+#(\d+)", re.IGNORECASE), TaskLinkKind.RELATES_TO),
    (re.compile(r"\bduplicates?\s+#(\d+)", re.IGNORECASE), TaskLinkKind.DUPLICATES),
    (re.compile(r"\bduplicate\s+of\s+#(\d+)", re.IGNORECASE), TaskLinkKind.DUPLICATES),
    (re.compile(r"\bsupersedes?\s+#(\d+)", re.IGNORECASE), TaskLinkKind.SUPERSEDES),
    (re.compile(r"\breplaces?\s+#(\d+)", re.IGNORECASE), TaskLinkKind.SUPERSEDES),
    (
        re.compile(r"\brepl(?:ies|y)\s+to\s+#(\d+)", re.IGNORECASE),
        TaskLinkKind.REPLIES_TO,
    ),
    (
        re.compile(r"\bin\s+response\s+to\s+#(\d+)", re.IGNORECASE),
        TaskLinkKind.REPLIES_TO,
    ),
    (re.compile(r"\bblocks?\s+#(\d+)", re.IGNORECASE), TaskLinkKind.BLOCKS),
    (
        re.compile(r"\bblocked\s+by\s+#(\d+)", re.IGNORECASE),
        TaskLinkKind.BLOCKED_BY,
    ),
]


def parse_task_links(body: str) -> list[TaskLink]:
    """Extract structured cross-task links from a task body.

    Scans *body* for Markdown prose patterns (e.g. "relates to #12",
    "duplicate of #5") and returns a deduplicated list of
    :class:`TaskLink` objects.  First match wins per *target_id*.
    """
    seen: dict[int, TaskLink] = {}
    for pattern, kind in _LINK_PATTERNS:
        for match in pattern.finditer(body):
            target_id = int(match.group(1))
            if target_id not in seen:
                seen[target_id] = TaskLink(kind=kind, target_id=target_id)
    # Preserve discovery order (Python 3.7+ dict maintains insertion order).
    return list(seen.values())


class Task(BaseModel):
    """Source-agnostic task representation.

    Maps to a GitHub issue or any other task backend.
    """

    id: int
    title: str
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)
    source_url: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    links: list[TaskLink] = Field(default_factory=list)
    parent_epic: int | None = None


# --- GitHub ---


class GitHubIssue(BaseModel):
    """A GitHub issue fetched for processing."""

    number: int
    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)
    url: HttpUrl = ""
    author: str = ""
    state: str = "open"  # "open" or "closed" from GitHub API
    milestone_number: int | None = None
    created_at: str = Field(
        default="",
        validation_alias=AliasChoices("createdAt", "created_at"),
    )

    @field_validator("labels", mode="before")
    @classmethod
    def _normalise_labels(cls, v: Any) -> list[str]:
        """Normalise ``gh`` CLI label objects (``{"name": "..."}`` dicts) to plain strings."""
        if isinstance(v, list):
            return [lbl["name"] if isinstance(lbl, dict) else str(lbl) for lbl in v]
        return v  # type: ignore[return-value]

    @field_validator("comments", mode="before")
    @classmethod
    def _normalise_comments(cls, v: Any) -> list[str]:
        """Normalise ``gh`` CLI comment objects (``{"body": "..."}`` dicts) to plain strings."""
        if isinstance(v, list):
            return [c.get("body", "") if isinstance(c, dict) else str(c) for c in v]
        return v  # type: ignore[return-value]

    def to_task(self) -> Task:
        """Convert to a source-agnostic :class:`Task`."""
        metadata: dict[str, Any] = {}
        if self.author:
            metadata["author"] = self.author
        if self.milestone_number is not None:
            metadata["milestone_number"] = self.milestone_number
        return Task(
            id=self.number,
            title=self.title,
            body=self.body,
            tags=list(self.labels),
            comments=list(self.comments),
            source_url=self.url,
            created_at=self.created_at,
            links=parse_task_links(self.body),
            metadata=metadata,
        )

    @classmethod
    def from_task(cls, task: Task) -> GitHubIssue:
        """Reconstruct a :class:`GitHubIssue` from a :class:`Task`."""
        return cls(
            number=task.id,
            title=task.title,
            body=task.body,
            labels=list(task.tags),
            comments=list(task.comments),
            url=task.source_url,
            created_at=task.created_at,
            author=task.metadata.get("author", ""),
        )


# --- Triage ---


class TriageStatus(StrEnum):
    """Lifecycle status of a triage evaluation."""

    EVALUATING = "evaluating"
    DONE = "done"
    FAILED = "failed"


class TriageResult(BaseModel):
    """Outcome of evaluating a single issue for readiness."""

    issue_number: int
    ready: bool = False
    reasons: list[str] = Field(default_factory=list)
    complexity_score: int = 0
    issue_type: str = "feature"  # "feature" | "bug" | "epic"
    enrichment: str = ""


class EpicDecompResult(BaseModel):
    """Result of auto-decomposing a large issue into an epic."""

    should_decompose: bool = False
    epic_title: str = ""
    epic_body: str = ""
    children: list[NewIssueSpec] = Field(default_factory=list)
    reasoning: str = ""


# --- Planner ---


class PlannerStatus(StrEnum):
    """Lifecycle status of a planning agent."""

    QUEUED = "queued"
    PLANNING = "planning"
    VALIDATING = "validating"
    RETRYING = "retrying"
    DONE = "done"
    FAILED = "failed"


class NewIssueSpec(BaseModel):
    """Specification for a new issue discovered during planning."""

    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)


class PlanResult(BaseModel):
    """Outcome of a planner agent run."""

    issue_number: int
    success: bool = False
    plan: str = ""
    summary: str = ""
    error: str | None = None
    transcript: str = ""
    duration_seconds: float = 0.0
    new_issues: list[NewIssueSpec] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    actionability_score: int = 0
    actionability_rank: str = "unknown"
    retry_attempted: bool = False
    already_satisfied: bool = False
    epic_number: int = 0


class EpicGapReview(BaseModel):
    """Result of a gap review across an epic's child plans."""

    epic_number: int
    findings: str = ""
    replan_issues: list[int] = Field(default_factory=list)
    guidance: str = ""


# --- Delta Verification ---


class DeltaReport(BaseModel):
    """Report comparing planned file changes against actual git diff."""

    planned: list[str] = Field(default_factory=list)
    actual: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unexpected: list[str] = Field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        """Return True if there is any drift between planned and actual."""
        return bool(self.missing or self.unexpected)

    def format_summary(self) -> str:
        """Format a concise summary of the delta comparison."""
        lines = [
            f"**Planned:** {len(self.planned)} files | **Actual:** {len(self.actual)} files"
        ]
        if self.missing:
            lines.append(
                f"**Missing** (planned but not changed): {', '.join(self.missing)}"
            )
        if self.unexpected:
            lines.append(
                f"**Unexpected** (changed but not planned): {', '.join(self.unexpected)}"
            )
        if not self.has_drift:
            lines.append("No drift detected.")
        return "\n".join(lines)


# --- Pre-Implementation Analysis ---


class AnalysisVerdict(StrEnum):
    """Verdict for a pre-implementation analysis section."""

    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class AnalysisSection(BaseModel):
    """A single section of a pre-implementation analysis."""

    name: str
    verdict: AnalysisVerdict
    details: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Full result of a pre-implementation analysis."""

    issue_number: int
    sections: list[AnalysisSection] = Field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """Return True if any section has a BLOCK verdict."""
        return any(s.verdict == AnalysisVerdict.BLOCK for s in self.sections)

    def format_comment(self) -> str:
        """Format the analysis result as a markdown comment."""
        verdict_icons = {
            AnalysisVerdict.PASS: "\u2705 PASS",
            AnalysisVerdict.WARN: "\u26a0\ufe0f WARN",
            AnalysisVerdict.BLOCK: "\U0001f6d1 BLOCK",
        }
        lines = ["## Pre-Implementation Analysis\n"]
        for section in self.sections:
            lines.append(f"### {section.name} {verdict_icons[section.verdict]}")
            for detail in section.details:
                lines.append(f"- {detail}")
            lines.append("")
        lines.append("---\n*Generated by HydraFlow Analyzer*")
        return "\n".join(lines)


# --- Worker ---


class WorkerStatus(StrEnum):
    """Lifecycle status of an implementation worker."""

    QUEUED = "queued"
    RUNNING = "running"
    PRE_QUALITY_REVIEW = "pre_quality_review"
    TESTING = "testing"
    COMMITTING = "committing"
    QUALITY_FIX = "quality_fix"
    MERGE_FIX = "merge_fix"
    FRESH_REBUILD = "fresh_rebuild"
    DONE = "done"
    FAILED = "failed"


class WorkerResult(BaseModel):
    """Outcome of an implementation worker run."""

    issue_number: int
    branch: str
    worktree_path: str = ""
    success: bool = False
    error: str | None = None
    transcript: str = ""
    commits: int = 0
    duration_seconds: float = 0.0
    pre_quality_review_attempts: int = 0
    quality_fix_attempts: int = 0
    pr_info: PRInfo | None = None


# --- Pull Requests ---


class PRInfo(BaseModel):
    """Metadata for a created pull request."""

    number: int
    issue_number: int
    branch: str
    url: HttpUrl = ""
    draft: bool = False


# --- HITL ---


class HITLResult(BaseModel):
    """Outcome of an HITL correction agent run."""

    issue_number: int
    success: bool = False
    error: str | None = None
    transcript: str = ""
    duration_seconds: float = 0.0


class VisualEvidenceItem(BaseModel):
    """A single visual check result (screenshot diff, etc.)."""

    screen_name: str
    diff_percent: float = 0.0
    baseline_url: HttpUrl = ""
    actual_url: HttpUrl = ""
    diff_url: HttpUrl = ""
    status: Literal["pass", "fail", "warn"]


class VisualEvidence(BaseModel):
    """Container for visual validation evidence attached to HITL items."""

    items: list[VisualEvidenceItem] = Field(default_factory=list)
    summary: str = ""
    run_url: HttpUrl = ""
    attempt: int = 1


# --- Reviews ---


class VerificationCriteria(BaseModel):
    """Structured acceptance criteria and verification instructions for a merged PR."""

    issue_number: int
    pr_number: int
    acceptance_criteria: str
    verification_instructions: str
    timestamp: IsoTimestamp


class ReviewerStatus(StrEnum):
    """Lifecycle status of a reviewer agent."""

    REVIEWING = "reviewing"
    DONE = "done"
    FAILED = "failed"
    FIXING = "fixing"
    FIX_DONE = "fix_done"


class ReviewVerdict(StrEnum):
    """Verdict from a reviewer agent."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request-changes"
    COMMENT = "comment"


class ReviewResult(BaseModel):
    """Outcome of a reviewer agent run."""

    pr_number: int
    issue_number: int
    verdict: ReviewVerdict = ReviewVerdict.COMMENT
    summary: str = ""
    fixes_made: bool = False
    transcript: str = ""
    merged: bool = False
    ci_passed: bool | None = None  # None = not checked, True/False = outcome
    ci_fix_attempts: int = 0
    duration_seconds: float = 0.0
    visual_passed: bool | None = None  # None = not checked, True/False = outcome


# --- Visual Validation ---


class VisualFailureClass(StrEnum):
    """Classification of a visual validation failure."""

    INFRA_FAILURE = "infra_failure"
    VISUAL_DIFF = "visual_diff"
    TIMEOUT = "timeout"
    CAPTURE_ERROR = "capture_error"


class VisualScreenVerdict(StrEnum):
    """Verdict for a single visual screen check."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class VisualScreenResult(BaseModel):
    """Result of a single visual screen validation."""

    screen_name: str
    diff_ratio: float = 0.0
    verdict: VisualScreenVerdict = VisualScreenVerdict.PASS
    failure_class: VisualFailureClass | None = None
    error: str = ""
    retries_used: int = 0


class VisualValidationReport(BaseModel):
    """Aggregated result of all visual screen validations."""

    screens: list[VisualScreenResult] = Field(default_factory=list)
    overall_verdict: VisualScreenVerdict = VisualScreenVerdict.PASS
    total_retries: int = 0
    infra_failures: int = 0
    visual_diffs: int = 0

    @property
    def has_failures(self) -> bool:
        """Return True if any screen failed."""
        return self.overall_verdict == VisualScreenVerdict.FAIL

    @property
    def has_warnings(self) -> bool:
        """Return True if any screen has a warning or failure."""
        return self.overall_verdict in (
            VisualScreenVerdict.WARN,
            VisualScreenVerdict.FAIL,
        )

    def format_summary(self) -> str:
        """Format a human-readable summary for PR comments."""
        lines: list[str] = ["## Visual Validation Report", ""]
        lines.append(f"**Overall: {self.overall_verdict.value.upper()}**")
        if self.total_retries:
            lines.append(f"Total retries: {self.total_retries}")
        if self.infra_failures:
            lines.append(f"Infrastructure failures: {self.infra_failures}")
        lines.append("")

        for screen in self.screens:
            icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(
                screen.verdict.value, "❓"
            )
            line = f"- {icon} **{screen.screen_name}**: {screen.verdict.value.upper()}"
            if screen.diff_ratio > 0:
                line += f" (diff: {screen.diff_ratio:.2%})"
            if screen.failure_class:
                line += f" [{screen.failure_class.value}]"
            if screen.retries_used:
                label = "retry" if screen.retries_used == 1 else "retries"
                line += f" ({screen.retries_used} {label})"
            if screen.error:
                line += f" — {screen.error}"
            lines.append(line)
        return "\n".join(lines)


class VisualValidationPolicy(StrEnum):
    """Deterministic policy for visual validation scope."""

    REQUIRED = "required"
    SKIPPED = "skipped"


class VisualValidationDecision(BaseModel):
    """Deterministic decision about whether visual validation is required."""

    policy: VisualValidationPolicy
    reason: str
    triggered_patterns: list[str] = Field(default_factory=list)
    override_label: str | None = None


# --- Verification Judge ---


class CriterionVerdict(StrEnum):
    """Verdict for a single acceptance criterion."""

    PASS = "pass"
    FAIL = "fail"


class CriterionResult(BaseModel):
    """Result of evaluating a single acceptance criterion against the code."""

    criterion: str
    verdict: CriterionVerdict = CriterionVerdict.FAIL
    reasoning: str = ""


class InstructionsQuality(StrEnum):
    """Quality verdict for human verification instructions."""

    READY = "ready"
    NEEDS_REFINEMENT = "needs_refinement"


class JudgeVerdict(BaseModel):
    """Full result of the verification judge evaluation."""

    issue_number: int
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    all_criteria_pass: bool = False
    instructions_quality: InstructionsQuality = InstructionsQuality.NEEDS_REFINEMENT
    instructions_feedback: str = ""
    refined: bool = False
    summary: str = ""
    verification_instructions: str = ""


class VerificationCriterion(BaseModel):
    """Result of evaluating a single acceptance criterion at code level."""

    description: str
    passed: bool
    details: str = ""


class JudgeResult(BaseModel):
    """Overall result from the LLM judge evaluating acceptance criteria."""

    issue_number: int
    pr_number: int
    criteria: list[VerificationCriterion] = Field(default_factory=list)
    verification_instructions: str = ""
    summary: str = ""

    @property
    def all_passed(self) -> bool:
        """Return True if every criterion passed."""
        return all(c.passed for c in self.criteria)

    @property
    def failed_criteria(self) -> list[VerificationCriterion]:
        """Return only the criteria that failed."""
        return [c for c in self.criteria if not c.passed]


# --- Batch ---


class BatchResult(BaseModel):
    """Summary of a full batch cycle."""

    batch_number: int
    issues: list[Task] = Field(default_factory=list)
    plan_results: list[PlanResult] = Field(default_factory=list)
    worker_results: list[WorkerResult] = Field(default_factory=list)
    pr_infos: list[PRInfo] = Field(default_factory=list)
    review_results: list[ReviewResult] = Field(default_factory=list)
    merged_prs: list[int] = Field(default_factory=list)


# --- Baseline Policy ---


class BaselineChangeType(StrEnum):
    """Type of baseline image change."""

    UPDATE = "update"
    ROLLBACK = "rollback"
    INITIAL = "initial"


class BaselineAuditRecord(BaseModel):
    """Audit trail entry for a baseline image change."""

    pr_number: int
    issue_number: int
    changed_files: list[str] = Field(default_factory=list)
    change_type: BaselineChangeType = BaselineChangeType.UPDATE
    approver: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    reason: str = ""
    commit_sha: str = ""


class BaselineApprovalResult(BaseModel):
    """Result of a baseline approval check on a PR."""

    approved: bool = False
    approver: str = ""
    changed_files: list[str] = Field(default_factory=list)
    reason: str = ""
    requires_approval: bool = False


# --- Orchestrator Phases ---


class Phase(StrEnum):
    """Phases of the orchestrator loop."""

    IDLE = "idle"
    PLAN = "plan"
    IMPLEMENT = "implement"
    REVIEW = "review"
    CLEANUP = "cleanup"
    DONE = "done"


# --- State Persistence ---


class QueueStats(BaseModel):
    """Snapshot of IssueStore queue depths and throughput."""

    queue_depth: dict[str, int] = Field(default_factory=dict)
    active_count: dict[str, int] = Field(default_factory=dict)
    total_processed: dict[str, int] = Field(default_factory=dict)
    last_poll_timestamp: str | None = None
    dedup_stats: dict[str, int] = Field(default_factory=dict)
    in_flight_count: int = 0


class StageStats(BaseModel):
    """Per-stage snapshot of queue depth, active count, and completions."""

    queued: int = 0
    active: int = 0
    completed_session: int = 0
    completed_lifetime: int = 0
    worker_count: int = 0
    worker_cap: int | None = None


class ThroughputStats(BaseModel):
    """Issues processed per hour, computed per stage."""

    triage: float = 0.0
    plan: float = 0.0
    implement: float = 0.0
    review: float = 0.0
    hitl: float = 0.0


class PipelineStats(BaseModel):
    """Unified real-time pipeline state emitted periodically by the orchestrator."""

    timestamp: str
    stages: dict[str, StageStats] = Field(default_factory=dict)
    queue: QueueStats = Field(default_factory=QueueStats)
    throughput: ThroughputStats = Field(default_factory=ThroughputStats)
    uptime_seconds: float = 0.0


class RepoRuntimeInfo(BaseModel):
    """Snapshot of a single repo runtime for API/dashboard consumption."""

    slug: str
    repo: str = ""
    running: bool = False
    session_id: str | None = None
    uptime_seconds: float = 0.0


class IssueOutcomeType(StrEnum):
    """How an issue was ultimately resolved."""

    MERGED = "merged"
    ALREADY_SATISFIED = "already_satisfied"
    HITL_CLOSED = "hitl_closed"
    HITL_SKIPPED = "hitl_skipped"
    HITL_APPROVED = "hitl_approved"
    FAILED = "failed"
    MANUAL_CLOSE = "manual_close"


class IssueOutcome(BaseModel):
    """Structured record of how and why an issue was closed."""

    outcome: IssueOutcomeType
    reason: str
    closed_at: str
    pr_number: int | None = None
    phase: str


class HookFailureRecord(BaseModel):
    """Record of a post-merge hook failure."""

    hook_name: str
    error: str
    timestamp: str


class HITLCloseRequest(BaseModel):
    """Request body for POST /api/hitl/{issue_number}/close."""

    reason: str = Field(..., min_length=1)


class HITLSkipRequest(BaseModel):
    """Request body for POST /api/hitl/{issue_number}/skip."""

    reason: str = Field(..., min_length=1)


class SessionStatus(StrEnum):
    """Lifecycle status of an orchestrator session."""

    ACTIVE = "active"
    COMPLETED = "completed"


class SessionLog(BaseModel):
    """A single orchestrator session — one per run() invocation."""

    id: str
    repo: str
    started_at: str
    ended_at: str | None = None
    issues_processed: list[int] = Field(default_factory=list)
    issues_succeeded: int = 0
    issues_failed: int = 0
    status: SessionStatus = SessionStatus.ACTIVE


class SessionCounters(BaseModel):
    """Per-session completion counts, persisted to state.json."""

    triaged: int = 0
    planned: int = 0
    implemented: int = 0
    reviewed: int = 0
    merged: int = 0
    session_start: str = ""


class LifetimeStats(BaseModel):
    """All-time counters preserved across resets."""

    # Existing
    issues_completed: int = 0
    prs_merged: int = 0
    issues_created: int = 0
    # Volume counters
    total_quality_fix_rounds: int = 0
    total_ci_fix_rounds: int = 0
    total_hitl_escalations: int = 0
    total_review_request_changes: int = 0
    total_review_approvals: int = 0
    total_reviewer_fixes: int = 0
    # Timing
    total_implementation_seconds: float = 0.0
    total_review_seconds: float = 0.0
    # Time-to-merge tracking (list of seconds from issue creation to PR merge)
    merge_durations: list[float] = Field(default_factory=list)
    # Retries per stage: {issue_number: {stage: count}}
    retries_per_stage: dict[str, dict[str, int]] = Field(default_factory=dict)
    # Outcome counters
    total_outcomes_merged: int = 0
    total_outcomes_already_satisfied: int = 0
    total_outcomes_hitl_closed: int = 0
    total_outcomes_hitl_skipped: int = 0
    total_outcomes_failed: int = 0
    total_outcomes_manual_close: int = 0
    total_outcomes_hitl_approved: int = 0
    # Threshold proposals already filed (avoid re-filing)
    fired_thresholds: list[str] = Field(default_factory=list)


class HITLSummaryCacheEntry(BaseModel):
    """Cached LLM summary for a HITL issue."""

    summary: str = ""
    updated_at: str | None = None


class HITLSummaryFailureEntry(BaseModel):
    """Cached failure metadata for HITL summary generation."""

    last_failed_at: str | None = None
    error: str = ""


class EpicState(BaseModel):
    """Persisted state for a tracked epic."""

    epic_number: int
    title: str = ""
    child_issues: list[int] = Field(default_factory=list)
    completed_children: list[int] = Field(default_factory=list)
    failed_children: list[int] = Field(default_factory=list)
    excluded_children: list[int] = Field(default_factory=list)
    hitl_warned_children: list[int] = Field(default_factory=list)
    approved_children: list[int] = Field(default_factory=list)
    merge_strategy: str = "independent"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_activity: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    closed: bool = False
    released: bool = False
    auto_decomposed: bool = False


class Release(BaseModel):
    """Persisted state for a GitHub Release created when an epic completes."""

    version: str
    epic_number: int
    sub_issues: list[int] = Field(default_factory=list)
    pr_numbers: list[int] = Field(default_factory=list)
    status: Literal["pending", "released"] = "pending"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    released_at: str | None = None
    changelog: str = ""
    tag: str = ""


class StateData(BaseModel):
    """Typed schema for the JSON-backed crash-recovery state."""

    processed_issues: dict[str, str] = Field(default_factory=dict)
    active_worktrees: dict[str, str] = Field(default_factory=dict)
    active_branches: dict[str, str] = Field(default_factory=dict)
    reviewed_prs: dict[str, str] = Field(default_factory=dict)
    hitl_origins: dict[str, str] = Field(default_factory=dict)
    hitl_causes: dict[str, str] = Field(default_factory=dict)
    hitl_summaries: dict[str, HITLSummaryCacheEntry] = Field(default_factory=dict)
    hitl_summary_failures: dict[str, HITLSummaryFailureEntry] = Field(
        default_factory=dict
    )
    hitl_visual_evidence: dict[str, VisualEvidence] = Field(default_factory=dict)
    review_attempts: dict[str, int] = Field(default_factory=dict)
    review_feedback: dict[str, str] = Field(default_factory=dict)
    worker_result_meta: dict[str, WorkerResultMeta] = Field(default_factory=dict)
    bg_worker_states: dict[str, BackgroundWorkerState] = Field(default_factory=dict)
    worker_heartbeats: dict[str, PersistedWorkerHeartbeat] = Field(default_factory=dict)
    verification_issues: dict[str, int] = Field(default_factory=dict)
    issue_attempts: dict[str, int] = Field(default_factory=dict)
    active_issue_numbers: list[int] = Field(default_factory=list)
    lifetime_stats: LifetimeStats = Field(default_factory=LifetimeStats)
    session_counters: SessionCounters = Field(default_factory=SessionCounters)
    memory_issue_ids: list[int] = Field(default_factory=list)
    memory_digest_hash: str = ""
    memory_last_synced: str | None = None
    manifest_issue_number: int | None = None
    manifest_snapshot_hash: str = ""
    manifest_hash: str = ""
    manifest_last_updated: str | None = None
    metrics_issue_number: int | None = None
    metrics_last_snapshot_hash: str = ""
    metrics_last_synced: str | None = None
    worker_intervals: dict[str, int] = Field(default_factory=dict)
    disabled_workers: list[str] = Field(default_factory=list)
    interrupted_issues: dict[str, str] = Field(default_factory=dict)
    last_reviewed_shas: dict[str, str] = Field(default_factory=dict)
    pending_reports: list[PendingReport] = Field(default_factory=list)
    issue_outcomes: dict[str, IssueOutcome] = Field(default_factory=dict)
    hook_failures: dict[str, list[HookFailureRecord]] = Field(default_factory=dict)
    epic_states: dict[str, EpicState] = Field(default_factory=dict)
    releases: dict[str, Release] = Field(default_factory=dict)
    baseline_audit: dict[str, list[BaselineAuditRecord]] = Field(default_factory=dict)
    active_crate_number: int | None = None
    last_updated: str | None = None


# --- Dashboard API Responses ---


class EpicProgress(BaseModel):
    """Dashboard-facing epic progress summary."""

    epic_number: int
    title: str = ""
    total_children: int = 0
    completed: int = 0
    failed: int = 0
    excluded: int = 0
    in_progress: int = 0
    approved: int = 0
    ready_to_merge: bool = False
    status: str = "active"  # "active", "completed", "stale", "blocked"
    percent_complete: float = 0.0
    last_activity: str = ""
    auto_decomposed: bool = False
    merge_strategy: str = "independent"
    child_issues: list[int] = Field(default_factory=list)


class EpicChildInfo(BaseModel):
    """Status of a single child issue within an epic."""

    issue_number: int
    title: str = ""
    url: str = ""
    state: str = "open"  # "open", "closed"
    stage: str = ""  # pipeline stage if active (triage/plan/implement/review/merged)
    current_stage: str = ""  # UI-facing alias of stage
    status: str = "queued"  # done, running, queued, failed
    is_completed: bool = False
    is_failed: bool = False
    is_excluded: bool = False
    is_approved: bool = False
    pr_number: int | None = None
    pr_url: str = ""
    pr_state: str | None = None  # open, merged, draft
    branch: str = ""
    ci_status: str | None = None  # passing, failing, pending
    review_status: str | None = None  # approved, changes_requested, pending
    time_in_stage_seconds: int = 0
    stage_entered_at: str = ""
    worker: str | None = None
    mergeable: bool | None = None


class EpicReadiness(BaseModel):
    """Readiness checks for an epic before release."""

    all_implemented: bool = False
    all_approved: bool = False
    all_ci_passing: bool = False
    no_conflicts: bool = False
    changelog_ready: bool = False
    version: str | None = None


class EpicDetail(BaseModel):
    """Full epic detail for the dashboard, including child issue info."""

    epic_number: int
    title: str = ""
    url: str = ""
    total_children: int = 0
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    merged_children: int = 0
    active_children: int = 0
    queued_children: int = 0
    approved: int = 0
    ready_to_merge: bool = False
    status: str = "active"
    percent_complete: float = 0.0
    last_activity: str = ""
    created_at: str = ""
    auto_decomposed: bool = False
    merge_strategy: str = "independent"
    children: list[EpicChildInfo] = Field(default_factory=list)
    readiness: EpicReadiness = Field(default_factory=EpicReadiness)
    release: dict | None = None


# --- Changelog ---


class ChangeCategory(StrEnum):
    """Category for a changelog entry derived from conventional commit prefixes."""

    FEATURES = "Features"
    BUG_FIXES = "Bug Fixes"
    IMPROVEMENTS = "Improvements"
    DOCUMENTATION = "Documentation"
    MISCELLANEOUS = "Miscellaneous"


class ChangelogEntry(BaseModel):
    """A single entry in a generated changelog."""

    category: ChangeCategory = ChangeCategory.MISCELLANEOUS
    title: str
    summary: str = ""
    issue_number: int = 0
    pr_number: int = 0


class Crate(BaseModel):
    """A GitHub milestone used as a delivery work package (crate)."""

    number: int
    title: str
    description: str = ""
    due_on: str | None = None
    state: str = "open"
    open_issues: int = 0
    closed_issues: int = 0
    created_at: str = ""
    updated_at: str = ""


class CrateCreateRequest(BaseModel):
    """Request body for POST /api/crates."""

    title: str
    description: str = ""
    due_on: str | None = None


class CrateUpdateRequest(BaseModel):
    """Request body for PATCH /api/crates/{number}.

    Fields use a sentinel pattern: only fields present in the request JSON
    are forwarded to GitHub.  Sending ``"due_on": null`` explicitly clears
    the milestone due date.
    """

    title: str | None = None
    description: str | None = None
    due_on: str | None = None
    state: Literal["open", "closed"] | None = None


class CrateItemsRequest(BaseModel):
    """Request body for POST/DELETE /api/crates/{number}/items."""

    issue_numbers: list[int] = Field(default_factory=list)


class PipelineIssueStatus(StrEnum):
    """Status of an issue in the pipeline snapshot."""

    QUEUED = "queued"
    ACTIVE = "active"
    PROCESSING = "processing"
    HITL = "hitl"


class PipelineIssue(BaseModel):
    """A single issue in a pipeline stage snapshot."""

    model_config = ConfigDict(frozen=True)

    issue_number: int
    title: str = ""
    url: HttpUrl = ""
    status: PipelineIssueStatus = PipelineIssueStatus.QUEUED
    epic_number: int = 0
    is_epic_child: bool = False


class PipelineSnapshot(BaseModel):
    """Snapshot of all pipeline stages with their issues."""

    stages: dict[str, list[PipelineIssue]] = Field(default_factory=dict)


class IntentRequest(BaseModel):
    """Request body for POST /api/intent."""

    text: str = Field(..., min_length=1, max_length=5000)


class IntentResponse(BaseModel):
    """Response for POST /api/intent."""

    issue_number: int
    title: str
    url: HttpUrl = ""
    status: str = "created"


class ReportIssueRequest(BaseModel):
    """Request body for POST /api/report."""

    description: str = Field(..., min_length=1, max_length=5000)
    screenshot_base64: str = Field(default="", max_length=5_000_000)
    environment: dict[str, Any] = Field(default_factory=dict)


class ReportIssueResponse(BaseModel):
    """Response for POST /api/report."""

    issue_number: int
    title: str
    url: HttpUrl = ""
    status: str = "created"


class PendingReport(BaseModel):
    """A queued bug report awaiting background processing."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    description: str
    screenshot_base64: str = ""
    environment: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PRListItem(BaseModel):
    """A PR entry returned by GET /api/prs."""

    pr: int
    issue: int = 0
    branch: str = ""
    url: HttpUrl = ""
    draft: bool = False
    title: str = ""


class HITLItem(BaseModel):
    """A HITL issue entry returned by GET /api/hitl."""

    issue: int
    title: str = ""
    issueUrl: HttpUrl = ""  # camelCase to match existing frontend contract
    pr: int = 0
    prUrl: HttpUrl = ""  # camelCase to match existing frontend contract
    branch: str = ""
    cause: str = ""  # escalation reason (populated by #113)
    status: str = "pending"  # pending | processing | resolved
    isMemorySuggestion: bool = False  # camelCase to match frontend contract
    llmSummary: str = ""  # cached, operator-focused context summary
    llmSummaryUpdatedAt: str | None = None
    visualEvidence: VisualEvidence | None = None  # camelCase to match frontend


class ControlStatusConfig(BaseModel):
    """Config subset returned by GET /api/control/status."""

    app_version: str = ""
    latest_version: str = ""
    update_available: bool = False
    repo: str = ""
    ready_label: list[str] = Field(default_factory=list)
    find_label: list[str] = Field(default_factory=list)
    planner_label: list[str] = Field(default_factory=list)
    review_label: list[str] = Field(default_factory=list)
    hitl_label: list[str] = Field(default_factory=list)
    hitl_active_label: list[str] = Field(default_factory=list)
    fixed_label: list[str] = Field(default_factory=list)
    improve_label: list[str] = Field(default_factory=list)
    memory_label: list[str] = Field(default_factory=list)
    transcript_label: list[str] = Field(default_factory=list)
    manifest_label: list[str] = Field(default_factory=list)
    max_triagers: int = 0
    max_workers: int = 0
    max_planners: int = 0
    max_reviewers: int = 0
    max_hitl_workers: int = 0
    batch_size: int = 0
    model: str = ""
    memory_auto_approve: bool = False
    pr_unstick_batch_size: int = 10
    worktree_base: str = ""


class ControlStatusResponse(BaseModel):
    """Response for GET /api/control/status."""

    status: str = "idle"
    credits_paused_until: str | None = None
    config: ControlStatusConfig = Field(default_factory=ControlStatusConfig)


# --- TypedDicts for replacing Any annotations ---


class BackgroundWorkerState(TypedDict):
    """Internal dict shape for orchestrator ``_bg_worker_states`` entries."""

    name: str
    status: str
    last_run: str | None
    details: dict[str, Any]
    enabled: NotRequired[bool]  # added by get_bg_worker_states()


class PersistedWorkerHeartbeat(TypedDict, total=False):
    """Lightweight persisted snapshot for worker heartbeats."""

    status: str
    last_run: str | None
    details: dict[str, Any]


class TranscriptEventData(TypedDict, total=False):
    """Event data shape passed to ``stream_claude_process`` and ``BaseRunner._execute``.

    All keys are optional since different runners include different subsets.
    """

    issue: int
    pr: int
    epic: int
    source: str


class WorkerUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.WORKER_UPDATE``."""

    issue: int
    worker: int
    status: str
    role: str
    repo: str


class PlannerUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.PLANNER_UPDATE``."""

    issue: int
    worker: int
    status: str
    role: str
    repo: str


class TriageUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.TRIAGE_UPDATE``."""

    issue: int
    worker: int
    status: str
    role: str
    repo: str


class ReviewUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.REVIEW_UPDATE``."""

    pr: int
    issue: int
    worker: int
    status: str
    role: str
    verdict: str
    duration: float
    repo: str


class PRCreatedPayload(TypedDict, total=False):
    """Payload for ``EventType.PR_CREATED``."""

    pr: int
    issue: int
    branch: str
    draft: bool
    url: str
    repo: str


class MergeUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.MERGE_UPDATE``."""

    pr: int
    status: str
    repo: str


class CICheckPayload(TypedDict, total=False):
    """Payload for ``EventType.CI_CHECK``."""

    pr: int
    issue: int
    status: str
    pending: int
    total: int
    failed: list[str]
    worker: int
    attempt: int
    verdict: str
    repo: str


class HITLEscalationPayload(TypedDict, total=False):
    """Payload for ``EventType.HITL_ESCALATION``."""

    issue: int
    cause: str
    origin: str
    ci_fix_attempts: int
    pr: int
    status: str
    role: str
    repo: str
    visual_evidence: dict[str, object]


class IssueCreatedPayload(TypedDict):
    """Payload for ``EventType.ISSUE_CREATED``."""

    number: int
    title: str
    labels: list[str]


class HITLUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.HITL_UPDATE``."""

    issue: int
    status: str
    action: str
    worker: int
    duration: float
    reason: str
    repo: str


class ErrorPayload(TypedDict, total=False):
    """Payload for ``EventType.ERROR``."""

    message: str
    source: str
    repo: str


class BackgroundWorkerStatusPayload(TypedDict):
    """Payload for ``EventType.BACKGROUND_WORKER_STATUS``."""

    worker: str
    status: str
    last_run: str
    details: dict[str, Any]


class OrchestratorStatusPayload(TypedDict, total=False):
    """Payload for ``EventType.ORCHESTRATOR_STATUS``."""

    status: str
    reset: bool


class SessionStartPayload(TypedDict):
    """Payload for ``EventType.SESSION_START``."""

    session_id: str
    repo: str


class SessionEndPayload(TypedDict):
    """Payload for ``EventType.SESSION_END``."""

    session_id: str
    status: str
    issues_processed: list[int]
    issues_succeeded: int
    issues_failed: int


class PipelineSnapshotEntry(TypedDict):
    """Shape of issue dicts returned by ``IssueStore.get_pipeline_snapshot``."""

    issue_number: int
    title: str
    url: str
    status: str
    epic_number: NotRequired[int]
    is_epic_child: NotRequired[bool]


class LabelCounts(TypedDict):
    """Return shape of ``PRManager.get_label_counts``."""

    open_by_label: dict[str, int]
    total_closed: int
    total_merged: int


class WorkerResultMeta(TypedDict, total=False):
    """Metadata stored by ``StateTracker.set_worker_result_meta``."""

    quality_fix_attempts: int
    duration_seconds: float
    error: str | None
    commits: int


class ManifestRefreshSummary(TypedDict):
    """Return shape of ``ManifestRefreshLoop._do_work``."""

    hash: str
    length: int


class TimelineStageMetadata(TypedDict, total=False):
    """Metadata for ``TimelineStage.metadata``."""

    verdict: str
    duration: float
    commits: int
    hitl_cause: str


class MemoryType(StrEnum):
    """Classification of a memory suggestion.

    - ``knowledge``: Passive insight — stored in digest for agent awareness.
    - ``config``: Suggests a configuration change — routed through HITL approval.
    - ``instruction``: Suggests a new agent instruction — routed through HITL approval.
    - ``code``: Suggests a code change — routed through HITL approval.
    """

    KNOWLEDGE = "knowledge"
    CONFIG = "config"
    INSTRUCTION = "instruction"
    CODE = "code"

    @classmethod
    def is_actionable(cls, memory_type: MemoryType) -> bool:
        """Return True if the memory type requires HITL approval."""
        return memory_type in (cls.CONFIG, cls.INSTRUCTION, cls.CODE)


# Ordered list for digest grouping (actionable types first, then knowledge).
MEMORY_TYPE_DISPLAY_ORDER: list[MemoryType] = [
    MemoryType.CONFIG,
    MemoryType.INSTRUCTION,
    MemoryType.CODE,
    MemoryType.KNOWLEDGE,
]


class MemoryIssueData(TypedDict):
    """Shape of issue dicts passed to ``MemorySyncWorker.sync``."""

    number: int
    title: str
    body: str
    createdAt: str
    labels: NotRequired[list[str]]


class MemorySyncResult(TypedDict):
    """Return shape of ``MemorySyncWorker.sync``."""

    action: str
    item_count: int
    compacted: bool
    digest_chars: int
    pruned: NotRequired[int]
    issues_closed: NotRequired[int]


class UnstickResult(TypedDict):
    """Return shape of ``PRUnsticker.unstick``."""

    processed: int
    resolved: int
    failed: int
    skipped: int
    merged: int


class MetricsSyncResult(TypedDict, total=False):
    """Return shape of ``MetricsManager.sync``.

    Different code paths return different subsets of keys.
    """

    status: str
    snapshot_hash: str
    timestamp: str
    reason: str
    issue_number: int


class ThresholdProposal(TypedDict):
    """Shape of items returned by ``StateTracker.check_thresholds``."""

    name: str
    metric: str
    threshold: float
    value: float
    action: str


# --- Structured Return Types ---


@dataclass(frozen=True)
class PrecheckResult:
    """Result of parsing a precheck transcript."""

    risk: str
    confidence: float
    escalate: bool
    summary: str
    parse_failed: bool


@dataclass(frozen=True)
class ConflictResolutionResult:
    """Result of a merge conflict resolution attempt."""

    success: bool
    used_rebuild: bool


class PlanAccuracyResult(NamedTuple):
    """Result of computing plan accuracy."""

    accuracy: float
    unplanned: list[str]
    missed: list[str]


class PRInfoExtract(NamedTuple):
    """Extracted PR info from timeline events."""

    pr_number: int | None
    url: str
    branch: str


class ManifestRefreshResult(NamedTuple):
    """Result of a manifest refresh."""

    content: str
    digest_hash: str


class InstructionsQualityResult(NamedTuple):
    """Parsed instructions quality verdict and feedback."""

    quality: InstructionsQuality
    feedback: str


class ParsedCriteria(NamedTuple):
    """Parsed acceptance criteria and instructions."""

    criteria_list: list[str]
    instructions_text: str


# --- Background Worker Status ---


class BGWorkerHealth(StrEnum):
    """Health status of a background worker."""

    OK = "ok"
    ERROR = "error"
    DISABLED = "disabled"


class BackgroundWorkerStatus(BaseModel):
    """Status of a single background worker."""

    model_config = ConfigDict(frozen=True)

    name: str
    label: str
    description: str = ""
    status: BGWorkerHealth = BGWorkerHealth.DISABLED
    enabled: bool = True
    last_run: str | None = None
    interval_seconds: int | None = None
    next_run: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class BackgroundWorkersResponse(BaseModel):
    """Response for GET /api/system/workers."""

    workers: list[BackgroundWorkerStatus] = Field(default_factory=list)


class MetricsResponse(BaseModel):
    """Response for GET /api/metrics."""

    lifetime: LifetimeStats = Field(default_factory=LifetimeStats)
    rates: dict[str, float] = Field(default_factory=dict)
    time_to_merge: dict[str, float] = Field(default_factory=dict)
    thresholds: list[ThresholdProposal] = Field(default_factory=list)
    inference_lifetime: dict[str, int] = Field(default_factory=dict)
    inference_session: dict[str, int] = Field(default_factory=dict)


class IssueHistoryLink(BaseModel):
    """A link from one issue to another, preserving relationship kind."""

    target_id: int
    kind: TaskLinkKind = TaskLinkKind.RELATES_TO
    target_url: str | None = None


class IssueHistoryPR(BaseModel):
    """A PR linked to an issue in history views."""

    number: int
    url: HttpUrl = ""
    merged: bool = False


class IssueHistoryEntry(BaseModel):
    """A single issue row for GET /api/issues/history."""

    issue_number: int
    title: str = ""
    issue_url: HttpUrl = ""
    status: str = "unknown"
    epic: str = ""
    crate_number: int | None = None
    crate_title: str = ""
    linked_issues: list[IssueHistoryLink] = Field(default_factory=list)
    prs: list[IssueHistoryPR] = Field(default_factory=list)
    session_ids: list[str] = Field(default_factory=list)
    source_calls: dict[str, int] = Field(default_factory=dict)
    model_calls: dict[str, int] = Field(default_factory=dict)
    inference: dict[str, int] = Field(default_factory=dict)
    first_seen: str | None = None
    last_seen: str | None = None
    outcome: IssueOutcome | None = None


class IssueHistoryResponse(BaseModel):
    """Response for GET /api/issues/history."""

    items: list[IssueHistoryEntry] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)
    since: str | None = None
    until: str | None = None


class MetricsSnapshot(BaseModel):
    """A single timestamped metrics snapshot for historical tracking."""

    timestamp: IsoTimestamp
    # Core counters (from LifetimeStats)
    issues_completed: int = 0
    prs_merged: int = 0
    issues_created: int = 0
    # Volume counters
    total_quality_fix_rounds: int = 0
    total_ci_fix_rounds: int = 0
    total_hitl_escalations: int = 0
    total_review_approvals: int = 0
    total_review_request_changes: int = 0
    total_reviewer_fixes: int = 0
    # Timing
    total_implementation_seconds: float = 0.0
    total_review_seconds: float = 0.0
    # Derived rates (computed at snapshot time)
    merge_rate: float = Field(default=0.0, ge=0.0)
    quality_fix_rate: float = Field(default=0.0, ge=0.0)
    hitl_escalation_rate: float = Field(default=0.0, ge=0.0)
    first_pass_approval_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_implementation_seconds: float = Field(default=0.0, ge=0.0)
    # Queue snapshot
    queue_depth: dict[str, int] = Field(default_factory=dict)
    # GitHub label counts
    github_open_by_label: dict[str, int] = Field(default_factory=dict)
    github_total_closed: int = 0
    github_total_merged: int = 0


class MetricsHistoryResponse(BaseModel):
    """Response for GET /api/metrics/history."""

    snapshots: list[MetricsSnapshot] = Field(default_factory=list)
    current: MetricsSnapshot | None = None


# --- Timeline ---


class PipelineStage(StrEnum):
    """Display pipeline stages for issue lifecycle."""

    TRIAGE = "triage"
    PLAN = "plan"
    IMPLEMENT = "implement"
    REVIEW = "review"
    MERGE = "merge"


class StageStatus(StrEnum):
    """Status of a pipeline stage."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class TimelineStage(BaseModel):
    """A single stage in an issue's lifecycle timeline."""

    stage: PipelineStage
    status: StageStatus
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    transcript_preview: list[str] = Field(default_factory=list)
    metadata: TimelineStageMetadata = Field(default_factory=dict)  # type: ignore[assignment]


class IssueTimeline(BaseModel):
    """Full lifecycle timeline for a single issue."""

    issue_number: int
    title: str = ""
    current_stage: PipelineStage | Literal[""] = ""
    stages: list[TimelineStage] = Field(default_factory=list)
    total_duration_seconds: float | None = None
    pr_number: int | None = None
    pr_url: HttpUrl = ""
    branch: str = ""


# --- Repo Audit ---


class AuditCheckStatus(StrEnum):
    """Status of a single audit check."""

    PRESENT = "present"
    MISSING = "missing"
    PARTIAL = "partial"


class AuditCheck(BaseModel):
    """Result of a single audit detection check."""

    name: str
    status: AuditCheckStatus
    detail: str = ""
    critical: bool = False


class AuditResult(BaseModel):
    """Full result of a repo audit scan."""

    repo: str
    checks: list[AuditCheck] = Field(default_factory=list)

    @property
    def missing_checks(self) -> list[AuditCheck]:
        """Return checks that are missing or partial."""
        return [
            c
            for c in self.checks
            if c.status in (AuditCheckStatus.MISSING, AuditCheckStatus.PARTIAL)
        ]

    @property
    def has_critical_gaps(self) -> bool:
        """Return True if any critical check is missing."""
        return any(
            c.critical and c.status == AuditCheckStatus.MISSING for c in self.checks
        )

    def format_report(self, color: bool = False) -> str:
        """Format the audit result as a human-readable report."""
        green = "\033[32m" if color else ""
        yellow = "\033[33m" if color else ""
        red = "\033[31m" if color else ""
        cyan = "\033[36m" if color else ""
        reset = "\033[0m" if color else ""

        lines = [
            f"{cyan}HydraFlow Repo Audit: {self.repo}{reset}",
            "=" * 40,
        ]

        status_icons = {
            AuditCheckStatus.PRESENT: f"{green}\u2713{reset}",
            AuditCheckStatus.MISSING: f"{red}\u2717{reset}",
            AuditCheckStatus.PARTIAL: f"{yellow}~{reset}",
        }

        for check in self.checks:
            icon = status_icons[check.status]
            detail = f" {check.detail}" if check.detail else ""
            lines.append(f"  {check.name + ':':<16}{icon}{detail}")

        missing = self.missing_checks
        if missing:
            names = ", ".join(c.name for c in missing)
            lines.append("")
            lines.append(f"{yellow}Missing ({len(missing)}): {names}{reset}")
            lines.append(
                f"{yellow}Run `hydraflow prep` to scaffold missing pieces.{reset}"
            )
        else:
            lines.append("")
            lines.append(
                f"{green}No gaps found. Repository is ready for HydraFlow.{reset}"
            )

        return "\n".join(lines)


# --- Callback Protocols ---
# These replace Callable[..., None] and Callable[..., Coroutine[Any, Any, ...]]
# with explicit signatures for full type-safety at call sites.


class EscalateFn(Protocol):
    """Async callback for HITL escalation.

    Matches ``ReviewPhase._escalate_to_hitl``.
    """

    async def __call__(
        self,
        issue_number: int,
        pr_number: int,
        cause: str,
        origin_label: str,
        *,
        comment: str,
        post_on_pr: bool = ...,
        event_cause: str = ...,
        extra_event_data: dict[str, object] | None = ...,
        task: Task | None = ...,
        visual_evidence: VisualEvidence | None = ...,
    ) -> None: ...


class PublishFn(Protocol):
    """Async callback for publishing review status.

    Matches ``ReviewPhase._publish_review_status``.
    """

    async def __call__(self, pr: PRInfo, worker_id: int, status: str) -> None: ...


class CiGateFn(Protocol):
    """Async callback for CI gate checks.

    Matches ``ReviewPhase.wait_and_fix_ci``.
    """

    async def __call__(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        result: ReviewResult,
        worker_id: int,
        code_scanning_alerts: list[dict] | None = None,
    ) -> bool: ...


class VisualGateFn(Protocol):
    """Async callback for visual validation gate checks.

    Matches ``ReviewPhase.check_visual_gate``.
    """

    async def __call__(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        worker_id: int,
    ) -> bool: ...


class MergeConflictFixFn(Protocol):
    """Async callback for post-merge conflict recovery attempts.

    Returns ``True`` when the conflict was resolved and branch updates were pushed.
    """

    async def __call__(
        self,
        pr: PRInfo,
        issue: Task,
        worker_id: int,
    ) -> bool: ...


class StatusCallback(Protocol):
    """Sync callback for background worker status updates.

    Matches ``HydraFlowOrchestrator.update_bg_worker_status``.
    """

    def __call__(
        self,
        name: str,
        status: str,
        details: dict[str, Any] | None = ...,
    ) -> None: ...


class WorkFn(Protocol):
    """Async zero-arg callback for polling loop work functions.

    Matches the work functions passed to ``_polling_loop``
    (e.g. ``triage_issues``, ``plan_issues``).  Uses ``object``
    return type because some work functions return values
    (e.g. ``plan_issues`` returns ``list[PlanResult]``) even
    though the return value is always discarded by the caller.
    """

    async def __call__(self) -> object: ...


# --- ADR Council Review ---


class CouncilVerdict(StrEnum):
    """Possible verdicts from an ADR review judge."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    DUPLICATE = "duplicate"


class CouncilVote(BaseModel):
    """A single judge's vote in an ADR review round."""

    role: str  # "architect" | "pragmatist" | "editor"
    verdict: CouncilVerdict
    reasoning: str = ""
    duplicate_of: int | None = None
    round_number: int = 1


class ADRCouncilResult(BaseModel):
    """Full result of a multi-round ADR council review session."""

    adr_number: int
    adr_title: str = ""
    rounds_needed: int = 1
    votes: list[CouncilVote] = Field(default_factory=list)
    all_round_votes: list[list[CouncilVote]] = Field(default_factory=list)
    final_decision: str = ""
    duplicate_detected: bool = False
    duplicate_of: int | None = None
    summary: str = ""
    minority_note: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def approve_count(self) -> int:
        return sum(1 for v in self.votes if v.verdict == CouncilVerdict.APPROVE)

    @property
    def reject_count(self) -> int:
        return sum(1 for v in self.votes if v.verdict == CouncilVerdict.REJECT)
