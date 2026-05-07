"""AdrTouchpointAuditorLoop — async caretaker replacing the deleted gate (ADR-0056).

Periodically scans recently-merged PRs and files `hydraflow-find` issues
when an Accepted/Proposed ADR's cited `src/` modules changed without the
ADR file appearing in the same diff. Bounded retry → HITL escalation
follows the `FakeCoverageAuditorLoop` pattern.

Cursor is `state.adr_audit_cursor` (ISO-8601 of the most-recently-scanned
merged-PR mergedAt). First run after deploy seeds it to "now" — pre-existing
merge history is frozen and not retroactively scanned.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from adr_drift import DriftFinding
    from adr_index import ADRIndex
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.adr_touchpoint_auditor_loop")

_MAX_ATTEMPTS = 3
_DEFAULT_PR_LIMIT = 50  # gh pr list page size per tick


class AdrTouchpointAuditorLoop(BaseBackgroundLoop):
    """ADR drift auditor (ADR-0056). Replaces the deleted touchpoint gate."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        adr_index: ADRIndex,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="adr_touchpoint_auditor",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        self._adr_index = adr_index

    def _get_default_interval(self) -> int:
        return self._config.adr_touchpoint_auditor_interval

    async def _list_recent_merged_prs(self, cursor: str) -> list[dict]:
        """Return merged PRs in the configured repo with mergedAt > cursor.

        Result entries carry: number, mergedAt, title, files (list[{path,additions,deletions}]).
        """
        cmd = [
            "gh",
            "pr",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "merged",
            "--limit",
            str(_DEFAULT_PR_LIMIT),
            "--json",
            "number,mergedAt,title,files",
        ]
        if cursor:
            cmd.extend(["--search", f"merged:>{cursor}"])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "gh pr list failed (rc=%s): %s",
                proc.returncode,
                stderr.decode(errors="replace").strip(),
            )
            return []
        try:
            payload = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            logger.warning("gh pr list returned non-JSON")
            return []
        return sorted(payload, key=lambda r: r.get("mergedAt") or "")

    @staticmethod
    def _changed_paths(pr: dict) -> list[str]:
        return [f.get("path", "") for f in pr.get("files", []) if f.get("path")]

    async def _file_drift_finding(self, finding: DriftFinding) -> int:
        adr = finding.adr
        title = (
            f"ADR drift: ADR-{adr.number:04d} cited modules changed in "
            f"PR #{finding.pr_number}"
        )
        files_block = "\n".join(f"- `{p}`" for p in finding.changed_cited_files)
        body = (
            f"## ADR drift\n\n"
            f"PR [#{finding.pr_number}](https://github.com/{self._config.repo}/pull/{finding.pr_number}) "
            f"changed `src/` modules cited by **ADR-{adr.number:04d}: {adr.title}** "
            f"(status: {adr.status}) without the ADR file being in the same diff:\n\n"
            f"{files_block}\n\n"
            f"**Repair options:**\n"
            f"1. Update `docs/adr/{adr.number:04d}-*.md` to reflect the new behavior, OR\n"
            f"2. Confirm the change is consistent with the existing ADR — close this "
            f"issue with a one-line explanation (the close comment is the audit trail).\n\n"
            f"_Filed by `adr_touchpoint_auditor` per ADR-0056._"
        )
        return await self._pr.create_issue(
            title,
            body,
            [*self._config.find_label, *self._config.adr_drift_label],
        )

    async def _file_drift_escalation(self, key: str, attempts: int) -> int:
        title = f"HITL: ADR drift {key} unresolved after {attempts}"
        body = (
            f"`adr_touchpoint_auditor` has re-filed `{key}` "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Closing this issue clears the dedup key (ADR-0056)._"
        )
        return await self._pr.create_issue(
            title,
            body,
            [
                *self._config.hitl_escalation_label,
                *self._config.adr_drift_stuck_label,
            ],
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys + attempt counters for closed drift escalations."""
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "closed",
        ]
        for label in (
            *self._config.hitl_escalation_label,
            *self._config.adr_drift_stuck_label,
        ):
            cmd.extend(["--label", label])
        cmd.extend(
            [
                "--author",
                "@me",
                "--limit",
                "100",
                "--json",
                "title",
            ]
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return
        try:
            closed = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return
        current = self._dedup.get()
        keep = set(current)
        for issue in closed:
            title = issue.get("title", "")
            for key in list(keep):
                if (
                    key.startswith("adr_touchpoint_auditor:")
                    and key.split(":", 1)[1] in title
                ):
                    keep.discard(key)
                    self._state.clear_adr_audit_attempts(key.split(":", 1)[1])
        if keep != current:
            self._dedup.set_all(keep)

    async def _do_work(self) -> WorkCycleResult:
        """Scan recently-merged PRs vs ADR citations, file drift findings."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        t0 = time.perf_counter()
        cursor = self._state.get_adr_audit_cursor()
        if not cursor:
            self._state.set_adr_audit_cursor(datetime.now(UTC).isoformat())
            return {"status": "seeded", "filed": 0, "scanned": 0}

        await self._reconcile_closed_escalations()

        prs = await self._list_recent_merged_prs(cursor)
        if not prs:
            self._emit_trace(t0, scanned=0, filed=0)
            return {"status": "ok", "scanned": 0, "filed": 0, "escalated": 0}

        from adr_drift import compute_drift  # noqa: PLC0415

        filed = 0
        escalated = 0
        dedup = self._dedup.get()
        new_cursor = cursor
        for pr in prs:
            pr_number = int(pr.get("number", 0))
            if not pr_number:
                continue
            changed = self._changed_paths(pr)
            for finding in compute_drift(self._adr_index, pr_number, changed):
                key = (
                    f"adr_touchpoint_auditor:PR-{pr_number}:"
                    f"ADR-{finding.adr.number:04d}"
                )
                if key in dedup:
                    continue
                attempt_id = key.split(":", 1)[1]
                attempts = self._state.inc_adr_audit_attempts(attempt_id)
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_drift_escalation(attempt_id, attempts)
                    escalated += 1
                else:
                    await self._file_drift_finding(finding)
                    filed += 1
                dedup.add(key)
                self._dedup.set_all(dedup)
            merged_at = pr.get("mergedAt") or ""
            new_cursor = max(new_cursor, merged_at)

        if new_cursor != cursor:
            self._state.set_adr_audit_cursor(new_cursor)

        self._emit_trace(t0, scanned=len(prs), filed=filed)
        return {
            "status": "ok",
            "scanned": len(prs),
            "filed": filed,
            "escalated": escalated,
        }

    def _emit_trace(self, t0: float, *, scanned: int, filed: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["gh", "pr", "list", "--state", "merged"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"scanned={scanned} filed={filed}",
        )
