"""Shared precheck utilities for low-tier subskill and debug escalation.

Consolidates ``parse_precheck_transcript``, ``build_subskill_command``,
``build_debug_command``, and ``run_precheck_context`` which were
previously duplicated across acceptance_criteria.py, verification_judge.py,
and reviewer.py.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from escalation_gate import high_risk_diff_touched, should_escalate_debug

if TYPE_CHECKING:
    from config import HydraFlowConfig

#: Callback signature for executing a Claude subprocess.
#: Takes (command, prompt) and returns the transcript string.
ExecuteCallback = Callable[[list[str], str], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class PrecheckResult:
    """Parsed result of a low-tier precheck transcript."""

    risk: str = "medium"
    confidence: float = 0.0
    escalate: bool = False
    summary: str = ""
    parse_failed: bool = True


def parse_precheck_transcript(transcript: str) -> PrecheckResult:
    """Parse structured PRECHECK_* fields from a transcript string."""
    risk_match = re.search(
        r"PRECHECK_RISK:\s*(low|medium|high)",
        transcript,
        re.IGNORECASE,
    )
    confidence_match = re.search(
        r"PRECHECK_CONFIDENCE:\s*([0-9]*\.?[0-9]+)",
        transcript,
        re.IGNORECASE,
    )
    escalate_match = re.search(
        r"PRECHECK_ESCALATE:\s*(yes|no)",
        transcript,
        re.IGNORECASE,
    )
    summary_match = re.search(
        r"PRECHECK_SUMMARY:\s*(.*)",
        transcript,
        re.IGNORECASE,
    )
    parse_failed = not (
        risk_match and confidence_match and escalate_match and summary_match
    )
    risk = risk_match.group(1).lower() if risk_match else "medium"
    confidence = float(confidence_match.group(1)) if confidence_match else 0.0
    escalate = bool(escalate_match and escalate_match.group(1).lower() == "yes")
    summary = summary_match.group(1).strip() if summary_match else ""
    return PrecheckResult(
        risk=risk,
        confidence=confidence,
        escalate=escalate,
        summary=summary,
        parse_failed=parse_failed,
    )


def build_subskill_command(config: HydraFlowConfig) -> list[str]:
    """Build a CLI command for the low-tier subskill agent."""
    return build_agent_command(
        tool=config.subskill_tool,
        model=config.subskill_model,
    )


def build_debug_command(config: HydraFlowConfig) -> list[str]:
    """Build a CLI command for the debug escalation agent."""
    return build_agent_command(
        tool=config.debug_tool,
        model=config.debug_model,
    )


async def run_precheck_context(
    *,
    config: HydraFlowConfig,
    prompt: str,
    diff: str,
    execute: ExecuteCallback,
    debug_message: str,
    logger: logging.Logger,
    execute_debug: ExecuteCallback | None = None,
) -> str:
    """Run the shared precheck orchestration loop.

    1. If disabled (``max_subskill_attempts <= 0``), return immediately.
    2. Retry up to ``max_subskill_attempts`` times, breaking on successful parse.
    3. Evaluate escalation gate; optionally run debug agent.
    4. Return formatted context string.
    """
    if config.max_subskill_attempts <= 0:
        return "Low-tier precheck disabled."

    risk = "medium"
    confidence = config.subskill_confidence_threshold
    summary = ""
    parse_failed = False

    try:
        for _attempt in range(config.max_subskill_attempts):
            transcript = await execute(
                build_subskill_command(config),
                prompt,
            )
            result = parse_precheck_transcript(transcript)
            risk = result.risk
            confidence = result.confidence
            summary = result.summary
            parse_failed = result.parse_failed
            if not parse_failed:
                break
    except Exception:  # noqa: BLE001
        return "Low-tier precheck failed; continuing without precheck context."

    decision = should_escalate_debug(
        enabled=config.debug_escalation_enabled,
        confidence=confidence,
        confidence_threshold=config.subskill_confidence_threshold,
        parse_failed=parse_failed,
        retry_count=config.max_subskill_attempts,
        max_subskill_attempts=config.max_subskill_attempts,
        risk=risk,
        high_risk_files_touched=high_risk_diff_touched(diff),
    )

    context = [
        f"Precheck risk: {risk}",
        f"Precheck confidence: {confidence:.2f}",
        f"Precheck summary: {summary or 'N/A'}",
        f"Debug escalation: {'yes' if decision.escalate else 'no'}",
    ]

    if decision.escalate and config.max_debug_attempts > 0:
        _debug_execute = execute_debug if execute_debug is not None else execute
        debug_transcript = await _debug_execute(
            build_debug_command(config),
            prompt + f"\n\n{debug_message}",
        )
        context.append("Debug precheck transcript:")
        context.append(debug_transcript[:1000])
        context.append(f"Escalation reasons: {', '.join(decision.reasons)}")

    return "\n".join(context)
