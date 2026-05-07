"""Triage-time bug reproduction runner (#6424).

For bug-classified issues, attempts to write a failing test under
``tests/regressions/test_issue_{N}.py`` (or, when an automated test
isn't feasible, a manual repro script). The result is stored as a
``reproduction_stored`` cache record so the planner can reference the
test path and the reviewer can verify the fix actually flips the test
red → green.

Like ``PlanReviewer`` (#6421), this runner is split into:

  1. A pure transcript parser (``_parse_outcome``) — testable on
     hand-crafted reproducer transcripts.
  2. A pure prompt builder (``_build_prompt``) — testable without
     any subprocess machinery.
  3. The ``reproduce`` orchestration entry point with a dry-run
     shortcut and an injectable subprocess hook.

Subprocess wiring lands in the phase-integration follow-up. The
acceptance criteria for #6424 require sandboxed write permissions
(only ``tests/regressions/`` is writable) — that policy is enforced
by ``BaseRunner._build_command`` configuration in the follow-up.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from pathlib import Path

from agent_cli import build_agent_command
from base_runner import BaseRunner
from models import (
    ReproductionOutcome,
    ReproductionResult,
    Task,
)

logger = logging.getLogger("hydraflow.bug_reproducer")


REPRO_START = "REPRO_START"
REPRO_END = "REPRO_END"

# Each transcript carries one Outcome line plus optional payload lines.
_OUTCOME_RE = re.compile(
    r"^\s*Outcome\s*:\s*(?P<outcome>success|partial|unable)\s*$",
    re.IGNORECASE,
)
_TEST_PATH_RE = re.compile(
    r"^\s*Test[_\s]?path\s*:\s*(?P<path>.+)$",
    re.IGNORECASE,
)
_CONFIDENCE_RE = re.compile(
    r"^\s*Confidence\s*:\s*(?P<value>[0-9.]+)\s*$",
    re.IGNORECASE,
)
_FAILING_OUTPUT_RE = re.compile(
    r"^\s*Failing[_\s]?output\s*:\s*(?P<text>.+)$",
    re.IGNORECASE,
)
_REPRO_SCRIPT_RE = re.compile(
    r"^\s*Repro[_\s]?script\s*:\s*(?P<text>.+)$",
    re.IGNORECASE,
)
_INVESTIGATION_RE = re.compile(
    r"^\s*Investigation\s*:\s*(?P<text>.+)$",
    re.IGNORECASE,
)


class BugReproducer(BaseRunner):
    """Read-write (scoped to ``tests/regressions/``) reproducer for bug issues."""

    _log = logger

    async def reproduce(self, task: Task) -> ReproductionResult:
        """Run the reproducer for *task*.

        Returns a :class:`ReproductionResult`. Dry-run mode short-circuits
        to ``UNABLE`` so callers can exercise the route-to-HITL path
        without spawning a subprocess.
        """
        start = time.monotonic()
        result = ReproductionResult(
            issue_number=task.id,
            outcome=ReproductionOutcome.UNABLE,
            confidence=0.0,
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would reproduce bug for issue #%d", task.id)
            result.investigation = "Dry-run: reproduction skipped"
            result.duration_seconds = time.monotonic() - start
            return result

        try:
            transcript = await self._run_reproducer_subprocess(task)
        except Exception as exc:  # noqa: BLE001
            result.error = f"reproducer subprocess failed: {exc}"
            result.investigation = f"subprocess raised: {exc}"
            result.duration_seconds = time.monotonic() - start
            logger.warning(
                "Bug reproducer subprocess failed for issue #%d",
                task.id,
                exc_info=True,
            )
            return result

        parsed = self._parse_outcome(transcript)
        result.outcome = parsed.outcome
        result.test_path = parsed.test_path
        result.repro_script = parsed.repro_script
        result.failing_output = parsed.failing_output
        result.investigation = parsed.investigation
        result.confidence = parsed.confidence
        result.duration_seconds = time.monotonic() - start

        logger.info(
            "Bug reproduction complete for issue #%d: outcome=%s confidence=%.2f",
            task.id,
            result.outcome,
            result.confidence,
        )
        return result

    async def _run_reproducer_subprocess(self, task: Task) -> str:
        """Spawn the reproducer subprocess and return its raw transcript.

        Builds the reproducer prompt via ``_build_prompt`` and runs it
        through ``BaseRunner._execute`` against the read-only repo
        root. The reproducer is allowed to write under
        ``tests/regressions/`` (and only there) and to run ``Bash`` so
        it can confirm the failing test is actually red — but it must
        NOT modify ``src/`` or fix the bug. Tool-level enforcement of
        the write scope is the agent runtime's responsibility; the
        prompt explicitly forbids src/ modification as a backstop.

        Terminates early when the ``REPRO_END`` marker appears, the
        same way ``PlannerRunner.plan`` terminates on ``PLAN_END``.
        """
        cmd = self._build_command()
        prompt = self._build_prompt(task)

        def _check_repro_complete(accumulated: str) -> bool:
            # Only checks the END marker, not START — same shape as
            # PlannerRunner._check_plan_complete and PlanReviewer's
            # _check_review_complete. If the agent emits REPRO_END in
            # prose before its structured outcome block, the callback
            # fires early and the parser falls back to the default
            # UNABLE outcome. Triage logs at warning and the issue
            # stays in the find queue for retry — correct conservative
            # behavior.
            if REPRO_END in accumulated:
                logger.info(
                    "Repro markers found for issue #%d — terminating reproducer",
                    task.id,
                )
                return True
            return False

        return await self._execute(
            cmd,
            prompt,
            self._config.repo_root,
            {"issue": task.id, "source": "bug_reproducer"},
            on_output=_check_repro_complete,
        )

    def _build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Build the reproducer CLI invocation.

        The reproducer needs Write + Bash to create a failing test
        and confirm it is red. NotebookEdit is disallowed (no
        notebook reproductions). The agent prompt itself constrains
        Write targets to ``tests/regressions/``; CLI-level scoping
        is the agent runtime's responsibility.

        ``_worktree_path`` is accepted for ``BaseRunner._build_command``
        signature compatibility but unused — the reproducer always
        runs against ``self._config.repo_root``.
        """
        return build_agent_command(
            tool=self._config.planner_tool,
            model=self._config.planner_model,
            disallowed_tools="NotebookEdit",
        )

    # ------------------------------------------------------------------
    # Pure helpers
    # ------------------------------------------------------------------

    @classmethod
    def _build_prompt(cls, task: Task) -> str:
        """Build the reproducer prompt for *task*. Pure function."""
        return (
            f"You are a bug reproducer for HydraFlow issue #{task.id}. "
            f"Your job is to write a failing test that demonstrates the "
            f"bug described below, OR (if a test is infeasible) produce "
            f"a manual reproduction script. Do not fix the bug — only "
            f"reproduce it.\n\n"
            f"## Issue\n\n"
            f"**Title:** {task.title}\n\n"
            f"**Body:**\n{task.body}\n\n"
            f"## Allowed actions\n\n"
            f"- Read any file in the repo.\n"
            f"- Write a new test file under `tests/regressions/test_issue_"
            f"{task.id}.py` (preferred path).\n"
            f"- Run the test to confirm it is RED.\n"
            f"- Do NOT modify any file under `src/`.\n"
            f"- Do NOT fix the bug — only reproduce it.\n\n"
            f"## Outcomes\n\n"
            f"- **success**: failing test written and confirmed red\n"
            f"- **partial**: agent could reproduce manually but not "
            f"automate — produce a `repro.sh`-style script\n"
            f"- **unable**: could not reproduce at all — escalate to "
            f"a human\n\n"
            f"## Output format\n\n"
            f"Emit your result between {REPRO_START} and {REPRO_END} "
            f"markers using these key/value lines (one per line):\n"
            f"```\n"
            f"Outcome: success | partial | unable\n"
            f"Test_path: tests/regressions/test_issue_{task.id}.py\n"
            f"Confidence: 0.0..1.0\n"
            f"Failing_output: <one-line summary of the failing assertion>\n"
            f"Repro_script: <one-line repro command, for partial outcomes>\n"
            f"Investigation: <free-form notes for unable outcomes>\n"
            f"```\n"
            f"Only the Outcome line is required. Other lines are optional "
            f"depending on the outcome — e.g., success needs Test_path, "
            f"partial needs Repro_script, unable needs Investigation."
        )

    @classmethod
    def _parse_outcome(cls, transcript: str) -> ReproductionResult:
        """Extract a ReproductionResult from a reproducer transcript.

        Returns a result with ``outcome=UNABLE`` if no markers are
        found — the same shape as a "no useful output" failure mode.
        ``issue_number`` is set to 0 because this parser does not have
        access to the issue context; the orchestration layer overwrites
        it from the call site.
        """
        result = ReproductionResult(
            issue_number=0,
            outcome=ReproductionOutcome.UNABLE,
            confidence=0.0,
        )

        start_idx = transcript.find(REPRO_START)
        end_idx = transcript.find(REPRO_END)
        if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
            return result

        body = transcript[start_idx + len(REPRO_START) : end_idx]
        for raw_line in body.splitlines():
            outcome_match = _OUTCOME_RE.match(raw_line)
            if outcome_match:
                with contextlib.suppress(ValueError):
                    result.outcome = ReproductionOutcome(
                        outcome_match.group("outcome").lower()
                    )
                continue

            test_match = _TEST_PATH_RE.match(raw_line)
            if test_match:
                result.test_path = test_match.group("path").strip()
                continue

            confidence_match = _CONFIDENCE_RE.match(raw_line)
            if confidence_match:
                try:
                    raw_value = float(confidence_match.group("value"))
                except ValueError:
                    raw_value = 0.0
                # Clamp to [0, 1] so a malformed reproducer line cannot
                # produce a model-validation error downstream.
                result.confidence = max(0.0, min(1.0, raw_value))
                continue

            failing_match = _FAILING_OUTPUT_RE.match(raw_line)
            if failing_match:
                result.failing_output = failing_match.group("text").strip()
                continue

            script_match = _REPRO_SCRIPT_RE.match(raw_line)
            if script_match:
                result.repro_script = script_match.group("text").strip()
                continue

            investigation_match = _INVESTIGATION_RE.match(raw_line)
            if investigation_match:
                result.investigation = investigation_match.group("text").strip()
                continue
        return result
