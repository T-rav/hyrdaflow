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
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import trace_collector
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

# Parse `Principles drift stuck: {check_id} in {slug}` from an escalation title
# to recover the (slug, check_id) pair when reconciling closed issues.
_STUCK_TITLE_RE = re.compile(
    r"^Principles drift stuck:\s*(?P<check_id>[\w\.\-]+)\s+in\s+(?P<slug>[\w\.\-/]+)\s*$"
)


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
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        stats: dict[str, Any] = {
            "onboarded": 0,
            "audited": 0,
            "regressions_filed": 0,
            "escalations_filed": 0,
            "ready_flips": 0,
        }

        # 0) Reconcile closed escalation issues — resets drift_attempts so
        # the "closing this issue clears the counter" promise in the
        # escalation body actually holds (§3.2 lifecycle).
        await self._reconcile_closed_escalations()

        # 1) Onboarding reconcile — new or pending slugs.
        stats["onboarded"] = await self._reconcile_onboarding()

        # 2) Retry blocked — may flip to ready.
        stats["ready_flips"] = await self._retry_blocked()

        # 3) HydraFlow-self audit. Call _run_audit directly so we retain
        # the full report for diffing without a disk round-trip. Wrap in
        # a broad except — if ``make audit-json`` is unavailable (test
        # env with no Makefile, missing python deps) a bare RuntimeError
        # would kill the tick and prevent managed-repo audits from
        # running.
        try:
            self_report = await self._run_audit(_HYDRAFLOW_SELF, self._config.repo_root)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Skipping self-audit this tick — audit-json unavailable",
                exc_info=True,
            )
        else:
            self._save_snapshot(_HYDRAFLOW_SELF, self_report)
            self_snapshot = self._snapshot_from_report(self_report)
            stats["audited"] += 1
            self_last = self._state.get_last_green_audit(_HYDRAFLOW_SELF)
            self_regressions = self._diff_regressions(self_last, self_snapshot)
            if self_regressions:
                fire = await self._fire_for_slug(
                    _HYDRAFLOW_SELF, self_regressions, self_report, self_last
                )
                stats["regressions_filed"] += fire["filed"]
                stats["escalations_filed"] += fire["escalated"]
            else:
                # All green — update the last-green reference.
                self._state.set_last_green_audit(_HYDRAFLOW_SELF, self_snapshot)

        # 4) Managed-repo audits (only `ready` slugs — blocked handled above).
        # One unreachable repo must not abort the rest — log + continue.
        for mr in self._config.managed_repos:
            if not mr.enabled:
                continue
            if self._state.get_onboarding_status(mr.slug) != "ready":
                continue
            try:
                snapshot = await self._audit_managed_repo(mr)
                stats["audited"] += 1
                report = await self._fetch_last_report(mr)
                last = self._state.get_last_green_audit(mr.slug)
                regressions = self._diff_regressions(last, snapshot)
                if regressions:
                    fire = await self._fire_for_slug(mr.slug, regressions, report, last)
                    stats["regressions_filed"] += fire["filed"]
                    stats["escalations_filed"] += fire["escalated"]
                else:
                    self._state.set_last_green_audit(mr.slug, snapshot)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "PrinciplesAuditLoop: skipping %s — audit failed",
                    mr.slug,
                    exc_info=True,
                )

        # Status key for fleet dashboard / event log consistency (audit
        # pass-5 finding I1 — every other trust loop returns one).
        stats["status"] = "ok" if stats["audited"] else "noop"
        return stats

    async def _retry_blocked(self) -> int:
        """For every blocked slug, re-audit; flip to ready if P1–P5 green."""
        flipped = 0
        for mr in self._config.managed_repos:
            if not mr.enabled:
                continue
            if self._state.get_onboarding_status(mr.slug) != "blocked":
                continue
            snapshot = await self._audit_managed_repo(mr)
            report = await self._fetch_last_report(mr)
            fails = self._p1_p5_fails(report.get("findings", []))
            if not fails:
                self._state.set_onboarding_status(mr.slug, "ready")
                self._state.set_last_green_audit(mr.slug, snapshot)
                flipped += 1
        return flipped

    async def _run_audit(self, slug: str, repo_root: Path) -> dict[str, Any]:
        """Invoke ``make audit-json`` → parsed JSON report (spec §4.4)."""
        cmd = ["make", "audit-json", f"DIR={repo_root}"]
        t0 = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self._config.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        duration_ms = int((time.perf_counter() - t0) * 1000)
        exit_code = proc.returncode or 0
        stderr_text = stderr.decode(errors="replace")
        trace_collector.emit_loop_subprocess_trace(
            loop="principles_audit",
            command=cmd,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stderr_excerpt=stderr_text if stderr_text else None,
        )
        if exit_code not in (0, 1):  # audit uses 1 for "failures present"
            logger.warning(
                "make audit-json exit=%d for %s: %s",
                exit_code,
                slug,
                stderr_text[:400],
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
        cmd = ["git", *args]
        t0 = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        duration_ms = int((time.perf_counter() - t0) * 1000)
        exit_code = proc.returncode or 0
        combined = out.decode(errors="replace")
        trace_collector.emit_loop_subprocess_trace(
            loop="principles_audit",
            command=cmd,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stderr_excerpt=combined if exit_code != 0 and combined else None,
        )
        return exit_code, combined

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
        """Fire exactly one hitl-escalation when the attempt counter reaches threshold.

        Before-threshold: increment the counter, file no escalation.
        At-threshold: file escalation, counter stays at threshold.
        Past-threshold: no-op until the operator closes the escalation
        (which calls ``reset_drift_attempts`` via ``_reconcile_closed_escalations``).
        """
        threshold = (
            _CULTURAL_ATTEMPTS if severity == "CULTURAL" else _STRUCTURAL_ATTEMPTS
        )
        current = self._state.get_drift_attempts(slug, check_id)
        if current >= threshold:
            # Already escalated; wait for operator to close the issue.
            return False
        attempts = self._state.increment_drift_attempts(slug, check_id)
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
            self._config.hitl_escalation_label[0],
            self._config.principles_stuck_label[0],
            f"check-{check_id}",
        ]
        if severity == "CULTURAL":
            labels.append("cultural-check")
        await self._pr.create_issue(title, body, labels)
        return True

    async def _reconcile_closed_escalations(self) -> None:
        """Clear drift_attempts for every closed principles-stuck issue.

        The escalation body tells the operator "closing this issue clears
        the attempt counter" (§3.2 lifecycle). This method honors that
        promise: it lists closed ``principles-stuck`` issues, parses the
        (slug, check_id) pair from the title, and calls
        ``reset_drift_attempts``. Close-to-clear latency is bounded by the
        loop interval.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "issue",
                "list",
                "--repo",
                self._config.repo,
                "--state",
                "closed",
                "--label",
                self._config.principles_stuck_label[0],
                "--json",
                "title",
                "--limit",
                "100",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            if proc.returncode != 0:
                logger.debug("reconcile: gh issue list failed")
                return
            issues = json.loads(out or b"[]")
        except Exception:  # noqa: BLE001
            logger.debug("reconcile: skipped", exc_info=True)
            return
        for issue in issues:
            m = _STUCK_TITLE_RE.match(str(issue.get("title", "")))
            if m is None:
                continue
            self._state.reset_drift_attempts(m.group("slug"), m.group("check_id"))

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

    @staticmethod
    def _p1_p5_fails(findings: list[dict[str, Any]]) -> list[str]:
        """check_ids whose principle is P1–P5 and whose status is FAIL."""
        return [
            f["check_id"]
            for f in findings
            if f.get("status") == "FAIL"
            and f.get("principle") in {"P1", "P2", "P3", "P4", "P5"}
        ]

    async def _fetch_last_report(self, mr: ManagedRepo) -> dict[str, Any]:
        """Read the most recent saved report for this slug; re-audit if absent."""
        base = self._config.data_root / mr.slug / "audit"
        if not base.exists():
            checkout = await self._refresh_checkout(mr)
            return await self._run_audit(mr.slug, checkout)
        latest = max(base.glob("*.json"), default=None)
        if latest is None:
            checkout = await self._refresh_checkout(mr)
            return await self._run_audit(mr.slug, checkout)
        return json.loads(latest.read_text())

    async def _run_onboarding_audit(self, mr: ManagedRepo) -> None:
        """Audit a newly-added managed repo and set its onboarding status."""
        snapshot = await self._audit_managed_repo(mr)
        report = await self._fetch_last_report(mr)
        fails = self._p1_p5_fails(report.get("findings", []))
        if fails:
            self._state.set_onboarding_status(mr.slug, "blocked")
            await self._file_onboarding_issue(mr, fails, report)
        else:
            self._state.set_onboarding_status(mr.slug, "ready")
            self._state.set_last_green_audit(mr.slug, snapshot)

    async def _file_onboarding_issue(
        self,
        mr: ManagedRepo,
        fails: list[str],
        report: dict[str, Any],
    ) -> int:
        findings_by_id = {f["check_id"]: f for f in report.get("findings", [])}
        bullets = "\n".join(
            f"- **{cid}** ({findings_by_id[cid]['severity']}): "
            f"{findings_by_id[cid]['what']} — {findings_by_id[cid]['remediation']}"
            for cid in fails
        )
        title = f"Onboarding blocked: {mr.slug} fails P1–P5"
        body = (
            f"Managed repo `{mr.slug}` cannot enter the HydraFlow pipeline "
            f"until the following P1–P5 checks pass (spec §4.4):\n\n"
            f"{bullets}\n\n"
            f"Factory dispatch is blocked for this slug until a re-audit "
            f"reports all P1–P5 as PASS. Run `make audit DIR=<checkout>` "
            f"locally to reproduce."
        )
        return await self._pr.create_issue(
            title,
            body,
            labels=["hydraflow-find", "onboarding-blocked"],
        )

    async def _reconcile_onboarding(self) -> int:
        """For every managed_repos entry, ensure onboarding status is set."""
        count = 0
        for mr in self._config.managed_repos:
            if not mr.enabled:
                continue
            status = self._state.get_onboarding_status(mr.slug)
            if status is None:
                self._state.set_onboarding_status(mr.slug, "pending")
                await self._run_onboarding_audit(mr)
                count += 1
            elif status == "pending":
                await self._run_onboarding_audit(mr)
                count += 1
        return count
