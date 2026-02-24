"""Data models for HydraFlow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NamedTuple, NotRequired

from pydantic import AliasChoices, BaseModel, Field, field_validator
from typing_extensions import TypedDict

# --- Task (source-agnostic task abstraction) ---


class TaskLinkKind(StrEnum):
    """Relationship kind between two tasks."""

    RELATES_TO = "relates_to"
    DUPLICATES = "duplicates"
    SUPERSEDES = "supersedes"
    REPLIES_TO = "replies_to"


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


# --- GitHub ---


class GitHubIssue(BaseModel):
    """A GitHub issue fetched for processing."""

    number: int
    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)
    url: str = ""
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
        return Task(
            id=self.number,
            title=self.title,
            body=self.body,
            tags=list(self.labels),
            comments=list(self.comments),
            source_url=self.url,
            created_at=self.created_at,
            links=parse_task_links(self.body),
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
    retry_attempted: bool = False
    already_satisfied: bool = False


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
    url: str = ""
    draft: bool = False


# --- HITL ---


class HITLResult(BaseModel):
    """Outcome of an HITL correction agent run."""

    issue_number: int
    success: bool = False
    error: str | None = None
    transcript: str = ""
    duration_seconds: float = 0.0


# --- Reviews ---


class VerificationCriteria(BaseModel):
    """Structured acceptance criteria and verification instructions for a merged PR."""

    issue_number: int
    pr_number: int
    acceptance_criteria: str
    verification_instructions: str
    timestamp: str


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


class SessionLog(BaseModel):
    """A single orchestrator session — one per run() invocation."""

    id: str
    repo: str
    started_at: str
    ended_at: str | None = None
    issues_processed: list[int] = Field(default_factory=list)
    issues_succeeded: int = 0
    issues_failed: int = 0
    status: str = "active"


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
    # Threshold proposals already filed (avoid re-filing)
    fired_thresholds: list[str] = Field(default_factory=list)


class StateData(BaseModel):
    """Typed schema for the JSON-backed crash-recovery state."""

    processed_issues: dict[str, str] = Field(default_factory=dict)
    active_worktrees: dict[str, str] = Field(default_factory=dict)
    active_branches: dict[str, str] = Field(default_factory=dict)
    reviewed_prs: dict[str, str] = Field(default_factory=dict)
    hitl_origins: dict[str, str] = Field(default_factory=dict)
    hitl_causes: dict[str, str] = Field(default_factory=dict)
    review_attempts: dict[str, int] = Field(default_factory=dict)
    review_feedback: dict[str, str] = Field(default_factory=dict)
    worker_result_meta: dict[str, dict[str, Any]] = Field(default_factory=dict)
    verification_issues: dict[str, int] = Field(default_factory=dict)
    issue_attempts: dict[str, int] = Field(default_factory=dict)
    active_issue_numbers: list[int] = Field(default_factory=list)
    lifetime_stats: LifetimeStats = Field(default_factory=LifetimeStats)
    memory_issue_ids: list[int] = Field(default_factory=list)
    memory_digest_hash: str = ""
    memory_last_synced: str | None = None
    manifest_hash: str = ""
    manifest_last_updated: str | None = None
    metrics_issue_number: int | None = None
    metrics_last_snapshot_hash: str = ""
    metrics_last_synced: str | None = None
    worker_intervals: dict[str, int] = Field(default_factory=dict)
    interrupted_issues: dict[str, str] = Field(default_factory=dict)
    last_reviewed_shas: dict[str, str] = Field(default_factory=dict)
    last_updated: str | None = None


# --- Dashboard API Responses ---


class PipelineIssue(BaseModel):
    """A single issue in a pipeline stage snapshot."""

    issue_number: int
    title: str = ""
    url: str = ""
    status: str = "queued"  # "queued" | "active" | "hitl"


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
    url: str = ""
    status: str = "created"


class PRListItem(BaseModel):
    """A PR entry returned by GET /api/prs."""

    pr: int
    issue: int = 0
    branch: str = ""
    url: str = ""
    draft: bool = False
    title: str = ""


class HITLItem(BaseModel):
    """A HITL issue entry returned by GET /api/hitl."""

    issue: int
    title: str = ""
    issueUrl: str = ""  # camelCase to match existing frontend contract
    pr: int = 0
    prUrl: str = ""  # camelCase to match existing frontend contract
    branch: str = ""
    cause: str = ""  # escalation reason (populated by #113)
    status: str = "pending"  # pending | processing | resolved
    isMemorySuggestion: bool = False  # camelCase to match frontend contract


class ControlStatusConfig(BaseModel):
    """Config subset returned by GET /api/control/status."""

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
    max_workers: int = 0
    max_planners: int = 0
    max_reviewers: int = 0
    max_hitl_workers: int = 0
    batch_size: int = 0
    model: str = ""
    memory_auto_approve: bool = False
    pr_unstick_batch_size: int = 10


class ControlStatusResponse(BaseModel):
    """Response for GET /api/control/status."""

    status: str = "idle"
    config: ControlStatusConfig = Field(default_factory=ControlStatusConfig)


# --- TypedDicts for replacing Any annotations ---


class BackgroundWorkerState(TypedDict):
    """Internal dict shape for orchestrator ``_bg_worker_states`` entries."""

    name: str
    status: str
    last_run: str | None
    details: dict[str, Any]
    enabled: NotRequired[bool]  # added by get_bg_worker_states()


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


class MemorySyncResult(TypedDict):
    """Return shape of ``MemorySyncWorker.sync``."""

    action: str
    item_count: int
    compacted: bool
    digest_chars: int


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


class BackgroundWorkerStatus(BaseModel):
    """Status of a single background worker."""

    name: str
    label: str
    status: str = "disabled"  # ok | error | disabled
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


class MetricsSnapshot(BaseModel):
    """A single timestamped metrics snapshot for historical tracking."""

    timestamp: str
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
    merge_rate: float = 0.0
    quality_fix_rate: float = 0.0
    hitl_escalation_rate: float = 0.0
    first_pass_approval_rate: float = 0.0
    avg_implementation_seconds: float = 0.0
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


class TimelineStage(BaseModel):
    """A single stage in an issue's lifecycle timeline."""

    stage: str  # "triage", "plan", "implement", "review", "merge"
    status: str  # "pending", "in_progress", "done", "failed"
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    transcript_preview: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IssueTimeline(BaseModel):
    """Full lifecycle timeline for a single issue."""

    issue_number: int
    title: str = ""
    current_stage: str = ""
    stages: list[TimelineStage] = Field(default_factory=list)
    total_duration_seconds: float | None = None
    pr_number: int | None = None
    pr_url: str = ""
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
