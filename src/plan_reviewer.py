"""Adversarial plan review runner (#6421).

Runs a read-only review agent against a produced ``PlanResult`` and
returns a ``PlanReview`` carrying severity-tagged findings. The output
gates the READY transition: if any finding has CRITICAL or HIGH
severity, ``plan_phase`` routes the issue back to PLAN with the
findings as feedback context (#6423 wires the route-back).

This runner is deliberately small. It owns:

  1. A pure prompt builder (``_build_prompt``) — testable without
     subprocess machinery.
  2. A pure findings parser (``_parse_findings``) — testable on
     hand-crafted transcript fixtures.
  3. The ``review`` orchestration entry point that ties subprocess
     execution to the parser, with a dry-run shortcut.

Subprocess execution reuses the ``BaseRunner`` infrastructure
(``stream_claude_process``, ``_execute``) — no new shell wrangling.
The actual integration into ``plan_phase._handle_plan_success`` is a
follow-up; this module lands the unit-testable surface.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from base_runner import BaseRunner
from models import (
    PlanFinding,
    PlanFindingSeverity,
    PlanResult,
    PlanReview,
    Task,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger("hydraflow.plan_reviewer")


# ---------------------------------------------------------------------------
# Marker contract
# ---------------------------------------------------------------------------

# The reviewer agent is instructed to bracket its findings with these
# markers so the parser can extract them deterministically without
# pulling stray heading-like text out of the rest of the transcript.
PLAN_REVIEW_START = "PLAN_REVIEW_START"
PLAN_REVIEW_END = "PLAN_REVIEW_END"

# Each finding line follows the shape:
#     - [severity] dimension: description
# with an optional indented suggestion line:
#       Suggestion: do this instead
_FINDING_RE = re.compile(
    r"^\s*-\s*\[(?P<severity>critical|high|medium|low|info)\]\s*"
    r"(?P<dimension>[a-z_][a-z0-9_]*)\s*:\s*(?P<description>.+)$",
    re.IGNORECASE,
)
_SUGGESTION_RE = re.compile(
    r"^\s+Suggestion\s*:\s*(?P<suggestion>.+)$",
    re.IGNORECASE,
)

# Dimensions the reviewer is asked to consider. These appear in the
# prompt and are validated by the parser — unknown dimensions are not
# rejected (the model might invent a useful one), they pass through as-is.
REVIEW_DIMENSIONS: tuple[str, ...] = (
    "correctness",
    "edge_cases",
    "test_strategy",
    "scope_creep",
    "convention",
    "security",
    "reproduction",
)


class PlanReviewer(BaseRunner):
    """Read-only adversarial reviewer for produced plans (#6421)."""

    _log = logger

    async def review(
        self,
        task: Task,
        plan_result: PlanResult,
        *,
        plan_version: int = 1,
    ) -> PlanReview:
        """Run the reviewer on *plan_result* for *task*.

        Returns a :class:`PlanReview`. ``plan_version`` is the version
        the issue cache assigned to the plan being reviewed — surfaces
        in the review record so versioned plans and versioned reviews
        line up in the audit trail.

        Dry-run mode short-circuits to a successful empty review (no
        findings) so test runs do not spawn subprocesses.
        """
        start = time.monotonic()
        review = PlanReview(
            issue_number=task.id,
            plan_version=plan_version,
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would review plan for issue #%d", task.id)
            review.success = True
            review.summary = "Dry-run: review skipped"
            review.duration_seconds = time.monotonic() - start
            return review

        if not plan_result.success or not plan_result.plan:
            review.error = "no plan to review"
            review.summary = "Plan reviewer skipped — no plan produced"
            review.duration_seconds = time.monotonic() - start
            return review

        try:
            transcript = await self._run_review_subprocess(task, plan_result)
        except Exception as exc:  # noqa: BLE001
            review.error = f"reviewer subprocess failed: {exc}"
            review.summary = "Reviewer subprocess raised"
            review.duration_seconds = time.monotonic() - start
            logger.warning(
                "Plan reviewer subprocess failed for issue #%d",
                task.id,
                exc_info=True,
            )
            return review

        review.transcript = transcript
        review.findings = self._parse_findings(transcript)
        review.success = True
        review.summary = self._summarize_findings(review.findings)
        review.duration_seconds = time.monotonic() - start

        logger.info(
            "Plan review complete for issue #%d: %d findings, blocking=%s",
            task.id,
            len(review.findings),
            review.has_blocking_findings,
        )
        return review

    async def _run_review_subprocess(self, task: Task, plan_result: PlanResult) -> str:
        """Spawn the reviewer subprocess and return its raw transcript.

        Split out so unit tests can patch this single method to return
        a hand-crafted transcript without exercising the full BaseRunner
        subprocess machinery.

        The actual subprocess wiring lands in the phase-integration
        follow-up — this method is a thin shim today so the public
        ``review`` method has a clean injection point for tests. The
        prompt built by ``_build_prompt`` is the input.
        """
        _ = (task, plan_result)  # unused until follow-up wiring
        raise NotImplementedError(
            "Plan reviewer subprocess is not wired in this PR — patch "
            "PlanReviewer._run_review_subprocess in tests to inject a "
            "transcript, or call review() in dry-run mode."
        )

    # ------------------------------------------------------------------
    # Pure helpers (testable in isolation)
    # ------------------------------------------------------------------

    @classmethod
    def _build_prompt(cls, task: Task, plan: str) -> str:
        """Build the reviewer prompt for *task* against *plan*.

        Returns the full system+user prompt string the reviewer agent
        is launched with. Pure function — no subprocess, no I/O.
        """
        dimensions_list = "\n".join(f"- {d}" for d in REVIEW_DIMENSIONS)
        return (
            f"You are an adversarial plan reviewer for HydraFlow issue "
            f"#{task.id}. Critique the implementation plan below across "
            f"the dimensions listed. Be skeptical — your job is to find "
            f"problems, not to validate work.\n\n"
            f"## Issue\n\n"
            f"**Title:** {task.title}\n\n"
            f"**Body:**\n{task.body}\n\n"
            f"## Plan to review\n\n"
            f"{plan}\n\n"
            f"## Review dimensions\n\n"
            f"{dimensions_list}\n\n"
            f"## Severity scale\n\n"
            f"- **critical** — the plan is wrong; if implemented as-is "
            f"it will produce a broken system\n"
            f"- **high** — the plan is incomplete in a way that will "
            f"cause test failures or hidden bugs\n"
            f"- **medium** — over-engineering, scope creep, missed "
            f"convention\n"
            f"- **low** — cosmetic or stylistic\n"
            f"- **info** — observation only, not a finding\n\n"
            f"## Output format\n\n"
            f"Write findings between {PLAN_REVIEW_START} and "
            f"{PLAN_REVIEW_END} markers. One finding per bullet, with "
            f"the shape:\n"
            f"```\n"
            f"- [severity] dimension: short description of the problem\n"
            f"  Suggestion: concrete remediation\n"
            f"```\n"
            f"The Suggestion line is optional but encouraged. If you "
            f"have no findings, emit an empty markers block — that's a "
            f"clean review."
        )

    @classmethod
    def _parse_findings(cls, transcript: str) -> list[PlanFinding]:
        """Extract structured findings from a reviewer transcript.

        Looks for content between ``PLAN_REVIEW_START`` and
        ``PLAN_REVIEW_END`` markers. Lines that don't match the
        finding regex are skipped silently — the marker block is
        permitted to contain prose.

        Returns findings in the order they appear in the transcript.
        """
        start_idx = transcript.find(PLAN_REVIEW_START)
        end_idx = transcript.find(PLAN_REVIEW_END)
        if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
            return []

        body = transcript[start_idx + len(PLAN_REVIEW_START) : end_idx]
        findings: list[PlanFinding] = []
        current: PlanFinding | None = None

        for raw_line in body.splitlines():
            finding_match = _FINDING_RE.match(raw_line)
            if finding_match:
                # Commit any in-flight finding before starting a new one.
                if current is not None:
                    findings.append(current)
                try:
                    severity = PlanFindingSeverity(
                        finding_match.group("severity").lower()
                    )
                except ValueError:
                    continue
                current = PlanFinding(
                    severity=severity,
                    dimension=finding_match.group("dimension").lower(),
                    description=finding_match.group("description").strip(),
                )
                continue

            suggestion_match = _SUGGESTION_RE.match(raw_line)
            if suggestion_match and current is not None:
                # Use model_copy to produce a fresh PlanFinding with
                # the suggestion populated. PlanFinding is not declared
                # frozen, so direct assignment would also work, but
                # model_copy makes the copy-then-rebind contract
                # explicit and avoids the trap of mutating an instance
                # that may have already been appended to a list.
                current = current.model_copy(
                    update={"suggestion": suggestion_match.group("suggestion").strip()}
                )

        if current is not None:
            findings.append(current)
        return findings

    @staticmethod
    def _summarize_findings(findings: Iterable[PlanFinding]) -> str:
        """Return a one-line summary of finding counts by severity."""
        counts: dict[str, int] = {}
        for finding in findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        if not counts:
            return "Plan review clean — no findings"
        parts = [
            f"{counts.get(s, 0)} {s}"
            for s in (
                PlanFindingSeverity.CRITICAL,
                PlanFindingSeverity.HIGH,
                PlanFindingSeverity.MEDIUM,
                PlanFindingSeverity.LOW,
                PlanFindingSeverity.INFO,
            )
            if counts.get(s, 0) > 0
        ]
        return f"Plan review: {', '.join(parts)}"
