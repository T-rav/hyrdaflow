"""Beads task decomposition manager — wraps the ``bd`` CLI."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from subprocess_util import run_subprocess

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from task_graph import TaskGraphPhase

logger = logging.getLogger("hydraflow.beads_manager")

# Priority mapping: Task Graph phases without deps are P0 (critical), others P1.
_PRIORITY_NO_DEPS = "0"
_PRIORITY_HAS_DEPS = "1"


class BeadTask(BaseModel):
    """A single bead task tracked by the ``bd`` CLI."""

    id: str  # e.g. "beads-test-4yu"
    title: str
    status: str = "open"
    priority: int = 2
    depends_on: list[str] = Field(default_factory=list)


class BeadsManager:
    """Wraps the ``bd`` CLI for structured task decomposition.

    All methods are no-ops when ``beads_enabled`` is ``False`` in config.

    CLI reference (https://github.com/steveyegge/beads):
    - ``bd init`` — initialize project
    - ``bd create "title" -p <priority> --silent`` — create task, output ID only
    - ``bd dep add <child> <parent>`` — add dependency (blocks relationship)
    - ``bd update <id> --claim`` — claim task (assignee + in_progress)
    - ``bd close <id> --reason "message"`` — close task with reason
    - ``bd ready --json`` — list unblocked tasks as JSON
    - ``bd show <id> --json`` — show task details as JSON
    """

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._enabled = config.beads_enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def is_available(self) -> bool:
        """Check if the ``bd`` CLI is installed and accessible."""
        if not self._enabled:
            return False
        try:
            await run_subprocess("bd", "status", timeout=10.0)
            return True
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd CLI not found — beads features disabled")
            return False

    async def init(self, cwd: Path) -> bool:
        """Initialize a beads project in *cwd* (idempotent).

        Returns ``True`` on success, ``False`` on failure or when disabled.
        """
        if not self._enabled:
            return False
        try:
            await run_subprocess("bd", "init", cwd=cwd, timeout=30.0)
            return True
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd init failed in %s", cwd, exc_info=True)
            return False

    async def create_task(self, title: str, priority: str, cwd: Path) -> str | None:
        """Create a bead task, returning the bead ID or ``None``.

        Uses ``bd create "title" -p <priority> --silent`` which outputs
        only the bead ID for reliable parsing.
        """
        if not self._enabled:
            return None
        try:
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
            if bead_id:
                return bead_id
            logger.warning("bd create returned empty output")
            return None
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd create failed for %r", title, exc_info=True)
            return None

    async def add_dependency(self, child: str, parent: str, cwd: Path) -> bool:
        """Add a dependency: *child* depends on *parent* (blocks relationship).

        Returns ``True`` on success.
        """
        if not self._enabled:
            return False
        try:
            await run_subprocess(
                "bd", "dep", "add", child, parent, cwd=cwd, timeout=30.0
            )
            return True
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd dep add %s %s failed", child, parent, exc_info=True)
            return False

    async def claim(self, bead_id: str, cwd: Path) -> bool:
        """Claim a bead task (sets assignee + in_progress).

        Returns ``True`` on success.
        """
        if not self._enabled:
            return False
        try:
            await run_subprocess(
                "bd", "update", bead_id, "--claim", cwd=cwd, timeout=30.0
            )
            return True
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd update %s --claim failed", bead_id, exc_info=True)
            return False

    async def close(self, bead_id: str, reason: str, cwd: Path) -> bool:
        """Close a bead task with a reason.

        Uses ``bd close <id> --reason "message"``.
        Returns ``True`` on success.
        """
        if not self._enabled:
            return False
        try:
            await run_subprocess(
                "bd", "close", bead_id, "--reason", reason, cwd=cwd, timeout=30.0
            )
            return True
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd close %s failed", bead_id, exc_info=True)
            return False

    async def list_ready(self, cwd: Path) -> list[BeadTask]:
        """List unblocked (ready) bead tasks.

        Uses ``bd ready --json`` for reliable JSON parsing.
        Returns an empty list when disabled or on failure.
        """
        if not self._enabled:
            return []
        try:
            output = await run_subprocess(
                "bd", "ready", "--json", cwd=cwd, timeout=30.0
            )
            return self._parse_ready_json(output)
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd ready failed", exc_info=True)
            return []

    async def show(self, bead_id: str, cwd: Path) -> BeadTask | None:
        """Show full details for a bead task.

        Uses ``bd show <id> --json`` for reliable parsing.
        Returns ``None`` when disabled or on failure.
        """
        if not self._enabled:
            return None
        try:
            output = await run_subprocess(
                "bd", "show", bead_id, "--json", cwd=cwd, timeout=30.0
            )
            return self._parse_show_json(output)
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd show %s failed", bead_id, exc_info=True)
            return None

    async def create_from_phases(
        self,
        phases: list[TaskGraphPhase],
        issue_number: int,
        cwd: Path,
    ) -> dict[str, str]:
        """Create bead tasks from Task Graph phases with dependency wiring.

        Returns a mapping of ``{phase_id: bead_id}``.
        """
        if not self._enabled:
            return {}

        mapping: dict[str, str] = {}

        # Create all tasks first
        for phase in phases:
            title = f"Issue #{issue_number} — {phase.name}"
            priority = _PRIORITY_NO_DEPS if not phase.depends_on else _PRIORITY_HAS_DEPS
            bead_id = await self.create_task(title, priority, cwd)
            if bead_id:
                mapping[phase.id] = bead_id
            else:
                logger.warning(
                    "Failed to create bead for phase %s of issue #%d",
                    phase.id,
                    issue_number,
                )

        # Wire dependencies
        for phase in phases:
            child_bead = mapping.get(phase.id)
            if not child_bead:
                continue
            for dep_id in phase.depends_on:
                parent_bead = mapping.get(dep_id)
                if parent_bead:
                    await self.add_dependency(child_bead, parent_bead, cwd)
                else:
                    logger.warning(
                        "Dependency %s not found in bead mapping for phase %s",
                        dep_id,
                        phase.id,
                    )

        return mapping

    @staticmethod
    def _parse_ready_json(output: str) -> list[BeadTask]:
        """Parse ``bd ready --json`` output into :class:`BeadTask` instances."""
        try:
            data = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse bd ready JSON output")
            return []

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
        try:
            data: Any = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse bd show JSON output")
            return None

        # bd show --json may return a single object or a list with one item
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
