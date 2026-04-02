"""Background worker loop — poll Dependabot alerts and file issues for fixable vulnerabilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.security_patch_loop")

# Severity levels ordered from most to least severe.
_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


class SecurityPatchLoop(BaseBackgroundLoop):
    """Periodically polls Dependabot alerts and files issues for fixable vulnerabilities.

    Only processes alerts at or above the configured severity threshold and
    that have a ``first_patched_version`` available.  Uses :class:`DedupStore`
    to avoid filing duplicate issues for the same alert number.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="security_patch", config=config, deps=deps)
        self._pr_manager = pr_manager
        self._dedup = DedupStore(
            "security_patch_alerts",
            config.data_root / "memory" / "security_patch_dedup.json",
        )

    def _get_default_interval(self) -> int:
        return self._config.security_patch_interval

    def _meets_severity(self, severity: str) -> bool:
        """Return True if *severity* meets or exceeds the configured threshold."""
        threshold = self._config.security_patch_severity_threshold
        alert_rank = _SEVERITY_RANK.get(severity.lower(), 99)
        threshold_rank = _SEVERITY_RANK.get(threshold.lower(), 1)
        return alert_rank <= threshold_rank

    @staticmethod
    def _is_fixable(alert: dict) -> bool:
        """Return True if the alert has a patched version with a known identifier."""
        vuln = alert.get("security_vulnerability") or {}
        patched = vuln.get("first_patched_version")
        if patched is None:
            return False
        if isinstance(patched, dict):
            return bool(patched.get("identifier"))
        return bool(patched)

    @staticmethod
    def _extract_info(alert: dict) -> tuple[str, str, str]:
        """Extract (package_name, severity, advisory_summary) from an alert."""
        vuln = alert.get("security_vulnerability") or {}
        pkg = vuln.get("package", {}).get("name", "unknown")
        severity = vuln.get("severity", "unknown")
        advisory = alert.get("security_advisory") or {}
        summary = advisory.get("summary", "Security vulnerability")
        return pkg, severity, summary

    async def _do_work(self) -> dict[str, Any] | None:
        if self._config.dry_run:
            return None

        alerts = await self._pr_manager.get_dependabot_alerts(state="open")
        seen = self._dedup.get()

        filed = 0
        skipped_dedup = 0
        skipped_unfixable = 0
        skipped_severity = 0

        for alert in alerts:
            alert_key = str(alert.get("number", ""))
            if not alert_key:
                continue

            # Skip already-processed alerts
            if alert_key in seen:
                skipped_dedup += 1
                continue

            # Skip unfixable alerts
            if not self._is_fixable(alert):
                skipped_unfixable += 1
                continue

            pkg, severity, summary = self._extract_info(alert)

            # Skip alerts below severity threshold
            if not self._meets_severity(severity):
                skipped_severity += 1
                continue

            title = f"[Security] {summary} in {pkg}"
            body = (
                f"## Dependabot Alert #{alert_key}\n\n"
                f"**Package:** {pkg}\n"
                f"**Severity:** {severity}\n"
                f"**Summary:** {summary}\n\n"
                f"A patched version is available. Please update the dependency.\n"
            )

            await self._pr_manager.create_issue(title, body, labels=["security"])
            self._dedup.add(alert_key)
            filed += 1

            logger.info(
                "Filed security issue for alert #%s: %s in %s (%s)",
                alert_key,
                summary,
                pkg,
                severity,
            )

        return {
            "total_alerts": len(alerts),
            "filed": filed,
            "skipped_dedup": skipped_dedup,
            "skipped_unfixable": skipped_unfixable,
            "skipped_severity": skipped_severity,
        }
