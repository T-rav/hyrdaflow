"""Tests for scripts.hydraflow_init."""

from __future__ import annotations

from scripts.hydraflow_init.modes import Mode, decide
from scripts.hydraflow_init.prompt import render


def _finding(
    status: str = "FAIL",
    severity: str = "STRUCTURAL",
    principle: str = "P1",
    check_id: str = "P1.1",
) -> dict:
    return {
        "check_id": check_id,
        "status": status,
        "severity": severity,
        "principle": principle,
        "source": "CLAUDE.md",
        "what": "something",
        "remediation": "do the thing",
        "message": "",
    }


# --- Mode decision --------------------------------------------------------


def test_no_structural_findings_is_incremental() -> None:
    findings = [_finding(status="PASS", severity="CULTURAL")]
    assert decide(findings) is Mode.INCREMENTAL


def test_most_structural_failing_is_greenfield() -> None:
    findings = [_finding(status="FAIL") for _ in range(10)]
    assert decide(findings) is Mode.GREENFIELD


def test_mostly_passing_is_incremental() -> None:
    findings = [_finding(status="PASS") for _ in range(8)] + [
        _finding(status="FAIL") for _ in range(2)
    ]
    assert decide(findings) is Mode.INCREMENTAL


def test_boundary_at_70_percent_is_greenfield() -> None:
    findings = [_finding(status="FAIL") for _ in range(7)] + [
        _finding(status="PASS") for _ in range(3)
    ]
    assert decide(findings) is Mode.GREENFIELD


# --- Prompt rendering ----------------------------------------------------


def test_greenfield_prompt_invokes_brainstorming() -> None:
    output = render(
        target="/repo",
        findings=[_finding()],
        summary={"pass": 0, "warn": 0, "fail": 1, "not_implemented": 0, "total": 1},
        mode=Mode.GREENFIELD,
        principle_filter=None,
        skip_brainstorm=False,
    )
    assert "superpowers:brainstorming" in output
    assert "superpowers:writing-plans" in output
    assert "make audit" in output


def test_greenfield_with_skip_brainstorm_omits_step() -> None:
    output = render(
        target="/repo",
        findings=[_finding()],
        summary={"fail": 1},
        mode=Mode.GREENFIELD,
        principle_filter=None,
        skip_brainstorm=True,
    )
    assert "superpowers:brainstorming" not in output
    assert "superpowers:writing-plans" in output


def test_incremental_prompt_skips_brainstorming() -> None:
    output = render(
        target="/repo",
        findings=[_finding()],
        summary={"fail": 1},
        mode=Mode.INCREMENTAL,
        principle_filter=None,
        skip_brainstorm=False,
    )
    assert "superpowers:brainstorming" not in output
    assert "superpowers:writing-plans" in output


def test_prompt_includes_only_actionable_findings() -> None:
    findings = [
        _finding(status="PASS", check_id="P1.1"),
        _finding(status="FAIL", check_id="P1.2"),
        _finding(status="WARN", check_id="P1.3"),
        _finding(status="NA", check_id="P1.4"),
    ]
    output = render(
        target="/repo",
        findings=findings,
        summary={"pass": 1},
        mode=Mode.INCREMENTAL,
        principle_filter=None,
        skip_brainstorm=False,
    )
    assert "P1.2" in output
    assert "P1.3" in output
    assert "P1.1" not in output
    assert "P1.4" not in output


def test_principle_filter_scopes_remediations() -> None:
    findings = [
        _finding(principle="P1", check_id="P1.1"),
        _finding(principle="P3", check_id="P3.1"),
    ]
    output = render(
        target="/repo",
        findings=findings,
        summary={"fail": 2},
        mode=Mode.INCREMENTAL,
        principle_filter="P3",
        skip_brainstorm=False,
    )
    assert "P3.1" in output
    assert "P1.1" not in output


def test_prompt_cites_source_for_each_finding() -> None:
    findings = [_finding(check_id="P5.7")]
    findings[0]["source"] = "docs/agents/quality-gates.md"
    output = render(
        target="/repo",
        findings=findings,
        summary={"fail": 1},
        mode=Mode.INCREMENTAL,
        principle_filter=None,
        skip_brainstorm=False,
    )
    assert "docs/agents/quality-gates.md" in output
    assert "Source:" in output


def test_empty_actionable_list_yields_green_message() -> None:
    findings = [_finding(status="PASS")]
    output = render(
        target="/repo",
        findings=findings,
        summary={"pass": 1},
        mode=Mode.INCREMENTAL,
        principle_filter=None,
        skip_brainstorm=False,
    )
    assert "audit is green" in output.lower()
