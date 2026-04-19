"""FakeBeads — in-memory mock of BeadsManager's bd CLI surface.

Stores tasks in a dict keyed by task_id. Dependencies tracked as a
parallel adjacency dict. No subprocess spawned — scenarios exercise
the bead workflow entirely against in-memory state.

Matches BeadsManager's async API signatures exactly so phases that
accept a BeadsManager can accept FakeBeads without modification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from beads_manager import BeadTask


@dataclass
class _FakeTask:
    task_id: str
    title: str
    status: str = "open"
    priority: int = 2
    depends_on: list[str] = field(default_factory=list)


class FakeBeads:
    """In-memory BeadsManager lookalike.

    Implements the same async API surface as ``BeadsManager`` so that
    scenario tests can drive the bead workflow (create → claim → close →
    list_ready → show) without spawning a real ``bd`` process.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, _FakeTask] = {}
        self._next_id: int = 1
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Script / test-helper API
    # ------------------------------------------------------------------

    def task_ids(self) -> list[str]:
        """Return all task IDs currently tracked."""
        return list(self._tasks)

    def task_count(self) -> int:
        return len(self._tasks)

    # ------------------------------------------------------------------
    # BeadsManager public async API (mirror signatures exactly)
    # ------------------------------------------------------------------

    async def ensure_installed(self) -> None:
        """Always succeeds — no real CLI in the fake."""
        return

    async def init(self, cwd: Path) -> None:
        """Mark the fake as initialised (idempotent)."""
        _ = cwd
        self._initialized = True

    async def create_task(self, title: str, priority: str, cwd: Path) -> str:
        """Create an in-memory bead task and return its generated ID."""
        _ = cwd
        task_id = f"bd-fake-{self._next_id}"
        self._next_id += 1
        self._tasks[task_id] = _FakeTask(
            task_id=task_id,
            title=title,
            priority=int(priority),
        )
        return task_id

    async def add_dependency(self, child: str, parent: str, cwd: Path) -> None:
        """Record that *child* depends on *parent*.

        Raises ``KeyError`` if either task does not exist.
        """
        _ = cwd
        if child not in self._tasks:
            msg = f"FakeBeads: unknown task {child!r}"
            raise KeyError(msg)
        if parent not in self._tasks:
            msg = f"FakeBeads: unknown task {parent!r}"
            raise KeyError(msg)
        self._tasks[child].depends_on.append(parent)

    async def claim(self, bead_id: str, cwd: Path) -> None:
        """Set task status to ``'in_progress'`` (claimed)."""
        _ = cwd
        task = self._tasks[bead_id]
        task.status = "in_progress"

    async def close(self, bead_id: str, reason: str, cwd: Path) -> None:
        """Set task status to ``'closed'``."""
        _ = (cwd, reason)
        task = self._tasks[bead_id]
        task.status = "closed"

    async def list_ready(self, cwd: Path) -> list[BeadTask]:
        """Return tasks whose dependencies are all closed and are not yet closed."""
        _ = cwd
        ready: list[BeadTask] = []
        for task in self._tasks.values():
            if task.status == "closed":
                continue
            deps_done = all(
                self._tasks[dep].status == "closed"
                for dep in task.depends_on
                if dep in self._tasks
            )
            if deps_done:
                ready.append(self._to_bead_task(task))
        return ready

    async def show(self, bead_id: str, cwd: Path) -> BeadTask:
        """Return a :class:`BeadTask` for the requested ID.

        Raises ``KeyError`` if the task does not exist.
        """
        _ = cwd
        task = self._tasks[bead_id]
        return self._to_bead_task(task)

    async def create_from_phases(
        self,
        phases: list,  # list[TaskGraphPhase] — avoid import cycle in tests
        issue_number: int,
        cwd: Path,
    ) -> dict[str, str]:
        """Create bead tasks from Task Graph phases with dependency wiring.

        Returns ``{phase_id: bead_id}``.  Mirrors ``BeadsManager.create_from_phases``
        exactly — same two-pass algorithm (create then wire deps).
        """
        from beads_manager import _PRIORITY_HAS_DEPS, _PRIORITY_NO_DEPS  # noqa: PLC0415

        mapping: dict[str, str] = {}

        for phase in phases:
            title = f"Issue #{issue_number} — {phase.name}"
            priority = _PRIORITY_NO_DEPS if not phase.depends_on else _PRIORITY_HAS_DEPS
            bead_id = await self.create_task(title, priority, cwd)
            mapping[phase.id] = bead_id

        for phase in phases:
            child_bead = mapping[phase.id]
            for dep_id in phase.depends_on:
                parent_bead = mapping[dep_id]
                await self.add_dependency(child_bead, parent_bead, cwd)

        return mapping

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_bead_task(task: _FakeTask) -> BeadTask:
        return BeadTask(
            id=task.task_id,
            title=task.title,
            status=task.status,
            priority=task.priority,
            depends_on=list(task.depends_on),
        )
