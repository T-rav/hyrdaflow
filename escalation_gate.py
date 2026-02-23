"""Shared debug-escalation gate for low-tier prechecks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EscalationDecision:
    """Decision payload for whether debug escalation is required."""

    escalate: bool
    reasons: list[str]


def should_escalate_debug(
    *,
    enabled: bool,
    confidence: float,
    confidence_threshold: float,
    parse_failed: bool,
    retry_count: int,
    max_subskill_attempts: int,
    risk: str = "",
    high_risk_files_touched: bool = False,
) -> EscalationDecision:
    """Return whether a stage should escalate to debug model/tooling."""
    if not enabled:
        return EscalationDecision(escalate=False, reasons=["disabled"])

    reasons: list[str] = []
    risk_norm = risk.strip().lower()

    if parse_failed:
        reasons.append("precheck_parse_failed")
    if confidence < confidence_threshold:
        reasons.append("low_confidence")
    if risk_norm in {"high", "critical"}:
        reasons.append(f"risk_{risk_norm}")
    if high_risk_files_touched:
        reasons.append("high_risk_files")
    if retry_count >= max_subskill_attempts:
        reasons.append("subskill_retries_exhausted")

    return EscalationDecision(escalate=bool(reasons), reasons=reasons)
