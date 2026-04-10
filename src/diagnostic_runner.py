"""Diagnostic runner — two-stage agent for self-healing."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner

if TYPE_CHECKING:
    from models import EscalationContext

from models import DiagnosisResult, Severity

logger = logging.getLogger("hydraflow.diagnostic")


def _extract_json(text: str) -> dict | None:
    """Extract first JSON block from agent output."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    raw = match.group(1).strip() if match else text.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _build_diagnosis_prompt(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    context: EscalationContext,
) -> str:
    """Build the Stage 1 diagnosis prompt with full context."""
    sections = [
        f"# Diagnostic Analysis — Issue #{issue_number}\n",
        f"**Title:** {issue_title}\n",
        f"**Body:**\n{issue_body or '_No description provided._'}\n",
        f"**Escalation cause:** {context.cause}\n",
        f"**Origin phase:** {context.origin_phase}\n",
    ]
    if context.ci_logs:
        sections.append(f"**CI Logs:**\n```\n{context.ci_logs}\n```\n")
    if context.review_comments:
        sections.append(
            "**Review Feedback:**\n"
            + "\n".join(f"- {c}" for c in context.review_comments)
            + "\n"
        )
    if context.pr_diff:
        sections.append(f"**PR Diff:**\n```diff\n{context.pr_diff}\n```\n")
    if context.code_scanning_alerts:
        sections.append(
            "**Code Scanning Alerts:**\n"
            + "\n".join(f"- {a}" for a in context.code_scanning_alerts)
            + "\n"
        )
    if context.previous_attempts:
        lines = []
        for a in context.previous_attempts:
            lines.append(
                f"- Attempt {a.attempt_number}: "
                f"{'made changes' if a.changes_made else 'no changes'}, "
                f"error: {a.error_summary}"
            )
        sections.append("**Previous Attempts:**\n" + "\n".join(lines) + "\n")
    if context.agent_transcript:
        sections.append(
            f"**Agent Reasoning (failed attempt):**\n{context.agent_transcript[:4000]}\n"
        )
    sections.append(
        "\n## Instructions\n\n"
        "Analyze the root cause. Classify severity:\n"
        "- P0: Secrets exposure, auth bypass, data loss\n"
        "- P1: Pipeline blocked, crash loop, state corruption\n"
        "- P2: Wrong behavior, system keeps running\n"
        "- P3: Missing wiring, incomplete setup\n"
        "- P4: Housekeeping, renaming, non-urgent\n\n"
        "Respond with a JSON block:\n"
        "```json\n"
        '{"root_cause": "...", "severity": "P0-P4", "fixable": true/false, '
        '"fix_plan": "...", "human_guidance": "...", "affected_files": [...]}\n'
        "```"
    )
    return "\n".join(sections)


class DiagnosticRunner(BaseRunner):
    """Two-stage diagnostic agent: diagnose (read-only), then fix (in worktree)."""

    _log = logger

    def _build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Build the diagnostic agent command."""
        return build_agent_command(
            tool=self._config.implementation_tool,
            model=self._config.model,
        )

    async def diagnose(
        self,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        context: EscalationContext,
    ) -> DiagnosisResult:
        """Stage 1: Read-only diagnosis against repo root. Returns structured result."""
        prompt = _build_diagnosis_prompt(issue_number, issue_title, issue_body, context)
        try:
            cmd = self._build_command()
            transcript = await self._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": issue_number, "source": "diagnostic"},
            )
        except (PermissionError, KeyboardInterrupt, SystemExit, MemoryError):
            raise
        except Exception:
            logger.exception("Diagnostic agent failed for issue #%d", issue_number)
            return DiagnosisResult(
                root_cause="Diagnostic agent crashed",
                severity=Severity.P2_FUNCTIONAL,
                fixable=False,
                fix_plan="",
                human_guidance="Diagnostic agent encountered an error. Manual review required.",
            )

        parsed = _extract_json(transcript)
        if parsed is None:
            return DiagnosisResult(
                root_cause=transcript[:500] if transcript else "No output",
                severity=Severity.P2_FUNCTIONAL,
                fixable=False,
                fix_plan="",
                human_guidance="Agent did not produce structured output. Manual review required.",
            )

        try:
            return DiagnosisResult.model_validate(parsed)
        except Exception:
            logger.warning(
                "DiagnosisResult validation failed for issue #%d — using fallback",
                issue_number,
                exc_info=True,
            )
            return DiagnosisResult(
                root_cause=parsed.get(
                    "root_cause", transcript[:500] if transcript else ""
                ),
                severity=Severity.P2_FUNCTIONAL,
                fixable=False,
                fix_plan=parsed.get("fix_plan", ""),
                human_guidance="Agent output did not validate. Manual review required.",
            )

    async def fix(
        self,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        diagnosis: DiagnosisResult,
        wt_path: str,
    ) -> tuple[bool, str]:
        """Stage 2: Attempt fix in worktree. Returns (success, transcript)."""
        prompt = (
            f"# Fix Issue #{issue_number}: {issue_title}\n\n"
            f"**Root Cause:** {diagnosis.root_cause}\n\n"
            f"**Fix Plan:** {diagnosis.fix_plan}\n\n"
            f"**Affected Files:** {', '.join(diagnosis.affected_files)}\n\n"
            f"**Issue Body:**\n{issue_body}\n\n"
            "Apply the fix. Run `make quality` to verify. "
            "Commit your changes with a descriptive message."
        )
        wt = Path(wt_path)
        try:
            cmd = self._build_command(wt)
            transcript = await self._execute(
                cmd,
                prompt,
                wt,
                {"issue": issue_number, "source": "diagnostic_fix"},
            )
            verify = await self._verify_quality(wt)
            return verify.passed, transcript
        except (PermissionError, KeyboardInterrupt, SystemExit, MemoryError):
            raise
        except Exception:
            logger.exception("Diagnostic fix failed for issue #%d", issue_number)
            return False, "Fix agent crashed"
