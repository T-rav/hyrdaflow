"""Hexagonal architecture port interfaces for HydraFlow.

Defines the formal boundaries between domain logic (phases, runners) and
infrastructure (GitHub API, git CLI, agent subprocesses).

## Port map

::

    Domain (phases)
        │
        ├─► TaskFetcher / TaskTransitioner (task_source.py — already formal)
        ├─► PRPort                          (GitHub PR / label / CI operations)
        └─► WorktreePort                   (git worktree lifecycle)

Concrete adapters:
  - PRPort      → pr_manager.PRManager
  - WorktreePort → worktree.WorktreeManager

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
from pathlib import Path
from typing import runtime_checkable

from typing_extensions import Protocol

from models import GitHubIssue, HITLItem, PRInfo, ReviewVerdict

__all__ = ["PRPort", "WorktreePort"]


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

    async def post_comment(self, task_id: int, body: str) -> None:
        """Post *body* as a comment on issue *task_id*."""
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

    async def fetch_code_scanning_alerts(self, branch: str) -> list[dict]:
        """Return open code scanning alerts for *branch*."""
        ...

    # --- Issue management ---

    async def close_issue(self, issue_number: int) -> None:
        """Close GitHub issue *issue_number*."""
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

    # --- TaskTransitioner compatibility ---
    # PRManager satisfies TaskTransitioner (post_comment, close_task,
    # transition, create_task) — those methods are defined on PRPort via the
    # shared post_comment above.  The remaining transition methods are
    # intentionally omitted here to keep PRPort focused on infrastructure
    # concerns; use TaskTransitioner from task_source for domain transitions.


@runtime_checkable
class WorktreePort(Protocol):
    """Port for git worktree lifecycle operations.

    Implemented by: ``worktree.WorktreeManager``
    """

    async def create(self, issue_number: int, branch: str) -> Path:
        """Create an isolated git worktree for *issue_number* on *branch*.

        Returns the path to the new worktree.
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
