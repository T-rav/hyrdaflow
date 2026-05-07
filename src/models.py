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
    ClassVar,  # noqa: UP035 — needed at runtime for Pydantic to exclude from fields
    Literal,
    NamedTuple,
    NotRequired,
    Protocol,
)
from uuid import uuid4

from pydantic import (
    AfterValidator,
    AliasChoices,  # noqa: F401 — used in Field(validation_alias=...)
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)
from pydantic.alias_generators import (
    to_camel,  # used at runtime in HITLItem.model_config
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

#: Return type for ``BaseBackgroundLoop._do_work()`` — an optional dict
#: of stats/details included in the ``BACKGROUND_WORKER_STATUS`` event.
WorkCycleResult = dict[str, Any] | None

# --- Enumerations for constrained fields ---


class GitHubIssueState(StrEnum):
    """Lifecycle state returned by the GitHub Issues API."""

    OPEN = "open"
    CLOSED = "closed"


class IssueType(StrEnum):
    """LLM-classified issue type from the triage stage."""

    FEATURE = "feature"
    BUG = "bug"
    EPIC = "epic"


class MergeStrategy(StrEnum):
    """Supported merge orchestration strategies for epic children."""

    INDEPENDENT = "independent"
    BUNDLED = "bundled"
    BUNDLED_HITL = "bundled_hitl"
    ORDERED = "ordered"


class EpicStatus(StrEnum):
    """Dashboard-friendly lifecycle status for epics."""

    ACTIVE = "active"
    COMPLETED = "completed"
    STALE = "stale"
    BLOCKED = "blocked"


class EpicChildState(StrEnum):
    """GitHub issue state for epic children."""

    OPEN = "open"
    CLOSED = "closed"


class EpicChildStatus(StrEnum):
    """Pipeline execution status for epic child work."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class EpicChildPRState(StrEnum):
    """Pull request state surfaced on the dashboard."""

    OPEN = "open"
    MERGED = "merged"
    DRAFT = "draft"


class CIStatus(StrEnum):
    """CI check aggregation status for epic children."""

    PASSING = "passing"
    FAILING = "failing"
    PENDING = "pending"


class ReviewStatus(StrEnum):
    """Review verdict states tracked for epic children."""

    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    PENDING = "pending"


class HITLItemStatus(StrEnum):
    """HITL queue lifecycle status values."""

    PENDING = "pending"
    PROCESSING = "processing"
    RESOLVED = "resolved"


class ControlStatus(StrEnum):
    """Operator control plane lifecycle status."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    DONE = "done"
    AUTH_FAILED = "auth_failed"
    CREDITS_PAUSED = "credits_paused"


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
    target_url: HttpUrl = ""


# Compiled patterns: (pattern, kind). Order matters — first match per target_id wins.
_LINK_PATTERNS: list[tuple[re.Pattern[str], TaskLinkKind]] = [
    (re.compile(r"\brelates?\s+to\s+#(\d+)", re.IGNORECASE), TaskLinkKind.RELATES_TO),
    (re.compile(r"\brelated:?\s+#(\d+)", re.IGNORECASE), TaskLinkKind.RELATES_TO),
    (re.compile(r"\bduplicates?\s+#(\d+)", re.IGNORECASE), TaskLinkKind.DUPLICATES),
    (re.compile(r"\bduplicate\s+of\s+#(\d+)", re.IGNORECASE), TaskLinkKind.DUPLICATES),
    (
        re.compile(r"\bsupersed(?:es?|ed|ing)\s+#(\d+)", re.IGNORECASE),
        TaskLinkKind.SUPERSEDES,
    ),
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
    ``id`` corresponds to :attr:`GitHubIssue.number` (the GitHub issue number).
    """

    id: int
    title: str
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)
    source_url: HttpUrl = ""
    created_at: IsoTimestamp = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    links: list[TaskLink] = Field(default_factory=list)
    parent_epic: int | None = None
    complexity_score: int = Field(
        default=0, ge=0, le=10, description="Complexity score from triage (0-10)"
    )


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
    state: GitHubIssueState = GitHubIssueState.OPEN
    milestone_number: int | None = None
    created_at: IsoTimestamp = ""

    @field_validator("labels", mode="before")
    @classmethod
    def _normalise_labels(cls, v: Any) -> list[str]:
        """Validate that labels are plain strings (infrastructure dicts are normalized upstream)."""
        if isinstance(v, list):
            return [str(lbl) for lbl in v]
        return v  # type: ignore[return-value]

    @field_validator("comments", mode="before")
    @classmethod
    def _normalise_comments(cls, v: Any) -> list[str]:
        """Validate that comments are plain strings (infrastructure dicts are normalized upstream)."""
        if isinstance(v, list):
            return [str(c) for c in v]
        return v  # type: ignore[return-value]

    @field_validator("state", mode="before")
    @classmethod
    def _normalise_state(cls, value: GitHubIssueState | str) -> str:
        """Allow case-insensitive GitHub API values.

        ``GitHubIssueState`` is a :class:`StrEnum`, so every incoming value is
        already a ``str`` and lowercasing is safe.
        """
        return str(value).lower()

    def to_task(self) -> Task:
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

    issue_number: int = Field(description="GitHub issue number that was triaged")
    ready: bool = Field(
        default=False, description="Whether the issue is ready for planning"
    )
    reasons: list[str] = Field(
        default_factory=list, description="Reasons for the readiness decision"
    )
    complexity_score: int = Field(
        default=0, ge=0, le=10, description="Complexity score 0-10"
    )
    issue_type: IssueType = Field(
        default=IssueType.FEATURE, description="Classified issue type"
    )
    enrichment: str = Field(
        default="", description="Additional context gathered during triage"
    )
    clarity_score: int = Field(
        default=10,
        ge=0,
        le=10,
        description="Clarity/specificity score 0-10; low values route to discovery",
    )
    needs_discovery: bool = Field(
        default=False,
        description="Whether the issue needs product discovery before planning",
    )

    @field_validator("issue_type", mode="before")
    @classmethod
    def _coerce_issue_type(cls, value: Any) -> IssueType:
        """Normalise issue type inputs and fall back to ``feature``."""
        if isinstance(value, IssueType):
            return value
        if isinstance(value, str):
            cleaned = value.strip().lower()
            for member in IssueType:
                if cleaned == member.value:
                    return member
        return IssueType.FEATURE


class EpicDecompResult(BaseModel):
    """Result of auto-decomposing a large issue into an epic."""

    should_decompose: bool = False
    epic_title: str = ""
    epic_body: str = ""
    children: list[NewIssueSpec] = Field(default_factory=list)
    reasoning: str = ""


# --- Product Discovery & Shaping ---


class ProductDirection(BaseModel):
    """A single product direction option proposed during shaping."""

    name: str = Field(description="Short name for this direction")
    approach: str = Field(description="What this direction entails")
    tradeoffs: str = Field(description="Key tradeoffs and considerations")
    effort: str = Field(description="Estimated effort level (low/medium/high)")
    risk: str = Field(description="Risk level (low/medium/high)")
    differentiator: str = Field(
        default="", description="Market differentiation strength"
    )


class DiscoverResult(BaseModel):
    """Outcome of product discovery research for a vague issue."""

    issue_number: int = Field(description="GitHub issue number")
    research_brief: str = Field(default="", description="Synthesized research findings")
    opportunities: list[str] = Field(
        default_factory=list, description="Identified opportunity areas"
    )
    competitors: list[str] = Field(
        default_factory=list, description="Key competitors analyzed"
    )
    user_needs: list[str] = Field(
        default_factory=list, description="Identified user needs/pain points"
    )


class ShapeResult(BaseModel):
    """Outcome of product shaping — proposed directions for human selection."""

    issue_number: int = Field(description="GitHub issue number")
    directions: list[ProductDirection] = Field(
        default_factory=list, description="Proposed product directions"
    )
    recommendation: str = Field(
        default="", description="Agent's recommended direction with reasoning"
    )


# --- Shape Conversation ---


class ConversationTurn(BaseModel):
    """A single turn in a shape design conversation."""

    role: Literal["agent", "human"] = Field(description="Who spoke")
    content: str = Field(description="The message content")
    timestamp: str = Field(default="", description="ISO 8601 timestamp")
    signal: str = Field(
        default="",
        description="Classified learning signal (e.g. scope_narrow, positive)",
    )
    source: str = Field(default="", description="Response source identifier")


class ShapeConversation(BaseModel):
    """Persisted state for an active shape design conversation."""

    issue_number: int = Field(description="GitHub issue number")
    turns: list[ConversationTurn] = Field(default_factory=list)
    status: Literal["exploring", "finalizing", "done", "timed_out"] = Field(
        default="exploring", description="Shape conversation lifecycle status"
    )
    started_at: IsoTimestamp = Field(default="", description="ISO 8601")
    last_activity_at: IsoTimestamp = Field(default="", description="ISO 8601")


class ShapeTurnResult(BaseModel):
    """Result of a single shape agent turn."""

    content: str = Field(default="", description="Agent's response content")
    is_final: bool = Field(
        default=False, description="Whether this is a finalization turn"
    )
    transcript: str = Field(default="", description="Full agent transcript")


# --- Planner ---


class PlannerStatus(StrEnum):
    """Lifecycle status of a planning agent."""

    QUEUED = "queued"
    PLANNING = "planning"
    VALIDATING = "validating"
    RETRYING = "retrying"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LoopResult:
    """Named result from internal agent verification/fix loops.

    Replaces the ambiguous ``tuple[bool, str]`` and ``tuple[bool, str, int]``
    return types used by ``_run_diff_sanity_loop``, ``_run_test_adequacy_loop``,
    ``_run_pre_quality_review_loop``, and ``_run_quality_fix_loop``.
    """

    passed: bool
    summary: str
    attempts: int = 0


class NewIssueSpec(BaseModel):
    """Specification for a new issue discovered during planning."""

    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)


class PlanResult(BaseModel):
    """Outcome of a planner agent run."""

    issue_number: int = Field(description="GitHub issue number that was planned")
    success: bool = Field(
        default=False, description="Whether planning succeeded (fail-safe default)"
    )
    plan: str = Field(default="", description="Full implementation plan text")
    summary: str = Field(default="", description="Short summary of the plan")
    error: str | None = Field(
        default=None, description="Error message if planning failed"
    )
    transcript: str = Field(default="", description="Raw agent transcript")
    duration_seconds: float = Field(
        default=0.0, ge=0, description="Wall-clock seconds for the planner run"
    )
    new_issues: list[NewIssueSpec] = Field(
        default_factory=list, description="Sub-issues discovered during planning"
    )
    validation_errors: list[str] = Field(
        default_factory=list, description="Plan validation errors found"
    )
    actionability_score: int = Field(
        default=0, description="Actionability score from plan validation"
    )
    actionability_rank: str = Field(
        default="unknown", description="Actionability rank label"
    )
    retry_attempted: bool = Field(
        default=False,
        description="Whether a retry was attempted after validation failure",
    )
    already_satisfied: bool = Field(
        default=False, description="Whether the issue was already resolved"
    )
    epic_number: int = Field(
        default=0, description="Parent epic issue number, 0 if standalone"
    )


class PlanFindingSeverity(StrEnum):
    """Severity scale for adversarial plan review findings (#6421)."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class PlanFinding(BaseModel):
    """A single adversarial-review finding against a plan (#6421)."""

    severity: PlanFindingSeverity = Field(description="Severity of the finding")
    dimension: str = Field(
        description=(
            "Dimension being reviewed: correctness, edge_cases, test_strategy, "
            "scope_creep, convention, security, reproduction"
        ),
    )
    description: str = Field(description="What is wrong with the plan")
    suggestion: str = Field(
        default="", description="Concrete remediation the reviewer suggests"
    )


class PlanReview(BaseModel):
    """Outcome of an adversarial plan review run (#6421).

    Produced by ``PlanReviewer`` against a ``PlanResult``. Determines
    whether the plan can advance to the implement stage or must be
    routed back to planning with feedback context.
    """

    issue_number: int = Field(description="GitHub issue number being reviewed")
    plan_version: int = Field(
        default=1, description="Version of the plan being reviewed"
    )
    success: bool = Field(
        default=False, description="Whether the review run completed cleanly"
    )
    findings: list[PlanFinding] = Field(
        default_factory=list, description="All findings, in severity order"
    )
    summary: str = Field(default="", description="Short summary of the review outcome")
    transcript: str = Field(default="", description="Raw reviewer transcript")
    duration_seconds: float = Field(
        default=0.0, ge=0, description="Wall-clock seconds for the review run"
    )
    error: str | None = Field(
        default=None, description="Error message if the review run failed"
    )

    @property
    def has_blocking_findings(self) -> bool:
        """Return True if any finding has critical OR high severity.

        Critical/high findings block the READY transition; the plan is
        routed back to planning with the findings as feedback context.
        Medium and below pass through.

        Named ``has_blocking_findings`` (not ``has_critical``) because
        it includes HIGH-severity findings — using just ``has_critical``
        would mislead readers into thinking it filters on CRITICAL only.
        """
        return any(
            f.severity in (PlanFindingSeverity.CRITICAL, PlanFindingSeverity.HIGH)
            for f in self.findings
        )

    @property
    def is_clean(self) -> bool:
        """Return True if the plan can advance — no blocking findings."""
        return self.success and not self.has_blocking_findings


# ---------------------------------------------------------------------------
# Bug reproduction (#6424)
# ---------------------------------------------------------------------------


class ReproductionOutcome(StrEnum):
    """Outcome of a triage-time bug reproduction attempt (#6424)."""

    SUCCESS = "success"  # failing test written and confirmed red
    PARTIAL = "partial"  # repro script produced but no automated test
    UNABLE = "unable"  # could not reproduce — escalate to HITL


class ReproductionResult(BaseModel):
    """Outcome of a ``BugReproducer`` run (#6424)."""

    issue_number: int = Field(description="GitHub issue number being reproduced")
    outcome: ReproductionOutcome = Field(description="Reproduction outcome")
    test_path: str = Field(
        default="",
        description=(
            "Path to a failing test that demonstrates the bug. Empty for "
            "PARTIAL/UNABLE outcomes."
        ),
    )
    repro_script: str = Field(
        default="",
        description="Manual reproduction script for PARTIAL outcomes",
    )
    failing_output: str = Field(
        default="",
        description="Stdout/stderr from the failing test (for SUCCESS)",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Reproducer confidence in the result, 0..1",
    )
    investigation: str = Field(
        default="",
        description="Investigation transcript / notes for UNABLE outcomes",
    )
    duration_seconds: float = Field(default=0.0, ge=0)
    error: str | None = Field(default=None)


class RouteBackRecord(BaseModel):
    """Record of a stage route-back transition (#6423).

    Persisted via :class:`StateTracker` so the route-back counter
    survives restart, and emitted to the issue cache as a ``route_back``
    snapshot for the audit trail.
    """

    issue_number: int
    from_stage: str = Field(description="Stage the issue was being picked up from")
    to_stage: str = Field(description="Stage the issue was routed back to")
    reason: str = Field(description="Why the route-back fired (precondition fail)")
    feedback_context: str = Field(
        default="",
        description="Feedback the upstream phase should consume on retry",
    )
    timestamp: IsoTimestamp = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# Stage preconditions and route-back (#6423)
# ---------------------------------------------------------------------------


class ResearchResult(BaseModel):
    """Outcome of a research agent run (pre-plan exploration)."""

    issue_number: int = Field(description="GitHub issue number researched")
    success: bool = Field(default=False, description="Whether research succeeded")
    research: str = Field(default="", description="Structured research context")
    transcript: str = Field(default="", description="Raw agent transcript")
    duration_seconds: float = Field(
        default=0.0, ge=0, description="Wall-clock seconds for the research run"
    )
    error: str | None = Field(
        default=None, description="Error message if research failed"
    )


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

    issue_number: int = Field(description="GitHub issue number being implemented")
    branch: str = Field(description="Git branch name for the implementation")
    workspace_path: str = Field(
        default="",
        description="Path to the workspace directory",
        validation_alias=AliasChoices("workspace_path", "worktree_path"),
    )
    success: bool = Field(
        default=False,
        description="Whether implementation succeeded (fail-safe default)",
    )
    error: str | None = Field(
        default=None, description="Error message if implementation failed"
    )
    transcript: str = Field(default="", description="Raw agent transcript")
    commits: int = Field(default=0, ge=0, description="Number of commits created")
    duration_seconds: float = Field(
        default=0.0, ge=0, description="Wall-clock seconds for the worker run"
    )
    pre_quality_review_attempts: int = Field(
        default=0, ge=0, description="Number of pre-quality review attempts"
    )
    quality_fix_attempts: int = Field(
        default=0, ge=0, description="Number of quality fix attempts"
    )
    pr_info: PRInfo | None = Field(
        default=None, description="Pull request info if a PR was created"
    )


# --- Pull Requests ---


class PRInfo(BaseModel):
    """Metadata for a created pull request."""

    number: int = Field(description="Pull request number")
    issue_number: int = Field(description="GitHub issue number this PR addresses")
    branch: str = Field(description="Git branch name for the PR")
    url: HttpUrl = Field(default="", description="URL of the pull request")
    draft: bool = Field(
        default=False, description="Whether the PR was created as a draft"
    )
    labels: list[str] = Field(
        default_factory=list,
        description=(
            "GitHub label names attached to the PR. Populated by "
            "``list_prs_by_label`` so callers (e.g. SandboxFailureFixerLoop) "
            "can apply secondary filters such as the ``no-auto-fix`` opt-out."
        ),
    )


# --- HITL ---


class HITLResult(BaseModel):
    """Outcome of an HITL correction agent run."""

    issue_number: int = Field(description="GitHub issue number being corrected")
    success: bool = Field(
        default=False,
        description="Whether the HITL correction succeeded (fail-safe default)",
    )
    error: str | None = Field(
        default=None, description="Error message if correction failed"
    )
    transcript: str = Field(default="", description="Raw agent transcript")
    duration_seconds: float = Field(
        default=0.0, ge=0, description="Wall-clock seconds for the HITL run"
    )


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


# --- HITL Escalation ---


@dataclass
class HitlEscalation:
    """Groups parameters for a HITL escalation request."""

    issue_number: int
    pr_number: int | None
    cause: str
    origin_label: str
    comment: str
    post_on_pr: bool = True
    event_cause: str = ""
    extra_event_data: dict[str, object] | None = None
    task: Task | None = None
    visual_evidence: VisualEvidence | None = None


# --- Diagnostic Self-Healing ---


class Severity(StrEnum):
    """Priority classification for diagnostic escalations."""

    P0_SECURITY = "P0"
    P1_BLOCKING = "P1"
    P2_FUNCTIONAL = "P2"
    P3_WIRING = "P3"
    P4_HOUSEKEEPING = "P4"


class AttemptRecord(BaseModel):
    """Record of a single diagnostic fix attempt."""

    attempt_number: int
    changes_made: bool
    error_summary: str
    timestamp: IsoTimestamp


class EscalationContext(BaseModel):
    """Full context captured at escalation time for the diagnostic agent."""

    cause: str
    origin_phase: str
    ci_logs: str | None = None
    review_comments: list[str] = Field(default_factory=list)
    pr_diff: str | None = None
    pr_number: int | None = None
    code_scanning_alerts: list[str] = Field(default_factory=list)
    previous_attempts: list[AttemptRecord] = Field(default_factory=list)
    agent_transcript: str | None = None


class DiagnosisResult(BaseModel):
    """Structured output from diagnostic agent Stage 1."""

    root_cause: str
    severity: Severity
    fixable: bool
    fix_plan: str
    human_guidance: str
    affected_files: list[str] = Field(default_factory=list)


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
    FIXING_REVIEW_FINDINGS = "fixing_review_findings"
    FIX_DONE = "fix_done"
    FIX_FINDINGS_DONE = "fix_findings_done"


class ReviewVerdict(StrEnum):
    """Verdict from a reviewer agent."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request-changes"
    COMMENT = "comment"


class CodeScanningAlert(BaseModel):
    """A single code scanning alert from GitHub's code-scanning API."""

    model_config = ConfigDict(frozen=True)

    number: int | None = None
    severity: str | None = None
    security_severity: str | None = None
    path: str | None = None
    start_line: int | None = None
    rule: str | None = None
    message: str | None = None


class ReviewResult(BaseModel):
    """Outcome of a reviewer agent run."""

    pr_number: int = Field(description="Pull request number that was reviewed")
    issue_number: int = Field(description="GitHub issue number the PR addresses")
    verdict: ReviewVerdict = Field(
        default=ReviewVerdict.COMMENT,
        description="Review verdict (approve, request-changes, comment)",
    )
    success: bool = Field(
        default=False,
        description="Whether the review completed successfully (fail-safe default)",
    )
    summary: str = Field(default="", description="Human-readable review summary")
    error: str | None = Field(
        default=None, description="Error message if review failed"
    )
    fixes_made: bool = Field(
        default=False, description="Whether the reviewer applied fixes to the PR"
    )
    files_changed: list[str] = Field(
        default_factory=list,
        description="Files changed by the reviewer during fix commits",
    )
    transcript: str = Field(default="", description="Raw agent transcript")
    merged: bool = Field(
        default=False, description="Whether the PR was merged after review"
    )
    ci_passed: bool | None = Field(
        default=None, description="CI outcome: None=not checked, True/False=result"
    )
    ci_fix_attempts: int = Field(
        default=0, ge=0, description="Number of CI fix attempts made"
    )
    duration_seconds: float = Field(
        default=0.0, ge=0, description="Wall-clock seconds for the review run"
    )
    commit_stat: str = Field(
        default="",
        description="Output of git diff --stat covering all reviewer commits, for audit trail",
    )
    visual_passed: bool | None = Field(
        default=None,
        description="Visual validation outcome: None=not checked, True/False=result",
    )


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

    timestamp: IsoTimestamp
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
    VERIFY_PENDING = "verify_pending"
    VERIFY_RESOLVED = "verify_resolved"


class IssueOutcome(BaseModel):
    """Structured record of how and why an issue was closed."""

    outcome: IssueOutcomeType
    reason: str
    closed_at: str
    pr_number: int | None = None
    phase: str
    verification_issue_number: int | None = None


class HookFailureRecord(BaseModel):
    """Record of a post-merge hook failure."""

    hook_name: str
    error: str
    timestamp: IsoTimestamp


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
    started_at: IsoTimestamp
    ended_at: IsoTimestamp | None = None
    issues_processed: list[int] = Field(default_factory=list)
    issues_succeeded: int = 0
    issues_failed: int = 0
    status: SessionStatus = SessionStatus.ACTIVE


class SessionCounters(BaseModel):
    """Per-session completion counts, persisted to state.json."""

    triaged: int = 0
    discovered: int = 0
    shaped: int = 0
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
    total_plan_seconds: float = 0.0
    total_triage_seconds: float = 0.0
    # Per-phase duration lists for percentile stats
    plan_durations: list[float] = Field(default_factory=list)
    implement_durations: list[float] = Field(default_factory=list)
    review_durations: list[float] = Field(default_factory=list)
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
    total_outcomes_verify_pending: int = 0
    total_outcomes_verify_resolved: int = 0
    # Threshold proposals already filed (avoid re-filing)
    fired_thresholds: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Trace mining models
# ---------------------------------------------------------------------------


class TraceSpanStats(BaseModel):
    """Aggregated span counts from a trace file."""

    total_spans: int
    total_turns: int
    total_inference_calls: int
    duration_seconds: float


class TraceTokenStats(BaseModel):
    """Token usage aggregated from inference spans."""

    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cache_hit_rate: float


class TraceToolProfile(BaseModel):
    """Tool invocation profile from a trace."""

    tool_counts: dict[str, int]
    tool_errors: dict[str, int]
    total_invocations: int


class TraceSkillProfile(BaseModel):
    """Skill and subagent invocation profile from a trace."""

    skill_counts: dict[str, int]
    subagent_counts: dict[str, int]
    total_skills: int
    total_subagents: int


class TraceSummary(BaseModel):
    """Aggregated trace data for one phase run of one issue."""

    issue_number: int
    phase: str
    harvested_at: str
    trace_ids: list[str]
    spans: TraceSpanStats
    tokens: TraceTokenStats
    tools: TraceToolProfile
    skills: TraceSkillProfile
    # New fields for in-process tracing (default for backward compatibility):
    run_id: int = 0
    subprocess_count: int = 0
    crashed: bool = False
    phase_run_started_at: str = ""
    phase_run_ended_at: str = ""


class ToolCallSpan(BaseModel):
    """One tool invocation observed during a subprocess."""

    tool_name: str
    started_at: IsoTimestamp  # ISO 8601
    duration_ms: int
    input_summary: str  # human-readable preview from _summarize_tool
    succeeded: bool
    error: str | None = None
    # Stream-level tool invocation id (Claude tool_use_id, codex function_call
    # id, pi invocationId). Used to match tool_result events back to the
    # right span when multiple tools are in flight concurrently.
    tool_use_id: str | None = None


class SkillResultRecord(BaseModel):
    """Outcome of a single skill loop run."""

    skill_name: str
    passed: bool
    attempts: int
    duration_seconds: float
    blocking: bool


class SubprocessTrace(BaseModel):
    """One subprocess trace file (`run-N/subprocess-<idx>.json`)."""

    issue_number: int
    phase: str
    source: str
    run_id: int
    subprocess_idx: int
    backend: str  # "claude" / "codex" / "pi"
    started_at: IsoTimestamp  # ISO 8601
    ended_at: str | None = None
    success: bool
    crashed: bool = False
    error: str | None = None

    tokens: TraceTokenStats
    tools: TraceToolProfile
    tool_calls: list[ToolCallSpan] = Field(default_factory=list)
    skill_results: list[SkillResultRecord] = Field(default_factory=list)
    turn_count: int = 0
    inference_count: int = 0


class HITLSummaryCacheEntry(BaseModel):
    """Cached LLM summary for a HITL issue."""

    summary: str = ""
    updated_at: IsoTimestamp | None = None


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
    merge_strategy: MergeStrategy = MergeStrategy.INDEPENDENT
    created_at: IsoTimestamp = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    last_activity: IsoTimestamp = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    closed: bool = False
    released: bool = False
    auto_decomposed: bool = False

    @property
    def total_children(self) -> int:
        """Total number of child issues."""
        return len(self.child_issues)

    @property
    def resolved_children(self) -> set[int]:
        """Children that are completed or excluded (no longer active)."""
        return set(self.completed_children) | set(self.excluded_children)

    @property
    def remaining_children(self) -> list[int]:
        """Children still active (not completed and not excluded)."""
        resolved = self.resolved_children
        return [c for c in self.child_issues if c not in resolved]

    @property
    def progress(self) -> dict[str, int]:
        """Return a summary dict of child-issue counts by category."""
        return {
            "total": self.total_children,
            "completed": len(self.completed_children),
            "failed": len(self.failed_children),
            "excluded": len(self.excluded_children),
            "approved": len(self.approved_children),
            "remaining": len(self.remaining_children),
        }

    def is_child_resolved(self, child_number: int) -> bool:
        """Return True if *child_number* is completed or excluded."""
        return child_number in self.resolved_children


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


class DependabotMergeSettings(BaseModel):
    """Configuration for the Dependabot merge auto-merge worker."""

    authors: list[str] = Field(
        default_factory=lambda: ["dependabot[bot]", "hydraflow-ul-bot"]
    )
    failure_strategy: Literal["skip", "hitl", "close"] = "skip"
    review_mode: Literal["ci_only", "llm_review"] = "ci_only"


class StaleIssueSettings(BaseModel):
    """Configuration for the stale issue cleanup worker."""

    staleness_days: int = Field(default=30, ge=7, le=365)
    excluded_labels: list[str] = Field(default_factory=list)
    dry_run: bool = False


class SecurityPatchSettings(BaseModel):
    """Configuration for the security alert auto-patch worker."""

    severity_levels: list[Literal["critical", "high", "medium", "low"]] = Field(
        default_factory=lambda: ["critical", "high"]
    )


class CIMonitorSettings(BaseModel):
    """Configuration for the CI health monitor worker."""

    branch: str = "main"
    workflows: list[str] = Field(default_factory=list)
    create_issue: bool = True


class CodeGroomingSettings(BaseModel):
    """Configuration for the code grooming worker."""

    max_issues_per_cycle: int = Field(default=5, ge=1, le=50)
    min_priority: Literal["P0", "P1", "P2", "P3"] = "P1"
    enabled_audits: list[str] = Field(
        default_factory=lambda: ["lint", "complexity", "dead_code"]
    )
    dry_run: bool = False


class StateData(BaseModel):
    """Typed schema for the JSON-backed crash-recovery state."""

    schema_version: int = 1
    processed_issues: dict[str, str] = Field(default_factory=dict)
    active_workspaces: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("active_workspaces", "active_worktrees"),
    )
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
    metrics_last_snapshot_hash: str = ""
    metrics_last_synced: str | None = None
    worker_intervals: dict[str, int] = Field(default_factory=dict)
    disabled_workers: list[str] = Field(default_factory=list)
    cost_budget_killed_workers: list[str] = Field(
        default_factory=list,
        description=(
            "Workers killed by CostBudgetWatcherLoop because daily cap was "
            "exceeded. Distinct from disabled_workers (operator-set). "
            "Preserved across restart."
        ),
    )
    interrupted_issues: dict[str, str] = Field(default_factory=dict)
    last_reviewed_shas: dict[str, str] = Field(default_factory=dict)
    pending_reports: list[PendingReport] = Field(default_factory=list)
    tracked_reports: list[TrackedReport] = Field(default_factory=list)
    issue_outcomes: dict[str, IssueOutcome] = Field(default_factory=dict)
    hook_failures: dict[str, list[HookFailureRecord]] = Field(default_factory=dict)
    epic_states: dict[str, EpicState] = Field(default_factory=dict)
    releases: dict[str, Release] = Field(default_factory=dict)
    baseline_audit: dict[str, list[BaselineAuditRecord]] = Field(default_factory=dict)
    active_crate_number: int | None = None
    bead_mappings: dict[str, dict[str, str]] = Field(default_factory=dict)
    completed_timelines: dict[str, CompletedTimeline] = Field(default_factory=dict)
    digest_hashes: dict[str, str] = Field(default_factory=dict)
    dependabot_merge_settings: DependabotMergeSettings = Field(
        default_factory=DependabotMergeSettings
    )
    dependabot_merge_processed: list[int] = Field(default_factory=list)
    shape_conversations: dict[str, ShapeConversation] = Field(default_factory=dict)
    shape_responses: dict[str, str] = Field(default_factory=dict)
    stale_issue_settings: StaleIssueSettings = Field(default_factory=StaleIssueSettings)
    stale_issue_closed: list[int] = Field(default_factory=list)
    security_patch_settings: SecurityPatchSettings = Field(
        default_factory=SecurityPatchSettings
    )
    security_patch_processed: list[str] = Field(default_factory=list)
    # Per-issue route-back counter (#6423). Keyed by str(issue_id) for
    # JSON-compat with the rest of StateData. See route_back.py and
    # state/_route_back.py.
    route_back_counts: dict[str, int] = Field(default_factory=dict)
    ci_monitor_settings: CIMonitorSettings = Field(default_factory=CIMonitorSettings)
    ci_monitor_tracked_failures: dict[str, str] = Field(default_factory=dict)
    code_grooming_settings: CodeGroomingSettings = Field(
        default_factory=CodeGroomingSettings
    )
    code_grooming_filed: list[str] = Field(default_factory=list)
    # Trust fleet — RCBudgetLoop (spec §4.8)
    rc_budget_duration_history: list[dict[str, Any]] = Field(default_factory=list)
    rc_budget_attempts: dict[str, int] = Field(default_factory=dict)
    # Trust fleet — WikiRotDetectorLoop (spec §4.9)
    wiki_rot_attempts: dict[str, int] = Field(default_factory=dict)
    # Trust fleet — ContractRefreshLoop (spec §4.2 Task 18)
    contract_refresh_attempts: dict[str, int] = Field(default_factory=dict)
    # Auto-Agent — AutoAgentPreflightLoop (spec §3.6)
    auto_agent_attempts: dict[str, int] = Field(default_factory=dict)
    auto_agent_daily_spend: dict[str, float] = Field(default_factory=dict)
    # Trust fleet — TrustFleetSanityLoop (spec §12.1)
    trust_fleet_sanity_attempts: dict[str, int] = Field(default_factory=dict)
    trust_fleet_sanity_last_run: str | None = None
    trust_fleet_sanity_last_seen_counts: dict[str, dict[str, int | str]] = Field(
        default_factory=dict,
    )
    # Trust fleet — caretaker loops (Plan 5)
    flake_counts: dict[str, int] = Field(default_factory=dict)
    # SandboxFailureFixerLoop state
    sandbox_failure_fixer_attempts: dict[str, int] = Field(default_factory=dict)
    flake_attempts: dict[str, int] = Field(default_factory=dict)
    skill_prompt_last_green: dict[str, str] = Field(default_factory=dict)
    skill_prompt_attempts: dict[str, int] = Field(default_factory=dict)
    fake_coverage_last_known: dict[str, list[str]] = Field(default_factory=dict)
    fake_coverage_attempts: dict[str, int] = Field(default_factory=dict)
    escalation_contexts: dict[str, dict[str, object]] = Field(default_factory=dict)
    diagnostic_attempts: dict[str, list[dict[str, object]]] = Field(
        default_factory=dict
    )
    diagnosis_severities: dict[str, str] = Field(default_factory=dict)
    sentry_creation_attempts: dict[str, int] = Field(default_factory=dict)
    trace_runs: dict[str, dict[str, object]] = Field(
        default_factory=lambda: {"active": {}, "next_run_id": {}}
    )
    # StagingBisectLoop state (spec §4.3 + §8). Written by StagingPromotionLoop
    # on each promotion outcome; polled + mutated by StagingBisectLoop.
    last_green_rc_sha: str = ""
    last_rc_red_sha: str = ""
    rc_cycle_id: int = 0
    auto_reverts_in_cycle: int = 0
    auto_reverts_successful: int = 0
    flake_reruns_total: int = 0
    # Per-lineage retry counter (spec §4.3 lines 645–659). lineage_id
    # is the SHA of the FIRST culprit in the chain; the counter advances
    # on every retry. The parallel ``retry_lineage_pr_chains`` maps
    # lineage_id → list[PR numbers in the lineage], so a new culprit
    # whose PR is already in an existing chain reuses that lineage.
    # Past ``max_retry_lineage_attempts``, the loop files
    # ``retry-lineage-exhausted``.
    retry_lineage_attempts: dict[str, int] = Field(default_factory=dict)
    retry_lineage_pr_chains: dict[str, list[int]] = Field(default_factory=dict)
    # PrinciplesAuditLoop state (spec §4.4).
    # Keys are repo slugs ("owner/repo"); sentinel "hydraflow-self" = working tree.
    managed_repos_onboarding_status: dict[
        str, Literal["pending", "blocked", "ready"]
    ] = Field(default_factory=dict)
    # last_green_audit[slug] maps check_id -> status string (PASS/WARN/FAIL/NA/
    # NOT_IMPLEMENTED). The loop diffs the current audit against this reference.
    last_green_audit: dict[str, dict[str, str]] = Field(default_factory=dict)
    # principles_drift_attempts[f"{slug}:{check_id}"] = attempt count.
    # STRUCTURAL/BEHAVIORAL escalate at 3; CULTURAL at 1.
    principles_drift_attempts: dict[str, int] = Field(default_factory=dict)
    # CorpusLearningLoop self-validation attempts per escape-issue number
    # (spec §4.1 v2 step 5). At 3 consecutive failures on the same escape
    # issue the loop files `hitl-escalation` + `corpus-learning-stuck`.
    corpus_learning_validation_attempts: dict[str, int] = Field(default_factory=dict)
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
    status: EpicStatus = EpicStatus.ACTIVE
    percent_complete: float = 0.0
    last_activity: str = ""
    auto_decomposed: bool = False
    merge_strategy: MergeStrategy = MergeStrategy.INDEPENDENT
    child_issues: list[int] = Field(default_factory=list)


class EpicChildInfo(BaseModel):
    """Status of a single child issue within an epic."""

    issue_number: int
    title: str = ""
    url: HttpUrl = ""
    state: EpicChildState = EpicChildState.OPEN
    stage: str = ""  # pipeline stage if active (triage/plan/implement/review/merged)
    current_stage: str = ""  # UI-facing alias of stage
    status: EpicChildStatus = EpicChildStatus.QUEUED
    is_completed: bool = False
    is_failed: bool = False
    is_excluded: bool = False
    is_approved: bool = False
    pr_number: int | None = None
    pr_url: HttpUrl = ""
    pr_state: EpicChildPRState | None = None
    branch: str = ""
    ci_status: CIStatus | None = None
    review_status: ReviewStatus | None = None
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
    url: HttpUrl = ""
    total_children: int = 0
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    merged_children: int = 0
    active_children: int = 0
    queued_children: int = 0
    approved: int = 0
    ready_to_merge: bool = False
    status: EpicStatus = EpicStatus.ACTIVE
    percent_complete: float = 0.0
    last_activity: str = ""
    created_at: IsoTimestamp = ""
    auto_decomposed: bool = False
    merge_strategy: MergeStrategy = MergeStrategy.INDEPENDENT
    children: list[EpicChildInfo] = Field(default_factory=list)
    readiness: EpicReadiness = Field(default_factory=EpicReadiness)
    release: dict[str, object] | None = None


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
    created_at: IsoTimestamp = ""
    updated_at: IsoTimestamp = ""


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
    MERGED = "merged"


class PipelineIssue(BaseModel):
    """A single issue in a pipeline stage snapshot."""

    model_config = ConfigDict(frozen=True)

    issue_number: int
    title: str = ""
    url: HttpUrl = ""
    status: PipelineIssueStatus = PipelineIssueStatus.QUEUED
    epic_number: int = 0
    is_epic_child: bool = False
    track: str = ""


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
    status: Literal["created"] = "created"


class ReportIssueRequest(BaseModel):
    """Request body for POST /api/report."""

    description: str = Field(..., min_length=1, max_length=5000)
    screenshot_base64: str = Field(default="", max_length=5_000_000)
    environment: dict[str, Any] = Field(default_factory=dict)
    reporter_id: str = ""


class ReportIssueResponse(BaseModel):
    """Response for POST /api/report."""

    issue_number: int
    title: str
    url: HttpUrl = ""
    status: Literal["created", "queued"] = "created"


class PendingReport(BaseModel):
    """A queued bug report awaiting background processing."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    description: str
    screenshot_base64: str = ""
    environment: dict[str, Any] = Field(default_factory=dict)
    created_at: IsoTimestamp = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    attempts: int = 0
    reporter_id: str = ""


class ReportHistoryEntry(BaseModel):
    """A single event in a tracked report's lifecycle timeline."""

    timestamp: IsoTimestamp = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    action: str  # e.g. "submitted", "processing", "fixed", "reopened", "cancelled"
    detail: str = ""


class TrackedReport(BaseModel):
    """A bug report with lifecycle tracking for the reporter."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    reporter_id: str
    description: str
    status: Literal[
        "queued", "in-progress", "filed", "fixed", "closed", "reopened", "failed"
    ] = "queued"
    linked_issue_url: HttpUrl = ""
    linked_pr_url: HttpUrl = ""
    progress_summary: str = ""
    created_at: IsoTimestamp = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    updated_at: IsoTimestamp = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    history: list[ReportHistoryEntry] = Field(default_factory=list)

    _VALID_TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        "queued": {"in-progress", "closed", "failed"},
        "in-progress": {"filed", "closed", "queued", "reopened", "failed"},
        "filed": {"fixed", "closed", "reopened"},
        "fixed": {"closed", "reopened"},
        "closed": {"reopened"},
        "reopened": {"in-progress", "closed"},
        # ``failed`` is a terminal-ish state for unrecoverable agent crashes
        # (#6408 / #6490).  Operators can only close or reopen from here.
        "failed": {"closed", "reopened"},
    }

    def transition(self, new_status: str, action: str, detail: str = "") -> None:
        """Transition to *new_status* with a validated state-machine guard.

        Appends a :class:`ReportHistoryEntry` and updates ``updated_at``.

        Raises :class:`ValueError` if the transition is not allowed.
        """
        allowed = self._VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            msg = f"Invalid transition: {self.status} -> {new_status}"
            raise ValueError(msg)
        self.status = new_status  # type: ignore[assignment]
        self.updated_at = datetime.now(UTC).isoformat()
        self.history.append(ReportHistoryEntry(action=action, detail=detail))


class TrackedReportUpdate(BaseModel):
    """Request body for PATCH /api/reports/<id>."""

    action: Literal["confirm_fixed", "reopen", "cancel"]
    detail: str = ""
    reporter_id: str = ""


class PRListItem(BaseModel):
    """A PR entry returned by GET /api/prs."""

    pr: int
    issue: int = 0
    branch: str = ""
    url: HttpUrl = ""
    draft: bool = False
    title: str = ""
    merged: bool = False
    author: str = ""


class HITLItem(BaseModel):
    """A HITL issue entry returned by GET /api/hitl."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    issue: int
    title: str = ""
    issue_url: HttpUrl = ""
    pr: int = 0
    pr_url: HttpUrl = ""
    branch: str = ""
    cause: str = ""  # escalation reason (populated by #113)
    status: HITLItemStatus = HITLItemStatus.PENDING
    is_memory_suggestion: bool = False
    llm_summary: str = ""  # cached, operator-focused context summary
    llm_summary_updated_at: str | None = None
    visual_evidence: VisualEvidence | None = None


class ControlStatusConfig(BaseModel):
    """Config subset returned by GET /api/control/status.

    This is an API DTO, not a domain model.  Also re-exported from
    ``route_types`` for convenience.
    """

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
    max_triagers: int = 0
    max_workers: int = 0
    max_planners: int = 0
    max_reviewers: int = 0
    max_hitl_workers: int = 0
    batch_size: int = 0
    model: str = ""
    pr_unstick_batch_size: int = 10
    workspace_base: str = ""


class ControlStatusResponse(BaseModel):
    """Response for GET /api/control/status.

    This is an API DTO, not a domain model.  Also re-exported from
    ``route_types`` for convenience.
    """

    status: ControlStatus = ControlStatus.IDLE
    credits_paused_until: str | None = None
    config: ControlStatusConfig = Field(default_factory=ControlStatusConfig)
    # True when the orchestrator is wired to Fake adapters (sandbox mode).
    # Detected by duck-typing the injected PRPort for ``_is_fake_adapter``.
    # The React UI renders MockWorldBanner when this is True so operators
    # can never confuse a sandbox tab with a production tab.
    mockworld_active: bool = False


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
    title: str


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
    source: str
    repo: str


class ErrorPayload(TypedDict, total=False):
    """Payload for ``EventType.ERROR``."""

    message: str
    source: str
    repo: str
    exception_type: str
    is_likely_bug: bool
    consecutive_failures: int


class BackgroundWorkerStatusPayload(TypedDict):
    """Payload for ``EventType.BACKGROUND_WORKER_STATUS``."""

    worker: str
    status: str
    last_run: str
    details: dict[str, object]


class OrchestratorStatusPayload(TypedDict, total=False):
    """Payload for ``EventType.ORCHESTRATOR_STATUS``."""

    status: str
    reset: bool
    credits_paused_until: str


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


class TranscriptLinePayload(TypedDict, total=False):
    """Payload for ``EventType.TRANSCRIPT_LINE``.

    Extends :class:`TranscriptEventData` with the ``line`` field added
    by ``stream_claude_process``.
    """

    issue: int
    pr: int
    epic: int
    source: str
    line: str
    repo: str


class AgentActivityPayload(TypedDict, total=False):
    """Payload for ``EventType.AGENT_ACTIVITY``.

    Parsers return partial payloads (activity_type, tool_name, summary, detail);
    the streaming function fills in issue/source from runner context.
    """

    issue: int
    source: str
    activity_type: str
    tool_name: str | None
    summary: str
    detail: str | None


class SystemAlertPayload(TypedDict, total=False):
    """Payload for ``EventType.SYSTEM_ALERT``."""

    message: str
    source: str
    repo: str
    epic_number: int
    exception_type: str
    consecutive_failures: int
    threshold: object
    hook_name: str
    issue: int
    resume_at: str


class TranscriptSummaryPayload(TypedDict, total=False):
    """Payload for ``EventType.TRANSCRIPT_SUMMARY``."""

    source_issue: int
    phase: str
    posted_as: str
    summary_issue: int
    repo: str


class VerificationJudgePayload(TypedDict, total=False):
    """Payload for ``EventType.VERIFICATION_JUDGE``."""

    issue: int
    pr: int
    all_criteria_pass: bool
    instructions_quality: str
    summary: str
    repo: str


class VisualGatePayload(TypedDict, total=False):
    """Payload for ``EventType.VISUAL_GATE``."""

    pr: int
    issue: int
    worker: int
    verdict: str
    reason: str
    runtime_seconds: float
    retries: int
    artifact_count: int
    artifacts: dict[str, str]
    screenshots: dict[str, object]
    repo: str


class BaselineUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.BASELINE_UPDATE``."""

    pr_number: int
    issue_number: int
    baseline_files: list[str]
    approved: bool
    approver: str
    rollback: bool
    reason: str
    repo: str


class EpicProgressPayload(TypedDict, total=False):
    """Payload for ``EventType.EPIC_PROGRESS``."""

    epic_number: int
    progress: dict[str, object]
    repo: str


class EpicReadyPayload(TypedDict, total=False):
    """Payload for ``EventType.EPIC_READY``."""

    epic_number: int
    readiness: dict[str, object]
    strategy: str
    progress: dict[str, object]
    repo: str


class EpicReleasingPayload(TypedDict, total=False):
    """Payload for ``EventType.EPIC_RELEASING``."""

    epic_number: int
    job_id: str
    repo: str


class EpicReleasedPayload(TypedDict, total=False):
    """Payload for ``EventType.EPIC_RELEASED``."""

    epic_number: int
    job_id: str
    status: str
    error: str
    repo: str


class EpicUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.EPIC_UPDATE``."""

    epic_number: int
    action: str
    progress: dict[str, object]
    repo: str


class CrateActivatedPayload(TypedDict, total=False):
    """Payload for ``EventType.CRATE_ACTIVATED``."""

    crate_number: int
    repo: str


class CrateCompletedPayload(TypedDict, total=False):
    """Payload for ``EventType.CRATE_COMPLETED``."""

    crate_number: int
    repo: str


class PlannerUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.PLANNER_UPDATE``."""

    issue: int
    worker: int
    status: str
    role: str


class MergeUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.MERGE_UPDATE``."""

    pr: int
    status: str
    title: str


class TriageUpdatePayload(TypedDict, total=False):
    """Payload for ``EventType.TRIAGE_UPDATE``."""

    issue: int
    worker: int
    status: str
    role: str


class GitHubIssueSummary(TypedDict):
    """Lightweight issue dict returned by ``PRPort.list_issues_by_label``."""

    number: int
    title: str
    body: str
    updated_at: str


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
    pre_quality_review_attempts: int
    duration_seconds: float
    error: str | None
    commits: int


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
    decayed_items: NotRequired[int]


class TribalMemory(BaseModel):
    """ADR-quality, durable knowledge worth remembering across years.

    Stored in Bank.TRIBAL. Each field is required and non-empty — the
    LLM judge (Task 3) will enforce semantic quality, this model
    enforces structural completeness.
    """

    principle: str = Field(min_length=10, description="The durable rule or invariant")
    rationale: str = Field(
        min_length=10,
        description="Why — historical incident, design constraint, or hard-won lesson",
    )
    failure_mode: str = Field(
        min_length=10, description="What breaks if this is ignored"
    )
    scope: str = Field(min_length=1, description="Subsystem, file glob, or 'all'")
    schema_version: int = Field(default=1)
    id: str = Field(default="")
    source: str = Field(default="")
    created_at: str = Field(default="")


class MemoryContextItem(BaseModel):
    """A single memory item surfaced to human operators."""

    bank: str
    content: str
    relevance_score: float = 0.0
    timestamp: str = ""
    context: str = ""


class MemoryContextResponse(BaseModel):
    """Response for memory context queries."""

    items: list[MemoryContextItem] = Field(default_factory=list)
    query: str = ""
    bank_filter: str | None = None


class MemoryBankInfo(BaseModel):
    """Summary info about a Hindsight memory bank."""

    id: str
    name: str
    item_count: int = 0


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
    target_url: HttpUrl | None = None


class IssueHistoryPR(BaseModel):
    """A PR linked to an issue in history views."""

    number: int
    url: HttpUrl = ""
    merged: bool = False
    title: str = ""


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
    first_seen: IsoTimestamp | None = None
    last_seen: IsoTimestamp | None = None
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
    # Per-phase duration stats (avg/p50/p90)
    plan_duration_stats: dict[str, float] = Field(default_factory=dict)
    implement_duration_stats: dict[str, float] = Field(default_factory=dict)
    review_duration_stats: dict[str, float] = Field(default_factory=dict)
    merge_duration_stats: dict[str, float] = Field(default_factory=dict)
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
    DISCOVER = "discover"
    SHAPE = "shape"
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
    started_at: IsoTimestamp | None = None
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


class CompletedTimeline(BaseModel):
    """Persisted summary of a completed issue's lifecycle timing.

    Stored in state.json so timing data survives event log rotation.
    """

    issue_number: int
    title: str = ""
    completed_at: str = ""
    total_duration_seconds: float = 0.0
    phase_durations: dict[str, float] = Field(default_factory=dict)
    pr_number: int | None = None


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

    async def __call__(self, esc: HitlEscalation) -> None: ...


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
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
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


@dataclass(slots=True)
class MergeApprovalContext:
    """Groups the 12 parameters of ``PostMergeHandler.handle_approved``.

    Replacing a flat parameter list with a typed context object makes call
    sites self-documenting and eliminates positional-argument ordering bugs.
    """

    pr: PRInfo
    issue: Task
    result: ReviewResult
    diff: str
    worker_id: int
    ci_gate_fn: CiGateFn
    escalate_fn: EscalateFn
    publish_fn: PublishFn
    code_scanning_alerts: list[CodeScanningAlert] | None = None
    visual_gate_fn: VisualGateFn | None = None
    visual_decision: VisualValidationDecision | None = None
    merge_conflict_fix_fn: MergeConflictFixFn | None = None


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
    final_decision: str = (
        ""  # uppercase: ACCEPT, REJECT, REQUEST_CHANGES, DUPLICATE, NO_CONSENSUS
    )
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


class ADRValidationIssue(BaseModel):
    """A single issue found during ADR pre-review validation."""

    field: str
    message: str
    fixable: bool = False


class ADRValidationResult(BaseModel):
    """Result of pre-review validation on an ADR."""

    adr_number: int
    adr_path: str = ""
    issues: list[ADRValidationIssue] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0

    @property
    def has_fixable_only(self) -> bool:
        return len(self.issues) > 0 and all(i.fixable for i in self.issues)
