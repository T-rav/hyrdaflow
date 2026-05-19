"""AdrTouchpointAuditorLoop — async caretaker replacing the deleted gate (ADR-0056).

Periodically scans recently-merged PRs and files `hydraflow-find` issues
when an Accepted/Proposed ADR's cited `src/` modules changed without the
ADR file appearing in the same diff. Bounded retry → HITL escalation
follows the `FakeCoverageAuditorLoop` pattern.

Cursor is `state.adr_audit_cursor` (ISO-8601 of the most-recently-scanned
merged-PR mergedAt). First run after deploy seeds it to "now" — pre-existing
merge history is frozen and not retroactively scanned.

Per-ADR rollup (#8987): findings are aggregated into **one issue per ADR**
listing all PRs that drifted it. Subsequent ticks update the body via
``PRPort.update_issue_body``. When an ADR's own file appears in a PR diff
the rollup is closed — drift is resolved by the same PR.

Migration: old per-tuple dedup keys (``adr_touchpoint_auditor:PR-N:ADR-N``)
and per-tuple attempt counters are silently ignored. They are not pruned —
the keys become dead weight in the dedup store until a future cleanup. New
keys are ``adr_touchpoint_auditor:ADR-NNNN`` (no PR component).
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


def _rollup_key(adr_number: int) -> str:
    return f"ADR-{adr_number:04d}"


def _dedup_key(adr_number: int) -> str:
    return f"adr_touchpoint_auditor:{_rollup_key(adr_number)}"


class AdrTouchpointAuditorLoop(BaseBackgroundLoop):
    """ADR drift auditor (ADR-0056). Replaces the deleted touchpoint gate.

    Files **one rollup issue per ADR** (#8987) listing all PRs that drifted
    its cited modules.
    """

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

    def _rollup_body(
        self,
        adr,
        pr_entries: list[dict],
    ) -> str:
        """Render the rollup issue body.

        ``pr_entries`` is a list of ``{number, mergedAt, changed_cited_files}``
        dicts, one per PR currently included in the rollup.
        """
        pr_entries = sorted(pr_entries, key=lambda e: int(e.get("number", 0)))
        repo = self._config.repo
        lines = [
            "## ADR drift rollup",
            "",
            f"PRs whose diff changed `src/` modules cited by "
            f"**ADR-{adr.number:04d}: {adr.title}** (status: {adr.status}) "
            f"without the ADR file being in the same diff:",
            "",
        ]
        for entry in pr_entries:
            pr_number = int(entry.get("number", 0))
            merged_at = entry.get("mergedAt") or "?"
            files = entry.get("changed_cited_files") or []
            files_str = ", ".join(f"`{p}`" for p in files) or "(no paths recorded)"
            lines.append(
                f"- PR [#{pr_number}](https://github.com/{repo}/pull/{pr_number}) "
                f"(merged {merged_at}): {files_str}"
            )
        lines.extend(
            [
                "",
                "**Repair options:**",
                f"1. Update `docs/adr/{adr.number:04d}-*.md` to reflect the new "
                "behavior (closes this rollup automatically on the next tick), OR",
                "2. Confirm the changes are consistent with the existing ADR — close "
                "this issue with a one-line explanation (the close comment is the "
                "audit trail).",
                "",
                "_Filed by `adr_touchpoint_auditor` per ADR-0056 (per-ADR rollup, #8987)._",
            ]
        )
        return "\n".join(lines)

    def _rollup_title(self, adr, pr_count: int) -> str:
        plural = "PR" if pr_count == 1 else "PRs"
        return (
            f"ADR drift: ADR-{adr.number:04d} cited modules drifted "
            f"across {pr_count} {plural}"
        )

    async def _file_drift_rollup(
        self,
        adr,
        pr_entries: list[dict],
    ) -> int:
        title = self._rollup_title(adr, len(pr_entries))
        body = self._rollup_body(adr, pr_entries)
        return await self._pr.create_issue(
            title,
            body,
            [*self._config.find_label, *self._config.adr_drift_label],
        )

    async def _update_drift_rollup(
        self,
        issue_number: int,
        adr,
        pr_entries: list[dict],
    ) -> None:
        body = self._rollup_body(adr, pr_entries)
        await self._pr.update_issue_body(issue_number, body)

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
                    attempt_id = key.split(":", 1)[1]
                    self._state.clear_adr_audit_attempts(attempt_id)
                    self._state.clear_adr_rollup(attempt_id)
        if keep != current:
            self._dedup.set_all(keep)

    def _adrs_updated_in_diff(self, changed_files: list[str]) -> set[int]:
        """Return ADR numbers whose own markdown file appears in *changed_files*."""
        updated: set[int] = set()
        for adr in self._adr_index.adrs():
            prefix = f"docs/adr/{adr.number:04d}-"
            if any(f.startswith(prefix) for f in changed_files):
                updated.add(adr.number)
        return updated

    @staticmethod
    def _contribs_to_pr_entries(
        contribs: tuple[DriftFinding, ...], pr_meta: dict[int, dict]
    ) -> list[dict]:
        entries: list[dict] = []
        for f in contribs:
            meta = pr_meta.get(f.pr_number, {})
            entries.append(
                {
                    "number": f.pr_number,
                    "mergedAt": meta.get("mergedAt", ""),
                    "changed_cited_files": list(f.changed_cited_files),
                }
            )
        return entries

    async def _do_work(self) -> WorkCycleResult:  # noqa: PLR0915
        """Scan recently-merged PRs vs ADR citations, file per-ADR drift rollups."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.adr_touchpoint_auditor_loop_enabled:
            return {"status": "config_disabled"}

        t0 = time.perf_counter()
        cursor = self._state.get_adr_audit_cursor()
        if not cursor:
            self._state.set_adr_audit_cursor(datetime.now(UTC).isoformat())
            return {"status": "seeded", "filed": 0, "scanned": 0}

        await self._reconcile_closed_escalations()

        prs = await self._list_recent_merged_prs(cursor)
        if not prs:
            self._emit_trace(t0, scanned=0, filed=0)
            return {
                "status": "ok",
                "scanned": 0,
                "filed": 0,
                "escalated": 0,
                "closed": 0,
                "updated": 0,
            }

        from adr_drift import compute_drift_by_adr  # noqa: PLC0415

        # Build (pr_number, changed_files) batch + per-PR metadata.
        pr_meta: dict[int, dict] = {}
        pr_diffs: list[tuple[int, list[str]]] = []
        adrs_resolved_this_tick: set[int] = set()
        new_cursor = cursor
        for pr in prs:
            pr_number = int(pr.get("number", 0))
            if not pr_number:
                continue
            changed = self._changed_paths(pr)
            pr_meta[pr_number] = {
                "mergedAt": pr.get("mergedAt") or "",
                "changed_files": changed,
            }
            pr_diffs.append((pr_number, changed))
            adrs_resolved_this_tick |= self._adrs_updated_in_diff(changed)
            merged_at = pr.get("mergedAt") or ""
            new_cursor = max(new_cursor, merged_at)

        rollups = compute_drift_by_adr(self._adr_index, pr_diffs)

        # Resolve rollups for ADRs that were updated in any PR diff this tick.
        closed = 0
        for adr_num in adrs_resolved_this_tick:
            rollup_key = _rollup_key(adr_num)
            existing = self._state.get_adr_rollup(rollup_key)
            if not existing:
                continue
            try:
                await self._pr.close_issue(int(existing["issue_number"]))
            except (
                RuntimeError,
                AttributeError,
            ) as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Could not close ADR rollup issue #%s: %s",
                    existing.get("issue_number"),
                    exc,
                )
            self._state.clear_adr_rollup(rollup_key)
            self._state.clear_adr_audit_attempts(rollup_key)
            current = self._dedup.get()
            if _dedup_key(adr_num) in current:
                self._dedup.set_all(current - {_dedup_key(adr_num)})
            closed += 1

        filed = 0
        updated = 0
        escalated = 0
        dedup = self._dedup.get()
        for entry in rollups:
            adr_num = entry.adr.number
            # Skip ADRs whose own file was in this tick's diffs — they were just
            # resolved above; their rollup (if any) was closed.
            if adr_num in adrs_resolved_this_tick:
                continue

            rollup_key = _rollup_key(adr_num)
            dedup_key = _dedup_key(adr_num)
            existing = self._state.get_adr_rollup(rollup_key)
            new_pr_entries = self._contribs_to_pr_entries(entry.contributors, pr_meta)
            new_pr_numbers = {int(e["number"]) for e in new_pr_entries}

            if existing:
                # Compute the set of PRs that this tick observed touching the
                # ADR's own file (and therefore "gained ADR coverage"). Any
                # tracked PR appearing in such a diff is dropped from the rollup.
                # (Rollup-wide close is handled above when *any* PR diff touches
                # the ADR file; this branch only runs for ADRs not in
                # ``adrs_resolved_this_tick``, so dropping here is a no-op in
                # practice — but kept as defense for partial-state cases.)
                gained_coverage: set[int] = set()
                for pr_num, meta in pr_meta.items():
                    if entry.adr.number in self._adrs_updated_in_diff(
                        meta["changed_files"]
                    ):
                        gained_coverage.add(pr_num)

                kept_existing = [
                    n for n in existing["pr_numbers"] if n not in gained_coverage
                ]
                merged_pr_numbers = sorted({*kept_existing, *new_pr_numbers})
                merged_entries: list[dict] = list(new_pr_entries)
                new_present = new_pr_numbers
                for n in merged_pr_numbers:
                    if n in new_present:
                        continue
                    merged_entries.append(
                        {
                            "number": n,
                            "mergedAt": "",
                            "changed_cited_files": [],
                        }
                    )
                await self._update_drift_rollup(
                    int(existing["issue_number"]), entry.adr, merged_entries
                )
                self._state.set_adr_rollup(
                    rollup_key,
                    issue_number=int(existing["issue_number"]),
                    pr_numbers=merged_pr_numbers,
                )
                updated += 1
                # Attempt-counter ticks per ADR; escalate at 3 strikes.
                attempts = self._state.inc_adr_audit_attempts(rollup_key)
                # Fire escalation exactly once at the threshold — using
                # ``==`` not ``>=`` so subsequent ticks for a still-open
                # rollup don't file a fresh HITL issue every tick.
                if attempts == _MAX_ATTEMPTS:
                    await self._file_drift_escalation(rollup_key, attempts)
                    escalated += 1
                continue

            if dedup_key in dedup:
                # Rollup state was cleared (e.g. external close) but dedup not
                # yet reconciled — skip until reconcile catches up.
                continue

            attempts = self._state.inc_adr_audit_attempts(rollup_key)
            # Same once-at-threshold guard as the existing-rollup branch
            # above. ``_reconcile_closed_escalations`` resets attempts on
            # human close so a recurrence after close can re-escalate.
            if attempts == _MAX_ATTEMPTS:
                await self._file_drift_escalation(rollup_key, attempts)
                escalated += 1
            else:
                issue_number = await self._file_drift_rollup(entry.adr, new_pr_entries)
                if issue_number:
                    self._state.set_adr_rollup(
                        rollup_key,
                        issue_number=issue_number,
                        pr_numbers=sorted(new_pr_numbers),
                    )
                filed += 1
            dedup.add(dedup_key)
            self._dedup.set_all(dedup)

        if new_cursor != cursor:
            self._state.set_adr_audit_cursor(new_cursor)

        self._emit_trace(t0, scanned=len(prs), filed=filed)
        return {
            "status": "ok",
            "scanned": len(prs),
            "filed": filed,
            "updated": updated,
            "closed": closed,
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
