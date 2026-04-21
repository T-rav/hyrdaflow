"""Tests for scripts/audit_prompts.py — AuditTarget dataclass and prompt registry scaffold."""

from __future__ import annotations

from scripts.audit_prompts import AuditTarget


def test_audit_target_carries_metadata():
    target = AuditTarget(
        name="triage_build_prompt",
        builder_qualname="triage.Triage._build_prompt_with_stats",
        fixture_path="tests/fixtures/prompts/triage_build_prompt.json",
        category="Triage",
        call_site="src/triage.py:194",
    )
    assert target.name == "triage_build_prompt"
    assert target.category == "Triage"
    assert target.call_site == "src/triage.py:194"
