"""Background worker loop — run code audits and file issues for critical findings."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from agent_cli import build_agent_command
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import Credentials, HydraFlowConfig
from dedup_store import DedupStore
from runner_utils import StreamConfig, stream_claude_process

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.code_grooming_loop")

# Severities that warrant filing an issue. P0-only by policy: "high" findings
# are deliberately ignored — code is fluid, over-investing in non-critical
# cleanup crowds the factory out of work that actually ships.
_ACTIONABLE_SEVERITIES = frozenset({"critical"})


class CodeGroomingLoop(BaseBackgroundLoop):
    """Periodically runs code quality audits and files issues for critical findings.

    Invokes the Claude CLI with the ``/hf.audit-code`` skill, parses the
    output for structured findings, and files GitHub issues for any
    critical or high severity items.  Uses :class:`DedupStore` to avoid
    filing duplicate issues for the same finding.
    """

    _FINDING_RE = re.compile(
        r"\{[^{}]*\"id\"\s*:\s*\"[^\"]+\"[^{}]*\}",
        re.DOTALL,
    )

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        deps: LoopDeps,
        credentials: Credentials | None = None,
    ) -> None:
        super().__init__(worker_name="code_grooming", config=config, deps=deps)
        self._pr_manager = pr_manager
        self._credentials = credentials or Credentials()
        self._dedup = DedupStore(
            "code_grooming_findings",
            config.data_root / "memory" / "code_grooming_dedup.json",
        )

    def _get_default_interval(self) -> int:
        return self._config.code_grooming_interval

    async def _run_audit(self) -> list[dict]:
        """Run the code audit skill and return parsed findings.

        Each finding is expected to be a JSON object with at least
        ``id``, ``severity``, ``title``, and ``description`` keys.
        """
        cmd = build_agent_command(
            tool=self._config.code_grooming_tool,
            model=self._config.code_grooming_model,
            max_turns=10,
        )

        transcript = await stream_claude_process(
            cmd=cmd,
            prompt="/hf.audit-code",
            cwd=self._config.repo_root,
            active_procs=set(),
            event_bus=self._bus,
            event_data={"source": "code_grooming"},
            logger=logger,
            config=StreamConfig(gh_token=self._credentials.gh_token),
        )

        return self._parse_findings(transcript)

    @classmethod
    def _parse_findings(cls, transcript: str) -> list[dict]:
        """Extract structured finding dicts from audit transcript."""
        findings: list[dict] = []
        for match in cls._FINDING_RE.finditer(transcript):
            try:
                obj = json.loads(match.group(0))
                if isinstance(obj, dict) and "id" in obj and "severity" in obj:
                    findings.append(obj)
            except (json.JSONDecodeError, TypeError):
                continue
        return findings

    async def _do_work(self) -> dict[str, Any] | None:
        if self._config.dry_run:
            return None

        if not self._config.code_grooming_enabled:
            return {"skipped": "disabled"}

        try:
            findings = await self._run_audit()
        except Exception:
            logger.warning("Code grooming audit failed", exc_info=True)
            return {"filed": 0, "error": True}

        seen = self._dedup.get()
        filed = 0
        skipped_dedup = 0
        skipped_severity = 0

        for finding in findings:
            finding_id = finding.get("id", "")
            if not finding_id:
                continue

            if finding_id in seen:
                skipped_dedup += 1
                continue

            severity = finding.get("severity", "").lower()
            if severity not in _ACTIONABLE_SEVERITIES:
                skipped_severity += 1
                continue

            title = f"[Code Grooming] {finding.get('title', 'Code quality finding')}"
            body = (
                f"## Code Quality Finding\n\n"
                f"**ID:** {finding_id}\n"
                f"**Severity:** {severity}\n\n"
                f"### Description\n\n"
                f"{finding.get('description', 'No description available.')}\n"
            )

            await self._pr_manager.create_issue(title, body, labels=["code-quality"])
            self._dedup.add(finding_id)
            filed += 1

            logger.info(
                "Filed code grooming issue: %s (%s)",
                finding_id,
                severity,
            )

        return {
            "total_findings": len(findings),
            "filed": filed,
            "skipped_dedup": skipped_dedup,
            "skipped_severity": skipped_severity,
        }
