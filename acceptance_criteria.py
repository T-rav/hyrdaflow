"""Post-merge acceptance criteria generation for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from execution import get_default_runner
from models import VerificationCriteria
from precheck import run_precheck_context
from runner_utils import stream_claude_process

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from execution import SubprocessRunner
    from models import GitHubIssue
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.acceptance_criteria")

_AC_START = "AC_START"
_AC_END = "AC_END"
_VERIFY_START = "VERIFY_START"
_VERIFY_END = "VERIFY_END"


class AcceptanceCriteriaGenerator:
    """Generates acceptance criteria and verification instructions after merge."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self._config = config
        self._prs = prs
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._runner = runner or get_default_runner()

    async def generate(
        self,
        issue_number: int,
        pr_number: int,
        issue: GitHubIssue,
        diff: str,
    ) -> None:
        """Generate acceptance criteria and post/persist them.

        This method is designed to be non-blocking — exceptions are
        caught and logged so they never interrupt the merge flow.
        """
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would generate acceptance criteria for issue #%d",
                issue_number,
            )
            return

        plan_text = self._read_plan_file(issue_number)
        diff_summary = self._summarize_diff(diff)
        test_files = self._extract_test_files(diff)
        precheck_context = await self._run_precheck_context(
            issue, issue_number, pr_number, diff_summary, diff
        )

        prompt = self._build_prompt(
            issue,
            plan_text,
            diff_summary,
            test_files,
            precheck_context=precheck_context,
        )
        cmd = self._build_command()

        transcript = await stream_claude_process(
            cmd=cmd,
            prompt=prompt,
            cwd=self._config.repo_root,
            active_procs=self._active_procs,
            event_bus=self._bus,
            event_data={
                "issue": issue_number,
                "pr": pr_number,
                "source": "ac_generator",
            },
            logger=logger,
            timeout=self._config.agent_timeout,
            runner=self._runner,
        )

        criteria = self._extract_criteria(transcript, issue_number, pr_number)
        if criteria is None:
            logger.warning(
                "Could not extract acceptance criteria from transcript for issue #%d",
                issue_number,
            )
            return

        comment = self._format_comment(criteria)
        await self._prs.post_comment(issue_number, comment)
        self._persist(criteria)

    def _build_command(self) -> list[str]:
        """Build the command for AC generation."""
        return build_agent_command(
            tool=self._config.ac_tool,
            model=self._config.ac_model,
            disallowed_tools="Write,Edit,NotebookEdit",
        )

    def _build_prompt(
        self,
        issue: GitHubIssue,
        plan_text: str,
        diff_summary: str,
        test_files: list[str],
        precheck_context: str = "",
    ) -> str:
        """Build the prompt for AC generation."""
        parts = [
            "You are generating acceptance criteria and human verification "
            "instructions for a successfully merged pull request.\n\n"
            "Your output must be functional and UAT-focused — describe what "
            "a human should do and observe to verify the change works. "
            "Do NOT produce generic criteria like 'tests pass' or "
            "'code compiles'. Instead produce specific, actionable steps "
            "like 'Open the dashboard, navigate to X, click Y, verify Z "
            "appears'.\n\n"
            f"## Original Issue\n\n"
            f"**#{issue.number}: {issue.title}**\n\n"
            f"{issue.body}\n\n",
            f"## Precheck Context\n\n{precheck_context or 'No low-tier precheck context provided.'}\n\n",
        ]

        if plan_text:
            parts.append(f"## Implementation Plan\n\n{plan_text}\n\n")

        if diff_summary:
            parts.append(f"## PR Diff Summary\n\n```\n{diff_summary}\n```\n\n")

        if test_files:
            parts.append(
                "## Test Files Added/Modified\n\n"
                + "\n".join(f"- `{f}`" for f in test_files)
                + "\n\n"
            )

        parts.append(
            "## Instructions\n\n"
            "Produce your output in the following format:\n\n"
            f"{_AC_START}\n"
            "AC-1: <first acceptance criterion>\n"
            "AC-2: <second acceptance criterion>\n"
            "...\n"
            f"{_AC_END}\n\n"
            f"{_VERIFY_START}\n"
            "1. <first verification step>\n"
            "2. <second verification step>\n"
            "...\n"
            f"{_VERIFY_END}\n\n"
            "Rules:\n"
            "- Each AC item must be specific and verifiable\n"
            "- Verification steps must be human-executable (functional/UAT)\n"
            "- Focus on observable behavior, not implementation details\n"
            "- Include 3-7 acceptance criteria\n"
            "- Include 3-10 verification steps\n"
        )

        return "".join(parts)

    def _build_precheck_prompt(
        self, issue: GitHubIssue, issue_number: int, pr_number: int, diff_summary: str
    ) -> str:
        return f"""Run a compact AC-generation precheck for issue #{issue_number} / PR #{pr_number}.

Estimate generation risk and confidence from issue + diff summary.

Return EXACTLY:
PRECHECK_RISK: low|medium|high
PRECHECK_CONFIDENCE: <0.0-1.0>
PRECHECK_ESCALATE: yes|no
PRECHECK_SUMMARY: <one line>

Issue: {issue.title}
Diff summary:
{diff_summary[:3000]}
"""

    async def _run_precheck_context(
        self,
        issue: GitHubIssue,
        issue_number: int,
        pr_number: int,
        diff_summary: str,
        diff: str,
    ) -> str:
        prompt = self._build_precheck_prompt(
            issue, issue_number, pr_number, diff_summary
        )

        async def execute(cmd: list[str], p: str) -> str:
            return await stream_claude_process(
                cmd=cmd,
                prompt=p,
                cwd=self._config.repo_root,
                active_procs=self._active_procs,
                event_bus=self._bus,
                event_data={
                    "issue": issue_number,
                    "pr": pr_number,
                    "source": "ac_precheck",
                },
                logger=logger,
                timeout=self._config.agent_timeout,
                runner=self._runner,
            )

        return await run_precheck_context(
            config=self._config,
            prompt=prompt,
            diff=diff,
            execute=execute,
            debug_message="DEBUG MODE: focus on ambiguity and failure modes.",
            logger=logger,
        )

    def _read_plan_file(self, issue_number: int) -> str:
        """Read the plan from ``.hydraflow/plans/issue-N.md``."""
        plan_path = self._config.plans_dir / f"issue-{issue_number}.md"
        try:
            return plan_path.read_text()
        except OSError:
            logger.debug("Plan file not found for issue #%d", issue_number)
            return ""

    def _summarize_diff(self, diff: str) -> str:
        """Truncate diff to fit in the prompt."""
        limit = self._config.max_review_diff_chars
        if len(diff) <= limit:
            return diff
        return diff[:limit] + "\n... (truncated)"

    def _extract_test_files(self, diff: str) -> list[str]:
        """Extract test file paths from the diff."""
        matches = re.findall(
            r"^(?:diff --git a/|[+]{3} b/)(\S*test\S*\.py)", diff, re.MULTILINE
        )
        return sorted(set(matches))

    def _extract_criteria(
        self, transcript: str, issue_number: int, pr_number: int
    ) -> VerificationCriteria | None:
        """Parse AC and verification sections from the transcript."""
        ac_match = re.search(
            rf"{_AC_START}\s*\n(.*?)\n\s*{_AC_END}",
            transcript,
            re.DOTALL,
        )
        verify_match = re.search(
            rf"{_VERIFY_START}\s*\n(.*?)\n\s*{_VERIFY_END}",
            transcript,
            re.DOTALL,
        )

        if ac_match is None and verify_match is None:
            return None

        ac_text = ac_match.group(1).strip() if ac_match else ""
        verify_text = verify_match.group(1).strip() if verify_match else ""

        return VerificationCriteria(
            issue_number=issue_number,
            pr_number=pr_number,
            acceptance_criteria=ac_text,
            verification_instructions=verify_text,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def _format_comment(self, criteria: VerificationCriteria) -> str:
        """Format criteria as a GitHub markdown comment."""
        lines = [
            "## Acceptance Criteria & Verification Instructions\n",
        ]

        if criteria.acceptance_criteria:
            lines.append("### Acceptance Criteria\n")
            for line in criteria.acceptance_criteria.splitlines():
                stripped = line.strip()
                if stripped:
                    # Convert "AC-N: text" to checkbox format
                    ac_match = re.match(r"AC-\d+:\s*(.*)", stripped)
                    if ac_match:
                        lines.append(f"- [ ] {ac_match.group(1)}")
                    else:
                        lines.append(f"- [ ] {stripped}")
            lines.append("")

        if criteria.verification_instructions:
            lines.append("### Human Verification Steps\n")
            lines.append(criteria.verification_instructions)
            lines.append("")

        lines.append("---\n*Generated by HydraFlow AC Generator*")
        return "\n".join(lines)

    def _persist(self, criteria: VerificationCriteria) -> None:
        """Write criteria to ``.hydraflow/verification/issue-N.md``."""
        verification_dir = self._config.repo_root / ".hydraflow" / "verification"
        path = verification_dir / f"issue-{criteria.issue_number}.md"

        content = (
            f"# Acceptance Criteria — Issue #{criteria.issue_number} "
            f"(PR #{criteria.pr_number})\n\n"
            f"Generated: {criteria.timestamp}\n\n"
        )
        if criteria.acceptance_criteria:
            content += f"## Acceptance Criteria\n\n{criteria.acceptance_criteria}\n\n"
        if criteria.verification_instructions:
            content += (
                f"## Verification Instructions\n\n"
                f"{criteria.verification_instructions}\n\n"
            )

        try:
            verification_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            logger.info(
                "Acceptance criteria persisted to %s",
                path,
            )
        except OSError:
            logger.warning(
                "Could not persist acceptance criteria to %s",
                path,
                exc_info=True,
            )

    def terminate(self) -> None:
        """Kill any active AC generation processes."""
        from runner_utils import terminate_processes

        terminate_processes(self._active_procs)
