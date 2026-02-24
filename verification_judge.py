"""LLM-as-judge for validating acceptance criteria and verification instructions."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from execution import get_default_runner
from models import (
    CriterionResult,
    CriterionVerdict,
    InstructionsQuality,
    InstructionsQualityResult,
    JudgeVerdict,
    ParsedCriteria,
)
from precheck import run_precheck_context
from runner_utils import stream_claude_process, terminate_processes
from subprocess_util import CreditExhaustedError

if TYPE_CHECKING:
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.verification_judge")


class VerificationJudge:
    """Validates acceptance criteria against merged code and evaluates instruction quality.

    Reads criteria from ``.hydraflow/verification/issue-N.md``, runs two LLM calls
    (code validation + instructions validation), optionally refines unclear
    instructions (max 1 retry), and persists a judge report.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._runner = runner or get_default_runner()

    async def judge(
        self,
        issue_number: int,
        pr_number: int,
        diff: str,
    ) -> JudgeVerdict | None:
        """Run the verification judge for the given issue.

        Returns ``None`` if no criteria file exists (graceful skip).
        """
        criteria_text = self._read_criteria_file(issue_number)
        if criteria_text is None:
            logger.debug(
                "No verification criteria file for issue #%d — skipping judge",
                issue_number,
            )
            return None

        if self._config.dry_run:
            logger.info(
                "[dry-run] Would run verification judge for issue #%d", issue_number
            )
            return JudgeVerdict(issue_number=issue_number)

        criteria_list, instructions_text = self._parse_criteria(criteria_text)
        precheck_context = await self._run_precheck_context(
            issue_number, criteria_text, diff
        )

        verdict = JudgeVerdict(
            issue_number=issue_number,
            verification_instructions=instructions_text,
        )

        cmd = self._build_command()

        # --- Code validation ---
        if criteria_list:
            try:
                code_prompt = self._build_code_validation_prompt(
                    criteria_list,
                    diff,
                    issue_number,
                    precheck_context=precheck_context,
                )
                transcript = await self._execute(cmd, code_prompt, issue_number)
                verdict.criteria_results = self._parse_criteria_results(transcript)
                verdict.all_criteria_pass = (
                    all(
                        cr.verdict == CriterionVerdict.PASS
                        for cr in verdict.criteria_results
                    )
                    and len(verdict.criteria_results) > 0
                )
            except CreditExhaustedError:
                raise
            except Exception:
                logger.warning(
                    "Code validation failed for issue #%d",
                    issue_number,
                    exc_info=True,
                )

        # --- Instructions validation ---
        if instructions_text.strip():
            try:
                instr_prompt = self._build_instructions_validation_prompt(
                    instructions_text,
                    issue_number,
                    precheck_context=precheck_context,
                )
                transcript = await self._execute(cmd, instr_prompt, issue_number)
                quality, feedback = self._parse_instructions_quality(transcript)
                verdict.instructions_quality = quality
                verdict.instructions_feedback = feedback

                # Refine once if needed
                if quality == InstructionsQuality.NEEDS_REFINEMENT:
                    refine_prompt = self._build_refinement_prompt(
                        instructions_text, feedback, issue_number
                    )
                    refine_transcript = await self._execute(
                        cmd, refine_prompt, issue_number
                    )
                    refined = self._extract_refined_instructions(refine_transcript)
                    if refined:
                        self._update_criteria_file(issue_number, refined)

                    # Re-validate refined instructions
                    revalidate_text = refined or instructions_text
                    verdict.verification_instructions = revalidate_text
                    revalidate_prompt = self._build_instructions_validation_prompt(
                        revalidate_text,
                        issue_number,
                        precheck_context=precheck_context,
                    )
                    revalidate_transcript = await self._execute(
                        cmd, revalidate_prompt, issue_number
                    )
                    quality2, feedback2 = self._parse_instructions_quality(
                        revalidate_transcript
                    )
                    verdict.instructions_quality = quality2
                    verdict.instructions_feedback = feedback2
                    verdict.refined = bool(refined)
            except CreditExhaustedError:
                raise
            except Exception:
                logger.warning(
                    "Instructions validation failed for issue #%d",
                    issue_number,
                    exc_info=True,
                )

        # Build summary
        pass_count = sum(
            1 for cr in verdict.criteria_results if cr.verdict == CriterionVerdict.PASS
        )
        total = len(verdict.criteria_results)
        verdict.summary = (
            f"{pass_count}/{total} criteria passed, "
            f"instructions: {verdict.instructions_quality.value}"
        )

        # Persist and publish
        self._save_judge_report(issue_number, verdict)

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.VERIFICATION_JUDGE,
                data={
                    "issue": issue_number,
                    "pr": pr_number,
                    "all_criteria_pass": verdict.all_criteria_pass,
                    "instructions_quality": verdict.instructions_quality.value,
                    "summary": verdict.summary,
                },
            )
        )

        return verdict

    def _read_criteria_file(self, issue_number: int) -> str | None:
        """Read the verification criteria file for the given issue."""
        path = self._config.data_path("verification", f"issue-{issue_number}.md")
        if not path.exists():
            return None
        try:
            return path.read_text()
        except OSError:
            logger.warning("Could not read criteria file %s", path, exc_info=True)
            return None

    def _parse_criteria(self, criteria_text: str) -> ParsedCriteria:
        """Extract acceptance criteria items and instructions from the markdown."""
        criteria: list[str] = []
        instructions = ""

        # Extract criteria: checkbox items only within the Acceptance Criteria section
        criteria_match = re.search(
            r"(?:^|\n)##\s*Acceptance\s+Criteria\s*\n(.*?)(?=\n##|\Z)",
            criteria_text,
            re.DOTALL | re.IGNORECASE,
        )
        if criteria_match:
            section_text = criteria_match.group(1)
            for line in section_text.splitlines():
                stripped = line.strip()
                match = re.match(r"^-\s*\[[ x]\]\s*(.*)", stripped, re.IGNORECASE)
                if match:
                    criteria.append(match.group(1).strip())

        # Extract instructions section
        instr_match = re.search(
            r"(?:^|\n)##\s*(?:Verification\s+)?Instructions?\s*\n(.*)",
            criteria_text,
            re.DOTALL | re.IGNORECASE,
        )
        if instr_match:
            # Take everything until the next ## heading or end of text
            raw = instr_match.group(1)
            next_heading = re.search(r"\n##\s", raw)
            if next_heading:
                instructions = raw[: next_heading.start()].strip()
            else:
                instructions = raw.strip()

        return ParsedCriteria(criteria_list=criteria, instructions_text=instructions)

    def _build_code_validation_prompt(
        self,
        criteria: list[str],
        diff: str,
        issue_number: int,
        precheck_context: str = "",
    ) -> str:
        """Build the prompt for evaluating acceptance criteria against the diff."""
        max_diff = self._config.max_review_diff_chars
        if len(diff) > max_diff:
            diff = diff[:max_diff] + f"\n\n[Diff truncated at {max_diff:,} chars]"

        criteria_block = "\n".join(f"AC-{i + 1}: {c}" for i, c in enumerate(criteria))

        return f"""You are a verification judge evaluating whether the merged code for issue #{issue_number} meets its acceptance criteria.

## Acceptance Criteria

{criteria_block}

## Merged Diff

```diff
{diff}
```

## Precheck Context

{precheck_context or "No low-tier precheck context provided."}

## Instructions

Evaluate EACH acceptance criterion against the diff. For each criterion, determine:
- PASS: The diff clearly satisfies this criterion
- FAIL: The diff does not satisfy this criterion or there is insufficient evidence

## Required Output Format

Output your evaluation between these markers:

CRITERIA_RESULTS_START
AC-1: PASS — <reasoning about why it passes, citing specific code>
AC-2: FAIL — <reasoning about why it fails>
CRITERIA_RESULTS_END

SUMMARY: <one-line overall summary>
"""

    def _build_instructions_validation_prompt(
        self, instructions: str, issue_number: int, precheck_context: str = ""
    ) -> str:
        """Build the prompt for evaluating human verification instructions quality."""
        return f"""You are evaluating the quality of human verification instructions for issue #{issue_number}.

## Verification Instructions

{instructions}

## Precheck Context

{precheck_context or "No low-tier precheck context provided."}

## Evaluation Criteria

Check whether the instructions are:
1. **Specific enough** — Can a human follow them without guessing?
2. **Reference actual elements** — Do steps reference real UI elements, endpoints, or commands?
3. **Clear expected outcomes** — Is it obvious what a passing verification looks like?
4. **Complete** — Are any verification steps missing?

## Required Output Format

INSTRUCTIONS_QUALITY: READY
or
INSTRUCTIONS_QUALITY: NEEDS_REFINEMENT
INSTRUCTIONS_FEEDBACK: <specific feedback about what needs improvement>
"""

    def _build_refinement_prompt(
        self, instructions: str, feedback: str, issue_number: int
    ) -> str:
        """Build the prompt for refining unclear instructions."""
        return f"""You are refining human verification instructions for issue #{issue_number}.

## Original Instructions

{instructions}

## Feedback

{feedback}

## Task

Rewrite the instructions addressing the feedback. Make them specific, actionable, and clear.

## Required Output Format

REFINED_INSTRUCTIONS_START
<your refined instructions here>
REFINED_INSTRUCTIONS_END
"""

    def _build_command(self) -> list[str]:
        """Construct the CLI invocation for the judge."""
        return build_agent_command(
            tool=self._config.verification_judge_tool,
            model=self._config.review_model,
            disallowed_tools="Write,Edit,NotebookEdit",
        )

    def _build_precheck_prompt(
        self, issue_number: int, criteria: str, diff: str
    ) -> str:
        return f"""Run a compact verification-judge precheck for issue #{issue_number}.

Return EXACTLY:
PRECHECK_RISK: low|medium|high
PRECHECK_CONFIDENCE: <0.0-1.0>
PRECHECK_ESCALATE: yes|no
PRECHECK_SUMMARY: <one line>

Criteria excerpt:
{criteria[:2000]}

Diff excerpt:
{diff[:3000]}
"""

    async def _run_precheck_context(
        self, issue_number: int, criteria_text: str, diff: str
    ) -> str:
        prompt = self._build_precheck_prompt(issue_number, criteria_text, diff)

        async def execute(cmd: list[str], p: str) -> str:
            return await self._execute(cmd, p, issue_number)

        return await run_precheck_context(
            config=self._config,
            prompt=prompt,
            diff=diff,
            execute=execute,
            debug_message="DEBUG MODE: focus on failure and ambiguity hotspots.",
            logger=logger,
        )

    def _parse_criteria_results(self, transcript: str) -> list[CriterionResult]:
        """Parse criterion results from the transcript."""
        results: list[CriterionResult] = []

        # Extract block between markers — return empty if markers are absent
        # to avoid parsing random LLM commentary as results
        block_match = re.search(
            r"CRITERIA_RESULTS_START\s*\n(.*?)\nCRITERIA_RESULTS_END",
            transcript,
            re.DOTALL,
        )
        if not block_match:
            return results
        text = block_match.group(1)

        pattern = re.compile(r"(AC-\d+):\s*(PASS|FAIL)\s*[—\-]+\s*(.*)", re.IGNORECASE)
        for match in pattern.finditer(text):
            criterion_id = match.group(1)
            raw_verdict = match.group(2).upper()
            reasoning = match.group(3).strip()
            verdict = (
                CriterionVerdict.PASS
                if raw_verdict == "PASS"
                else CriterionVerdict.FAIL
            )
            results.append(
                CriterionResult(
                    criterion=criterion_id,
                    verdict=verdict,
                    reasoning=reasoning,
                )
            )

        return results

    def _parse_instructions_quality(self, transcript: str) -> InstructionsQualityResult:
        """Parse instructions quality verdict and feedback from the transcript."""
        quality_match = re.search(
            r"INSTRUCTIONS_QUALITY:\s*(READY|NEEDS_REFINEMENT)",
            transcript,
            re.IGNORECASE,
        )
        if quality_match:
            raw = quality_match.group(1).upper()
            quality = (
                InstructionsQuality.READY
                if raw == "READY"
                else InstructionsQuality.NEEDS_REFINEMENT
            )
        else:
            quality = InstructionsQuality.NEEDS_REFINEMENT

        feedback_match = re.search(
            r"INSTRUCTIONS_FEEDBACK:\s*(.*)",
            transcript,
            re.DOTALL,
        )
        feedback = feedback_match.group(1).strip() if feedback_match else ""

        return InstructionsQualityResult(quality=quality, feedback=feedback)

    def _extract_refined_instructions(self, transcript: str) -> str:
        """Extract refined instructions from between markers."""
        match = re.search(
            r"REFINED_INSTRUCTIONS_START\s*\n(.*?)\nREFINED_INSTRUCTIONS_END",
            transcript,
            re.DOTALL,
        )
        return match.group(1).strip() if match else ""

    def _save_judge_report(self, issue_number: int, verdict: JudgeVerdict) -> None:
        """Write the judge report to ``.hydraflow/verification/issue-N-judge.md``."""
        path = self._config.data_path("verification", f"issue-{issue_number}-judge.md")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._format_judge_report(verdict))
            logger.info("Judge report saved to %s", path)
        except OSError:
            logger.warning("Could not save judge report to %s", path, exc_info=True)

    def _format_judge_report(self, verdict: JudgeVerdict) -> str:
        """Format the judge verdict as a markdown report."""
        lines = [f"# Verification Judge Report — Issue #{verdict.issue_number}\n"]

        # Criteria results table
        lines.append("## Acceptance Criteria Results\n")
        if verdict.criteria_results:
            lines.append("| Criterion | Verdict | Reasoning |")
            lines.append("|-----------|---------|-----------|")
            for cr in verdict.criteria_results:
                icon = "PASS" if cr.verdict == CriterionVerdict.PASS else "FAIL"
                safe_reasoning = cr.reasoning.replace("|", "\\|")
                lines.append(f"| {cr.criterion} | {icon} | {safe_reasoning} |")
        else:
            lines.append("No criteria evaluated.")
        lines.append("")

        # Summary
        pass_count = sum(
            1 for cr in verdict.criteria_results if cr.verdict == CriterionVerdict.PASS
        )
        total = len(verdict.criteria_results)
        lines.append(f"**Result**: {pass_count}/{total} criteria passed\n")

        # Instructions quality
        lines.append("## Instructions Quality\n")
        lines.append(f"**Verdict**: {verdict.instructions_quality.value}")
        if verdict.instructions_feedback:
            lines.append(f"\n**Feedback**: {verdict.instructions_feedback}")
        if verdict.refined:
            lines.append("\n*Instructions were refined during evaluation.*")
        lines.append("")

        # Verification instructions
        if verdict.verification_instructions:
            lines.append("## Verification Instructions\n")
            lines.append(verdict.verification_instructions)
            lines.append("")

        # Overall summary
        if verdict.summary:
            lines.append(f"## Summary\n\n{verdict.summary}\n")

        lines.append("---\n*Generated by HydraFlow Verification Judge*")
        return "\n".join(lines)

    def _update_criteria_file(
        self, issue_number: int, refined_instructions: str
    ) -> None:
        """Replace the instructions section in the verification file with refined text."""
        path = self._config.data_path("verification", f"issue-{issue_number}.md")
        if not path.exists():
            return

        try:
            content = path.read_text()
        except OSError:
            logger.warning("Could not read criteria file %s", path, exc_info=True)
            return

        # Find and replace the instructions section
        pattern = re.compile(
            r"(##\s*(?:Verification\s+)?Instructions?\s*\n)(.*?)(\n##|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(content)
        if match:
            new_content = (
                content[: match.start()]
                + match.group(1)
                + refined_instructions
                + "\n"
                + content[match.start(3) :]
            )
        else:
            # No instructions section — append one
            new_content = (
                content + f"\n## Verification Instructions\n\n{refined_instructions}\n"
            )

        try:
            path.write_text(new_content)
        except OSError:
            logger.warning("Could not update criteria file %s", path, exc_info=True)

    async def _execute(self, cmd: list[str], prompt: str, issue_number: int) -> str:
        """Run the claude judge process."""
        return await stream_claude_process(
            cmd=cmd,
            prompt=prompt,
            cwd=self._config.repo_root,
            active_procs=self._active_procs,
            event_bus=self._bus,
            event_data={"issue": issue_number, "source": "verification_judge"},
            logger=logger,
            timeout=self._config.agent_timeout,
            runner=self._runner,
        )

    def terminate(self) -> None:
        """Kill all active judge subprocesses."""
        terminate_processes(self._active_procs)
