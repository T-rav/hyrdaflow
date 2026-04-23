"""Tests for scripts.hydraflow_audit.runner."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
from scripts.hydraflow_audit import registry
from scripts.hydraflow_audit.models import (
    CheckContext,
    CheckSpec,
    Finding,
    Severity,
    Status,
)
from scripts.hydraflow_audit.runner import overall_exit_code, run_checks


@pytest.fixture(autouse=True)
def _isolate_registry() -> Iterator[None]:
    """Each test starts with an empty check registry."""
    registry._clear_for_tests()
    yield
    registry._clear_for_tests()


@pytest.fixture
def ctx(tmp_path: Path) -> CheckContext:
    return CheckContext(root=tmp_path)


def _spec(
    check_id: str = "P1.1", severity: Severity = Severity.STRUCTURAL
) -> CheckSpec:
    return CheckSpec(
        check_id=check_id,
        severity=severity,
        source="src",
        what="what",
        remediation="fix it",
        principle=check_id.split(".", 1)[0],
    )


def test_missing_check_function_yields_not_implemented(ctx: CheckContext) -> None:
    findings = run_checks([_spec()], ctx)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.status is Status.NOT_IMPLEMENTED
    assert finding.check_id == "P1.1"
    assert "ADR" in finding.message


def test_registered_check_is_called(ctx: CheckContext) -> None:
    @registry.register("P1.1")
    def _check(_: CheckContext) -> Finding:
        return Finding(
            check_id="P1.1",
            status=Status.PASS,
            severity=Severity.STRUCTURAL,
            principle="P1",
            source="",
            what="",
            remediation="",
            message="it's fine",
        )

    findings = run_checks([_spec()], ctx)
    assert findings[0].status is Status.PASS
    assert findings[0].message == "it's fine"


def test_spec_metadata_is_backfilled_when_check_leaves_it_blank(
    ctx: CheckContext,
) -> None:
    @registry.register("P1.1")
    def _check(_: CheckContext) -> Finding:
        return Finding(
            check_id="P1.1",
            status=Status.PASS,
            severity=None,  # type: ignore[arg-type]  # deliberately blank
            principle="",
            source="",
            what="",
            remediation="",
        )

    spec = _spec()
    findings = run_checks([spec], ctx)
    result = findings[0]
    assert result.source == spec.source
    assert result.what == spec.what
    assert result.remediation == spec.remediation
    assert result.principle == spec.principle
    assert result.severity is spec.severity


def test_exceptions_in_a_check_become_fail_findings(ctx: CheckContext) -> None:
    @registry.register("P1.1")
    def _broken(_: CheckContext) -> Finding:
        raise RuntimeError("boom")

    findings = run_checks([_spec()], ctx)
    finding = findings[0]
    assert finding.status is Status.FAIL
    assert "RuntimeError" in finding.message
    assert "boom" in finding.message


def test_overall_exit_code_zero_when_all_pass_or_na(ctx: CheckContext) -> None:
    @registry.register("P1.1")
    def _ok(_: CheckContext) -> Finding:
        return Finding(
            check_id="P1.1",
            status=Status.PASS,
            severity=Severity.STRUCTURAL,
            principle="P1",
            source="",
            what="",
            remediation="",
        )

    @registry.register("P1.2")
    def _na(_: CheckContext) -> Finding:
        return Finding(
            check_id="P1.2",
            status=Status.NA,
            severity=Severity.STRUCTURAL,
            principle="P1",
            source="",
            what="",
            remediation="",
        )

    findings = run_checks([_spec("P1.1"), _spec("P1.2")], ctx)
    assert overall_exit_code(findings) == 0


@pytest.mark.parametrize("bad", [Status.WARN, Status.FAIL, Status.NOT_IMPLEMENTED])
def test_overall_exit_code_nonzero_on_any_bad_finding(
    bad: Status, ctx: CheckContext
) -> None:
    @registry.register("P1.1")
    def _ok(_: CheckContext) -> Finding:
        return Finding(
            check_id="P1.1",
            status=Status.PASS,
            severity=Severity.STRUCTURAL,
            principle="P1",
            source="",
            what="",
            remediation="",
        )

    @registry.register("P1.2")
    def _bad(_: CheckContext) -> Finding:
        return Finding(
            check_id="P1.2",
            status=bad,
            severity=Severity.STRUCTURAL,
            principle="P1",
            source="",
            what="",
            remediation="",
        )

    findings = run_checks([_spec("P1.1"), _spec("P1.2")], ctx)
    assert overall_exit_code(findings) == 1
