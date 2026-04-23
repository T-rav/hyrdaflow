"""Dispatch check specs to registered check functions and collect findings."""

from __future__ import annotations

from . import registry
from .models import CheckContext, CheckSpec, Finding, Status


def run_checks(specs: list[CheckSpec], ctx: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    for spec in specs:
        findings.append(_run_one(spec, ctx))
    return findings


def _run_one(spec: CheckSpec, ctx: CheckContext) -> Finding:
    fn = registry.get(spec.check_id)
    if fn is None:
        return Finding(
            check_id=spec.check_id,
            status=Status.NOT_IMPLEMENTED,
            severity=spec.severity,
            principle=spec.principle,
            source=spec.source,
            what=spec.what,
            remediation=spec.remediation,
            message=(
                f"check {spec.check_id} has an ADR row but no implementation — "
                "the ADR and the audit have drifted"
            ),
        )
    try:
        result = fn(ctx)
    except Exception as exc:  # noqa: BLE001 — surface check crashes as findings
        return Finding(
            check_id=spec.check_id,
            status=Status.FAIL,
            severity=spec.severity,
            principle=spec.principle,
            source=spec.source,
            what=spec.what,
            remediation=spec.remediation,
            message=f"check raised {type(exc).__name__}: {exc}",
        )
    # Backfill metadata from the spec so check functions only set status + message.
    result.severity = result.severity or spec.severity
    result.principle = result.principle or spec.principle
    result.source = result.source or spec.source
    result.what = result.what or spec.what
    result.remediation = result.remediation or spec.remediation
    return result


def overall_exit_code(findings: list[Finding]) -> int:
    """0 if every finding is PASS or NA; 1 otherwise."""
    bad = {Status.FAIL, Status.WARN, Status.NOT_IMPLEMENTED}
    return 1 if any(f.status in bad for f in findings) else 0
