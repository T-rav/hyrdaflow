"""DiagramLoop (L24) — autonomous regeneration of architecture knowledge.

Per ADR-0029 (caretaker pattern), ADR-0049 (kill-switch convention),
and the architecture knowledge system spec (§4.4).

Tick behavior:
  1. Run runner.emit() against the current working tree.
  2. git status --porcelain on docs/arch/generated/ and .meta.json.
  3. If empty: log "no drift", return.
  4. Otherwise: open (or update) a single PR using auto_pr.open_automated_pr_async.
     The branch is fixed (arch-regen-auto) so re-running force-pushes and
     either creates a new PR or updates the existing one — gh handles
     idempotence at the branch level (open PR for branch already exists).
  5. Run the functional-area coverage check; if it fails, open
     a "chore(arch): unassigned functional area" issue (separate from
     the regen PR) via PRPort.find_existing_issue + create_issue.

Kill switch: HYDRAFLOW_DISABLE_DIAGRAM_LOOP=1.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import WorkCycleResult

logger = logging.getLogger(__name__)

_KILL_SWITCH_ENV = "HYDRAFLOW_DISABLE_DIAGRAM_LOOP"
_REGEN_BRANCH = "arch-regen-auto"
_PR_TITLE_PREFIX = "chore(arch): regenerate architecture knowledge"
_COVERAGE_ISSUE_TITLE = "chore(arch): unassigned functional area"


@dataclass
class _DriftResult:
    has_drift: bool
    changed_files: list[str]


class DiagramLoop(BaseBackgroundLoop):
    """L24 caretaker — keeps docs/arch/generated/ in sync with src/.

    Per ADR-0029, ADR-0049.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager,  # PRPort
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="diagram-loop",
            config=config,
            deps=deps,
        )
        self._pr_manager = pr_manager
        self._repo_root = Path.cwd()

    def _set_repo_root(self, path: Path) -> None:
        """Test seam: redirect the loop at a worktree without subclassing."""
        self._repo_root = Path(path)

    def _get_default_interval(self) -> int:
        # 4 hours; configurable via HydraFlowConfig
        return 14400

    async def _do_work(self) -> WorkCycleResult:
        # Kill-switch (ADR-0049). Belt and suspenders.
        if os.environ.get(_KILL_SWITCH_ENV) == "1":
            return {"skipped": "kill_switch"}

        drift = await asyncio.to_thread(self._regen_and_detect_drift)
        if not drift.has_drift:
            return {"drift": False}

        pr_url = await self._open_or_update_regen_pr(drift.changed_files)
        await self._ensure_coverage_issue()

        return {
            "drift": True,
            "changed_files": len(drift.changed_files),
            "pr_url": pr_url,
        }

    def _regen_and_detect_drift(self) -> _DriftResult:
        # Lazy import — avoids loading arch.* at module import time.
        from arch.runner import emit  # noqa: PLC0415

        out_dir = self._repo_root / "docs/arch/generated"
        emit(repo_root=self._repo_root, out_dir=out_dir)
        res = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "docs/arch/generated",
                "docs/arch/.meta.json",
            ],
            cwd=self._repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return _DriftResult(has_drift=False, changed_files=[])
        lines = [line for line in res.stdout.splitlines() if line.strip()]
        return _DriftResult(has_drift=bool(lines), changed_files=lines)

    async def _open_or_update_regen_pr(self, changed_files: list[str]) -> str | None:
        """Open a regen PR via auto_pr.open_automated_pr_async.

        Branch is fixed (`arch-regen-auto`); auto_pr handles the
        idempotent open-or-update behavior at the branch level.
        """
        # Lazy import to avoid a top-level dependency cycle.
        from datetime import UTC, datetime  # noqa: PLC0415

        from auto_pr import open_automated_pr_async  # noqa: PLC0415

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        pr_title = f"{_PR_TITLE_PREFIX} — {today}"
        pr_body = self._build_pr_body(changed_files)

        files_to_commit = [
            self._repo_root / "docs" / "arch" / "generated",
            self._repo_root / "docs" / "arch" / ".meta.json",
        ]

        result = await open_automated_pr_async(
            repo_root=self._repo_root,
            branch=_REGEN_BRANCH,
            files=files_to_commit,
            pr_title=pr_title,
            pr_body=pr_body,
            base="main",
            auto_merge=True,
            labels=["hydraflow-ready", "arch-regen"],
            raise_on_failure=False,
        )
        if result.status in {"opened", "no-diff"}:
            return result.pr_url
        logger.warning("DiagramLoop PR creation failed: %s", result.error)
        return None

    def _build_pr_body(self, changed_files: list[str]) -> str:
        lines = [
            "Auto-generated by `DiagramLoop` (L24). The architecture knowledge",
            "artifacts in `docs/arch/generated/` were re-extracted from source",
            "and the diff is included in this PR.",
            "",
            f"**Changed files** ({len(changed_files)}):",
            "",
        ]
        lines.extend(f"- `{path}`" for path in changed_files[:30])
        if len(changed_files) > 30:
            lines.append(f"- _(...and {len(changed_files) - 30} more)_")
        lines.extend(
            [
                "",
                "Per ADR-0029 caretaker pattern. Auto-merges once CI passes",
                "(arch-regen guard, quality, scenario tests).",
            ]
        )
        return "\n".join(lines)

    async def _unassigned_items(self) -> dict[str, list[str]]:
        """Return {'loops': [...], 'ports': [...]} of items in code but not in YAML."""
        from arch._functional_areas_schema import (  # noqa: PLC0415
            load_functional_areas,
        )
        from arch.extractors.loops import extract_loops  # noqa: PLC0415
        from arch.extractors.ports import extract_ports  # noqa: PLC0415

        src_dir = self._repo_root / "src"
        fakes_dir = self._repo_root / "src/mockworld/fakes"
        yaml_path = self._repo_root / "docs/arch/functional_areas.yml"

        if not yaml_path.exists():
            return {"loops": [], "ports": []}

        fa = load_functional_areas(yaml_path)
        assigned_loops: set[str] = set()
        assigned_ports: set[str] = set()
        for area in fa.areas.values():
            assigned_loops.update(area.loops)
            assigned_ports.update(area.ports)

        discovered_loops = {info.name for info in extract_loops(src_dir)}
        discovered_ports = {
            info.name for info in extract_ports(src_dir=src_dir, fakes_dir=fakes_dir)
        }
        return {
            "loops": sorted(discovered_loops - assigned_loops),
            "ports": sorted(discovered_ports - assigned_ports),
        }

    async def _ensure_coverage_issue(self) -> None:
        items = await self._unassigned_items()
        if not items["loops"] and not items["ports"]:
            return
        existing_number = await self._pr_manager.find_existing_issue(
            _COVERAGE_ISSUE_TITLE
        )
        if existing_number:
            return  # already open; let humans triage it

        body_lines = [
            "DiagramLoop detected loops or ports in `src/` that aren't assigned",
            "to a functional area in `docs/arch/functional_areas.yml`.",
            "",
        ]
        if items["loops"]:
            body_lines.append("**Unassigned loops:**\n")
            body_lines.extend(f"- `{n}`" for n in items["loops"])
            body_lines.append("")
        if items["ports"]:
            body_lines.append("**Unassigned ports:**\n")
            body_lines.extend(f"- `{n}`" for n in items["ports"])
            body_lines.append("")
        body_lines.append(
            "Fix: edit `docs/arch/functional_areas.yml` and assign each item to "
            "the appropriate area's `loops:` or `ports:` list."
        )

        await self._pr_manager.create_issue(
            title=_COVERAGE_ISSUE_TITLE,
            body="\n".join(body_lines),
            labels=["hydraflow-find", "arch-knowledge"],
        )
