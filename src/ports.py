"""Hexagonal architecture port interfaces for HydraFlow.

Defines the formal boundaries between domain logic (phases, runners) and
infrastructure (GitHub API, git CLI, agent subprocesses).

## Port map

::

    Domain (phases)
        │
        ├─► TaskFetcher / TaskTransitioner (task_source.py — already formal)
        ├─► PRPort                          (GitHub PR / label / CI operations)
        ├─► WorkspacePort                   (git workspace lifecycle)
        ├─► IssueStorePort                  (in-memory work queue operations)
        ├─► IssueFetcherPort                (GitHub issue fetching)
        └─► StateBackendPort                (state persistence backend)

Concrete adapters:
  - PRPort           → pr_manager.PRManager
  - WorkspacePort    → workspace.WorkspaceManager
  - IssueStorePort   → issue_store.IssueStore
  - IssueFetcherPort → issue_fetcher.IssueFetcher
  - StateBackendPort → dolt_backend.DoltBackend

Both concrete classes satisfy their respective protocols via structural
subtyping (typing.runtime_checkable).  No changes to the concrete classes
are required.

Usage in tests — replace concrete classes with AsyncMock / stub::

    from unittest.mock import AsyncMock
    from ports import PRPort

    prs: PRPort = AsyncMock(spec=PRPort)  # type: ignore[assignment]

IMPORTANT: All method signatures here are kept in sync with the concrete
implementations.  If a signature drifts, ``tests/test_ports.py`` will catch
it via ``inspect.signature`` comparison.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import runtime_checkable

from typing_extensions import Protocol

from models import (
    CodeScanningAlert,
    GitHubIssue,
    GitHubIssueSummary,
    HITLItem,
    LoopResult,
    PRInfo,
    ReviewVerdict,
    Task,
    TranscriptEventData,
)

__all__ = [
    "AgentPort",
    "IssueFetcherPort",
    "IssueStorePort",
    "PRPort",
    "StateBackendPort",
    "WorkspacePort",
]


@runtime_checkable
class StateBackendPort(Protocol):
    """Port for state persistence backends.

    Implemented by: ``dolt_backend.DoltBackend``

    Defines the three methods that ``StateTracker`` needs from a storage
    backend so the concrete implementation can be injected rather than
    imported at module level.
    """

    def load_state(self) -> dict[str, object] | None:
        """Load the state JSON document. Returns ``None`` if no state stored."""
        ...

    def save_state(self, data: str) -> None:
        """Save the state JSON document."""
        ...

    def commit(self, message: str = "state update") -> None:
        """Stage all changes and create a backend commit."""
        ...


@runtime_checkable
class PRPort(Protocol):
    """Port for GitHub PR, label, and CI operations.

    Implemented by: ``pr_manager.PRManager``
    Signatures are kept identical to the concrete class to enable
    structural subtype checks in ``tests/test_ports.py``.
    """

    # --- Branch / PR lifecycle ---

    async def push_branch(
        self, worktree_path: Path, branch: str, *, force: bool = False
    ) -> bool:
        """Push *branch* from *worktree_path* to origin. Force-push when ``force`` is True."""
        ...

    async def create_pr(
        self,
        issue: GitHubIssue,
        branch: str,
        *,
        draft: bool = False,
    ) -> PRInfo:
        """Create a PR for *branch* linked to *issue*.

        Matches ``pr_manager.PRManager.create_pr`` exactly.
        """
        ...

    async def merge_pr(self, pr_number: int) -> bool:
        """Attempt to merge *pr_number*. Returns True if merged."""
        ...

    async def get_pr_diff(self, pr_number: int) -> str:
        """Return the unified diff for *pr_number* as a string."""
        ...

    async def wait_for_ci(
        self,
        pr_number: int,
        timeout: int,
        poll_interval: int,
        stop_event: asyncio.Event,
    ) -> tuple[bool, str]:
        """Poll CI checks until all complete or *timeout* seconds elapse.

        Returns ``(passed, summary_message)``.
        Matches ``pr_manager.PRManager.wait_for_ci`` exactly.
        """
        ...

    # --- Label management ---

    async def add_labels(self, issue_number: int, labels: list[str]) -> None:
        """Add *labels* to *issue_number*."""
        ...

    async def remove_label(self, issue_number: int, label: str) -> None:
        """Remove *label* from *issue_number* (no-op if absent)."""
        ...

    async def swap_pipeline_labels(
        self,
        issue_number: int,
        new_label: str,
        *,
        pr_number: int | None = None,
    ) -> None:
        """Atomically replace the current pipeline label with *new_label*.

        Matches ``pr_manager.PRManager.swap_pipeline_labels`` exactly.
        """
        ...

    # --- Comments / review ---

    async def post_comment(self, issue_number: int, body: str) -> None:
        """Post *body* as a comment on issue *issue_number*."""
        ...

    async def submit_review(
        self,
        pr_number: int,
        verdict: ReviewVerdict,
        body: str,
    ) -> bool:
        """Submit a formal GitHub PR review.

        Returns True on success.
        Matches ``pr_manager.PRManager.submit_review`` exactly.
        """
        ...

    # --- CI / checks ---

    async def fetch_ci_failure_logs(self, pr_number: int) -> str:
        """Return aggregated CI failure logs for *pr_number*."""
        ...

    async def fetch_code_scanning_alerts(self, branch: str) -> list[CodeScanningAlert]:
        """Return open code scanning alerts for *branch*."""
        ...

    # --- Issue management ---

    async def close_issue(self, issue_number: int) -> None:
        """Close GitHub issue *issue_number*."""
        ...

    async def find_existing_issue(self, title: str) -> int:
        """Search for an open issue with matching title. Returns issue number or 0."""
        ...

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> int:
        """Create a new GitHub issue. Returns the new issue number (0 on failure)."""
        ...

    # --- HITL ---

    async def list_hitl_items(
        self, hitl_labels: list[str], *, concurrency: int = 10
    ) -> list[HITLItem]:
        """Return open issues carrying any of *hitl_labels*."""
        ...

    # --- Branch inspection ---

    async def find_open_pr_for_branch(
        self, branch: str, *, issue_number: int = 0
    ) -> PRInfo | None:
        """Return the open PR for *branch*, or ``None`` when absent/unreadable."""
        ...

    async def branch_has_diff_from_main(self, branch: str) -> bool:
        """Return whether *branch* has commits ahead of configured main branch."""
        ...

    @staticmethod
    def expected_pr_title(issue_number: int, issue_title: str) -> str:
        """Return the canonical PR title for an issue: ``Fixes #N: <title>``."""
        ...

    async def update_pr_title(self, pr_number: int, title: str) -> bool:
        """Update the title of an existing PR. Returns True on success."""
        ...

    # --- PR detail accessors ---

    async def get_pr_diff_names(self, pr_number: int) -> list[str]:
        """Fetch the list of files changed in *pr_number*."""
        ...

    async def get_pr_approvers(self, pr_number: int) -> list[str]:
        """Fetch the list of GitHub usernames that approved *pr_number*."""
        ...

    async def get_pr_head_sha(self, pr_number: int) -> str:
        """Fetch the HEAD commit SHA for *pr_number*. Returns empty string on failure."""
        ...

    async def get_pr_mergeable(self, pr_number: int) -> bool | None:
        """Return whether *pr_number* is mergeable. ``None`` if unknown."""
        ...

    async def post_pr_comment(self, pr_number: int, body: str) -> None:
        """Post a comment on a GitHub pull request."""
        ...

    # --- Issue detail accessors ---

    async def list_issues_by_label(self, label: str) -> list[GitHubIssueSummary]:
        """Return open issues with the given label as a list of typed dicts."""
        ...

    async def get_issue_state(self, issue_number: int) -> str:
        """Return the resolved state of a GitHub issue (``'COMPLETED'``, ``'OPEN'``, etc.)."""
        ...

    async def get_issue_updated_at(self, issue_number: int) -> str:
        """Return the updated_at timestamp for an issue as ISO string."""
        ...

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        """Update the body of a GitHub issue."""
        ...

    # --- CI / repo operations ---

    async def get_latest_ci_status(self) -> tuple[str, str]:
        """Return (conclusion, url) for the latest CI run on the main branch."""
        ...

    async def get_dependabot_alerts(self, state: str = "open") -> list[dict]:
        """Fetch Dependabot alerts for the repository."""
        ...

    async def pull_main(self) -> bool:
        """Pull latest main into the local repo."""
        ...

    # --- Asset upload ---

    async def upload_screenshot(self, png_path: Path) -> str:
        """Upload a local PNG to GitHub and return the URL. Empty string on failure."""
        ...

    # --- TaskTransitioner compatibility ---
    # PRManager satisfies both PRPort and TaskTransitioner.  Phases assign
    # ``self._transitioner: TaskTransitioner = prs`` from a PRPort-typed
    # parameter, so PRPort must include these methods for structural
    # compatibility.

    async def transition(
        self, issue_number: int, new_stage: str, *, pr_number: int | None = None
    ) -> None:
        """Move *issue_number* to *new_stage* in the pipeline."""
        ...

    async def close_task(self, issue_number: int) -> None:
        """Close a task (GitHub issue)."""
        ...

    async def create_task(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        """Create a new task (GitHub issue). Returns the new issue number."""
        ...


@runtime_checkable
class WorkspacePort(Protocol):
    """Port for git workspace lifecycle operations.

    Implemented by: ``workspace.WorkspaceManager``
    """

    async def create(self, issue_number: int, branch: str) -> Path:
        """Create an isolated workspace for *issue_number* on *branch*.

        Returns the path to the new workspace.
        """
        ...

    async def destroy(self, issue_number: int) -> None:
        """Remove the worktree for *issue_number* and clean up the branch."""
        ...

    async def destroy_all(self) -> None:
        """Remove all managed worktrees (used by ``make clean``)."""
        ...

    async def merge_main(self, worktree_path: Path, branch: str) -> bool:
        """Merge the main branch into the worktree. Returns True on success."""
        ...

    async def get_conflicting_files(self, worktree_path: Path) -> list[str]:
        """Return a list of files with merge conflicts in *worktree_path*."""
        ...

    async def reset_to_main(self, worktree_path: Path) -> None:
        """Hard-reset worktree to ``origin/main`` and clean untracked files."""
        ...

    async def post_work_cleanup(
        self, issue_number: int, *, phase: str = "implement"
    ) -> None:
        """Clean up after an issue is done (salvage uncommitted changes, destroy workspace)."""
        ...

    async def abort_merge(self, worktree_path: Path) -> None:
        """Abort an in-progress merge in *worktree_path*."""
        ...

    async def start_merge_main(self, worktree_path: Path, branch: str) -> bool:
        """Begin merging main into *branch*, leaving conflicts for manual resolution.

        Returns *True* if the merge completed cleanly, *False* if conflicts remain.
        """
        ...


@runtime_checkable
class IssueStorePort(Protocol):
    """Port for in-memory issue work-queue operations.

    Implemented by: ``issue_store.IssueStore``

    Only the methods consumed by domain code (phases, background loops,
    phase utilities) are declared here.  Orchestrator-only and dashboard-only
    methods stay on the concrete class.
    """

    # --- Queue accessors ---

    def get_triageable(self, max_count: int) -> list[Task]:
        """Return up to *max_count* issues from the find queue."""
        ...

    def get_plannable(self, max_count: int) -> list[Task]:
        """Return up to *max_count* issues from the plan queue."""
        ...

    def get_implementable(self, max_count: int) -> list[Task]:
        """Return up to *max_count* issues from the ready queue."""
        ...

    def get_reviewable(self, max_count: int) -> list[Task]:
        """Return up to *max_count* issues from the review queue."""
        ...

    # --- Transition / lifecycle ---

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        """Immediately route *task* into *next_stage* in-memory."""
        ...

    def mark_active(self, issue_number: int, stage: str) -> None:
        """Mark a task as actively being processed in *stage*."""
        ...

    def mark_complete(self, issue_number: int) -> None:
        """Mark a task as done processing; increment throughput counter."""
        ...

    def mark_merged(self, issue_number: int) -> None:
        """Record an issue as merged so it appears in the pipeline snapshot."""
        ...

    def release_in_flight(self, issue_numbers: set[int]) -> None:
        """Remove *issue_numbers* from the in-flight protection set."""
        ...

    def is_active(self, issue_number: int) -> bool:
        """Return True if the task is currently being processed."""
        ...

    # --- Enrichment ---

    async def enrich_with_comments(self, task: Task) -> Task:
        """Fetch issue comments and return an enriched copy of *task*."""
        ...


@runtime_checkable
class IssueFetcherPort(Protocol):
    """Port for GitHub issue fetching operations.

    Implemented by: ``issue_fetcher.IssueFetcher``

    Only the methods consumed by domain code (phases, background loops)
    are declared here.
    """

    async def fetch_issue_by_number(self, issue_number: int) -> GitHubIssue | None:
        """Fetch a single issue by number. Returns ``None`` on failure."""
        ...

    async def fetch_issues_by_labels(
        self,
        labels: list[str],
        limit: int,
        exclude_labels: list[str] | None = None,
        require_complete: bool = False,
    ) -> list[GitHubIssue]:
        """Fetch open issues matching *any* of *labels*, deduplicated."""
        ...


@runtime_checkable
class AgentPort(Protocol):
    """Port for agent runner operations used by infrastructure modules.

    Implemented by: ``agent.AgentRunner`` (via ``base_runner.BaseRunner``)

    Defines only the methods needed by infrastructure modules like
    ``merge_conflict_resolver`` so they can accept the agent runner via
    dependency injection without importing from the Runner layer.

    Parameter names and types are kept identical to the concrete
    implementations to satisfy structural subtype checks.
    """

    def _build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Construct the CLI command for the agent."""
        ...

    async def _execute(
        self,
        cmd: list[str],
        prompt: str,
        cwd: Path,
        event_data: TranscriptEventData,
        *,
        on_output: Callable[[str], bool] | None = None,
        telemetry_stats: Mapping[str, object] | None = None,
    ) -> str:
        """Run the agent subprocess and return the transcript."""
        ...

    async def _verify_result(self, worktree_path: Path, branch: str) -> LoopResult:
        """Verify the agent produced valid commits and quality passes."""
        ...
