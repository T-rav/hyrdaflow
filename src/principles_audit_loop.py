"""PrinciplesAuditLoop — weekly ADR-0044 drift detector + onboarding gate.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.4. Foundational caretaker — enforces principle conformance on
HydraFlow-self and every managed target repo before the other trust
subsystems take effect.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from config import HydraFlowConfig, ManagedRepo
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.principles_audit_loop")

_HYDRAFLOW_SELF = "hydraflow-self"
_STRUCTURAL_ATTEMPTS = 3
_BEHAVIORAL_ATTEMPTS = 3
_CULTURAL_ATTEMPTS = 1


class PrinciplesAuditLoop(BaseBackgroundLoop):
    """Weekly audit against ADR-0044 + onboarding trigger (spec §4.4)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="principles_audit",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager

    def _get_default_interval(self) -> int:
        return self._config.principles_audit_interval

    async def _do_work(self) -> WorkCycleResult:
        """One audit cycle: onboarding reconcile, HydraFlow-self, managed repos."""
        stats: dict[str, Any] = {
            "onboarded": 0,
            "audited": 0,
            "regressions_filed": 0,
            "escalations_filed": 0,
            "ready_flips": 0,
        }
        return stats

    async def _run_audit(self, slug: str, repo_root: Path) -> dict[str, Any]:
        """Invoke ``make audit-json`` → parsed JSON report (spec §4.4)."""
        proc = await asyncio.create_subprocess_exec(
            "make",
            "audit-json",
            f"DIR={repo_root}",
            cwd=self._config.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode not in (0, 1):  # audit uses 1 for "failures present"
            logger.warning(
                "make audit-json exit=%d for %s: %s",
                proc.returncode,
                slug,
                stderr.decode(errors="replace")[:400],
            )
        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"audit-json emitted non-JSON for {slug}: {exc}"
            ) from exc

    def _snapshot_from_report(self, report: dict[str, Any]) -> dict[str, str]:
        """Collapse a full audit report down to ``{check_id: status}``."""
        return {f["check_id"]: f["status"] for f in report.get("findings", [])}

    def _save_snapshot(self, slug: str, report: dict[str, Any]) -> Path:
        """Persist the full report to ``<data_root>/<slug>/audit/<YYYY-MM-DD>.json``."""
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        out = self._config.data_root / slug / "audit" / f"{date}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        return out

    async def _audit_hydraflow_self(self) -> dict[str, str]:
        """Audit the HydraFlow working tree and persist the dated snapshot."""
        report = await self._run_audit(_HYDRAFLOW_SELF, self._config.repo_root)
        self._save_snapshot(_HYDRAFLOW_SELF, report)
        return self._snapshot_from_report(report)

    async def _run_git(self, *args: str, cwd: Path | None = None) -> tuple[int, str]:
        """Run a git subcommand; returns ``(exit_code, combined_output)``."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        return proc.returncode or 0, out.decode(errors="replace")

    async def _refresh_checkout(self, mr: ManagedRepo) -> Path:
        """Shallow-clone or fetch the managed repo. Returns the checkout root."""
        checkout = self._config.data_root / mr.slug / "audit-checkout"
        if checkout.exists():
            code, out = await self._run_git(
                "fetch", "--depth", "1", "origin", mr.main_branch, cwd=checkout
            )
            if code != 0:
                raise RuntimeError(f"git fetch failed for {mr.slug}: {out[:400]}")
            await self._run_git(
                "reset", "--hard", f"origin/{mr.main_branch}", cwd=checkout
            )
        else:
            checkout.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://github.com/{mr.slug}.git"
            code, out = await self._run_git(
                "clone",
                "--depth",
                "1",
                "--branch",
                mr.main_branch,
                url,
                str(checkout),
            )
            if code != 0:
                raise RuntimeError(f"git clone failed for {mr.slug}: {out[:400]}")
        return checkout

    async def _audit_managed_repo(self, mr: ManagedRepo) -> dict[str, str]:
        """Refresh the checkout, run the audit, save the snapshot (spec §4.4)."""
        checkout = await self._refresh_checkout(mr)
        report = await self._run_audit(mr.slug, checkout)
        self._save_snapshot(mr.slug, report)
        return self._snapshot_from_report(report)

    @staticmethod
    def _diff_regressions(
        last_green: dict[str, str], current: dict[str, str]
    ) -> list[str]:
        """Return check_ids that went PASS→FAIL vs last-green (spec §4.4)."""
        if not last_green:
            return []
        return sorted(
            cid
            for cid, prev in last_green.items()
            if prev == "PASS" and current.get(cid) == "FAIL"
        )

    async def _file_drift_issue(
        self, slug: str, finding: dict[str, Any], last_status: str
    ) -> int:
        """File a ``hydraflow-find`` + ``principles-drift`` issue for one regression."""
        check_id = finding["check_id"]
        title = f"Principles drift: {check_id} regressed in {slug}"
        body = (
            f"**Principle:** {finding['principle']}\n"
            f"**Severity:** {finding['severity']}\n"
            f"**Source:** {finding['source']}\n"
            f"**Check:** {finding['what']}\n"
            f"**Remediation:** {finding['remediation']}\n\n"
            f"**Last-green status:** {last_status}\n"
            f"**Current status:** {finding.get('status', 'FAIL')}\n"
            f"**Audit message:** {finding.get('message', '')}\n\n"
            f"Filed by PrinciplesAuditLoop (spec §4.4)."
        )
        labels = [
            "hydraflow-find",
            "principles-drift",
            f"check-{check_id}",
        ]
        return await self._pr.create_issue(title, body, labels)

    async def _maybe_escalate(self, slug: str, check_id: str, severity: str) -> bool:
        """Increment attempt counter and file hitl-escalation if threshold reached."""
        attempts = self._state.increment_drift_attempts(slug, check_id)
        threshold = (
            _CULTURAL_ATTEMPTS if severity == "CULTURAL" else _STRUCTURAL_ATTEMPTS
        )
        if attempts < threshold:
            return False
        title = f"Principles drift stuck: {check_id} in {slug}"
        body = (
            f"PrinciplesAuditLoop has filed {attempts} repair issues for "
            f"`{check_id}` in `{slug}` without a successful remediation.\n\n"
            f"Severity: {severity}. Threshold: {threshold}.\n\n"
            f"Operator action required — verify the check, the ADR-0044 row, "
            f"and branch protection / review settings if applicable. "
            f"Closing this issue clears the attempt counter (§3.2 lifecycle)."
        )
        labels = [
            "hitl-escalation",
            "principles-stuck",
            f"check-{check_id}",
        ]
        if severity == "CULTURAL":
            labels.append("cultural-check")
        await self._pr.create_issue(title, body, labels)
        return True

    async def _fire_for_slug(
        self,
        slug: str,
        regressions: list[str],
        report: dict[str, Any],
        last_green: dict[str, str],
    ) -> dict[str, int]:
        """File drift issues + escalations for every regression on this slug."""
        stats = {"filed": 0, "escalated": 0}
        findings_by_id = {f["check_id"]: f for f in report.get("findings", [])}
        for check_id in regressions:
            finding = findings_by_id.get(check_id)
            if not finding:
                continue
            last_status = last_green.get(check_id, "PASS")
            await self._file_drift_issue(slug, finding, last_status)
            stats["filed"] += 1
            if await self._maybe_escalate(slug, check_id, finding["severity"]):
                stats["escalated"] += 1
        return stats
