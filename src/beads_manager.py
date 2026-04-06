"""Beads task decomposition manager — wraps the ``bd`` CLI.

Beads is always active. If ``bd`` is not installed, methods raise
``BeadsNotInstalledError`` with install instructions.

Install: ``npm install -g @beads/bd``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from subprocess_util import run_subprocess

if TYPE_CHECKING:
    from task_graph import TaskGraphPhase

logger = logging.getLogger("hydraflow.beads_manager")

# Priority mapping: Task Graph phases without deps are P0 (critical), others P1.
_PRIORITY_NO_DEPS = "0"
_PRIORITY_HAS_DEPS = "1"

_INSTALL_MSG = (
    "bd CLI is not installed. "
    "Install with: npm install -g @beads/bd  "
    "(https://github.com/steveyegge/beads)"
)


class BeadsNotInstalledError(RuntimeError):
    """Raised when the ``bd`` CLI is not found on the system."""

    def __init__(self, msg: str | None = None) -> None:
        super().__init__(msg or _INSTALL_MSG)


class BeadTask(BaseModel):
    """A single bead task tracked by the ``bd`` CLI."""

    id: str  # e.g. "beads-test-4yu"
    title: str
    status: str = "open"
    priority: int = 2
    depends_on: list[str] = Field(default_factory=list)


class BeadsManager:
    """Wraps the ``bd`` CLI for structured task decomposition.

    Always active. Raises ``BeadsNotInstalledError`` if ``bd`` is missing.

    CLI reference (https://github.com/steveyegge/beads):
    - ``bd init`` — initialize project
    - ``bd create "title" -p <priority> --silent`` — create task, output ID only
    - ``bd dep add <child> <parent>`` — add dependency (blocks relationship)
    - ``bd update <id> --claim`` — claim task (assignee + in_progress)
    - ``bd close <id> --reason "message"`` — close task with reason
    - ``bd ready --json`` — list unblocked tasks as JSON
    - ``bd show <id> --json`` — show task details as JSON
    """

    async def ensure_installed(self) -> None:
        """Ensure ``bd`` is installed, auto-installing via npm if missing.

        Uses ``bd --version`` (not ``bd status``) so the check succeeds even
        when no beads project is initialised yet — ``bd status`` requires a
        working Dolt database and will fail with a CGO/server-mode error in
        environments that lack the embedded Dolt binary.
        """
        try:
            await run_subprocess("bd", "--version", timeout=10.0)
            return
        except (FileNotFoundError, OSError, RuntimeError):
            pass

        logger.info("bd CLI not found — installing via npm install -g @beads/bd")
        try:
            await run_subprocess("npm", "install", "-g", "@beads/bd", timeout=120.0)
        except FileNotFoundError as exc:
            raise BeadsNotInstalledError(
                "npm is not installed. Install Node.js first, then run: "
                "npm install -g @beads/bd"
            ) from exc

        # Verify it worked
        try:
            await run_subprocess("bd", "--version", timeout=10.0)
            logger.info("bd CLI installed successfully")
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            raise BeadsNotInstalledError() from exc

    async def init(self, cwd: Path) -> None:
        """Initialize a beads project in *cwd* (idempotent).

        Uses ``--mode server`` to avoid the embedded Dolt CGO requirement.
        Server mode uses a Dolt SQL server backend which works in all
        environments including Docker containers built without CGO.
        """
        try:
            await run_subprocess(
                "bd", "init", "--mode", "server", cwd=cwd, timeout=30.0
            )
        except FileNotFoundError as exc:
            raise BeadsNotInstalledError() from exc

    async def create_task(self, title: str, priority: str, cwd: Path) -> str:
        """Create a bead task, returning the bead ID.

        Uses ``bd create "title" -p <priority> --silent`` which outputs
        only the bead ID for reliable parsing.

        Raises ``RuntimeError`` on failure.
        """
        output = await run_subprocess(
            "bd",
            "create",
            title,
            "-p",
            priority,
            "--silent",
            cwd=cwd,
            timeout=30.0,
        )
        bead_id = output.strip()
        if not bead_id:
            msg = f"bd create returned empty output for {title!r}"
            raise RuntimeError(msg)
        return bead_id

    async def add_dependency(self, child: str, parent: str, cwd: Path) -> None:
        """Add a dependency: *child* depends on *parent* (blocks relationship)."""
        await run_subprocess("bd", "dep", "add", child, parent, cwd=cwd, timeout=30.0)

    async def claim(self, bead_id: str, cwd: Path) -> None:
        """Claim a bead task (sets assignee + in_progress)."""
        await run_subprocess("bd", "update", bead_id, "--claim", cwd=cwd, timeout=30.0)

    async def close(self, bead_id: str, reason: str, cwd: Path) -> None:
        """Close a bead task with a reason."""
        await run_subprocess(
            "bd", "close", bead_id, "--reason", reason, cwd=cwd, timeout=30.0
        )

    async def list_ready(self, cwd: Path) -> list[BeadTask]:
        """List unblocked (ready) bead tasks.

        Uses ``bd ready --json`` for reliable JSON parsing.
        """
        output = await run_subprocess("bd", "ready", "--json", cwd=cwd, timeout=30.0)
        return self._parse_ready_json(output)

    async def show(self, bead_id: str, cwd: Path) -> BeadTask:
        """Show full details for a bead task.

        Uses ``bd show <id> --json`` for reliable parsing.
        """
        output = await run_subprocess(
            "bd", "show", bead_id, "--json", cwd=cwd, timeout=30.0
        )
        result = self._parse_show_json(output)
        if result is None:
            msg = f"bd show {bead_id} returned unparseable output"
            raise RuntimeError(msg)
        return result

    async def create_from_phases(
        self,
        phases: list[TaskGraphPhase],
        issue_number: int,
        cwd: Path,
    ) -> dict[str, str]:
        """Create bead tasks from Task Graph phases with dependency wiring.

        Returns a mapping of ``{phase_id: bead_id}``.
        Raises on any failure — no partial results.
        """
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

    @staticmethod
    def _parse_ready_json(output: str) -> list[BeadTask]:
        """Parse ``bd ready --json`` output into :class:`BeadTask` instances."""
        data = json.loads(output)

        if not isinstance(data, list):
            return []

        tasks: list[BeadTask] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            deps: list[str] = []
            for dep in item.get("dependencies", []):
                if isinstance(dep, dict) and "depends_on_id" in dep:
                    deps.append(dep["depends_on_id"])
            tasks.append(
                BeadTask(
                    id=item.get("id", ""),
                    title=item.get("title", ""),
                    status=item.get("status", "open"),
                    priority=item.get("priority", 2),
                    depends_on=deps,
                )
            )
        return tasks

    @staticmethod
    def _parse_show_json(output: str) -> BeadTask | None:
        """Parse ``bd show --json`` output into a :class:`BeadTask`."""
        data: Any = json.loads(output)

        if isinstance(data, list):
            if not data:
                return None
            data = data[0]

        if not isinstance(data, dict):
            return None

        deps: list[str] = []
        for dep in data.get("dependencies", []):
            if isinstance(dep, dict) and "depends_on_id" in dep:
                deps.append(dep["depends_on_id"])

        return BeadTask(
            id=data.get("id", ""),
            title=data.get("title", ""),
            status=data.get("status", "open"),
            priority=data.get("priority", 2),
            depends_on=deps,
        )
