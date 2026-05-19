"""SpecJudge — pre-implementation gate on plan + draft acceptance criteria.

Sibling of (not a refactor of) ``src/verification_judge.py``. That module
judges real code, diffs, and test output post-merge. This one judges the plan
itself: are the draft AC concrete, observable, and testable from the plan as
written? The two have different inputs, different prompts, and run at
different points in the pipeline; the duplication is intentional.

Parse-failure policy: if the agent output is unparseable, return a FAIL
verdict with a synthetic HIGH concern. A judge is a gate — defaulting to
FAIL on parse failure forces human or retry attention rather than silently
PASSing on garbled output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from exception_classify import reraise_on_credit_or_bug
from src.adversarial_agents import AgentLike
from src.pending_concerns import Concern

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are the Pre-Implementation Spec Judge. You evaluate whether a plan's
acceptance criteria are concrete, observable, and testable from the plan as
written.

You judge the SPEC, not the eventual code. You ask:
  - Is each AC observable (pass/fail readable from test output)?
  - Is each AC concrete (no "reasonable", "appropriate", "etc.")?
  - Does the plan provide enough detail to write a failing test for each AC?
  - Do any pending_concerns indicate an AC will be unverifiable in practice?

Output strict JSON:
  {"verdict": "PASS" | "FAIL",
   "findings": [{"severity": "CRITICAL|HIGH|MEDIUM|LOW", "concern": "..."}]}

FAIL if any CRITICAL or HIGH finding exists.
"""


@dataclass
class JudgeResult:
    verdict: Literal["PASS", "FAIL"]
    findings: list[Concern] = field(default_factory=list)


@dataclass
class SpecJudge:
    """Judges a plan + draft AC bundle before implementation begins."""

    agent: AgentLike

    async def evaluate(
        self,
        plan_text: str,
        acceptance_criteria: list[str],
        pending_concerns: list[Concern] | None = None,
    ) -> JudgeResult:
        pending = pending_concerns or []
        user_msg = _build_user_message(plan_text, acceptance_criteria, pending)

        try:
            raw = await self.agent.run(_SYSTEM_PROMPT, user_msg)
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("SpecJudge JSON parse failure: %s", exc)
            return _parse_failure_result(
                f"SpecJudge could not parse agent output: {exc}"
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("SpecJudge agent failure: %s", exc)
            return _parse_failure_result(f"SpecJudge agent error: {exc}")

        verdict_raw = data.get("verdict", "FAIL")
        verdict: Literal["PASS", "FAIL"] = "PASS" if verdict_raw == "PASS" else "FAIL"

        now = datetime.now(UTC)
        findings = [
            Concern(
                id=f"SPEC-JUDGE-{i:03d}",
                raised_in_phase="plan",
                raised_in_stage="spec_judge",
                severity=f["severity"],
                concern=f["concern"],
                raised_at=now,
                must_address_by="implement",
            )
            for i, f in enumerate(data.get("findings", []), start=1)
        ]
        return JudgeResult(verdict=verdict, findings=findings)


def _build_user_message(
    plan_text: str,
    acceptance_criteria: list[str],
    pending: list[Concern],
) -> str:
    ac_block = "\n".join(f"- {ac}" for ac in acceptance_criteria) or "(none)"
    pending_block = (
        "\n".join(
            f"- [{c.id}|{c.severity}] {c.concern} "
            f"(from {c.raised_in_phase}/{c.raised_in_stage})"
            for c in pending
        )
        or "(none)"
    )
    return (
        f"## Plan under review\n{plan_text}\n\n"
        f"## Draft acceptance criteria\n{ac_block}\n\n"
        f"## Pending concerns from earlier stages\n{pending_block}\n\n"
        f"Evaluate the AC against the plan. Output strict JSON only."
    )


def _parse_failure_result(detail: str) -> JudgeResult:
    return JudgeResult(
        verdict="FAIL",
        findings=[
            Concern(
                id="SPEC-JUDGE-001",
                raised_in_phase="plan",
                raised_in_stage="spec_judge",
                severity="HIGH",
                concern=detail,
                raised_at=datetime.now(UTC),
                must_address_by="implement",
            )
        ],
    )
