"""Tests for DiagnosticRunner."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from models import DiagnosisResult, EscalationContext, Severity


class TestExtractJson:
    def test_extracts_from_code_block(self) -> None:
        from diagnostic_runner import _extract_json

        text = '```json\n{"key": "value"}\n```'
        assert _extract_json(text) == {"key": "value"}

    def test_extracts_bare_json(self) -> None:
        from diagnostic_runner import _extract_json

        text = '{"key": "value"}'
        assert _extract_json(text) == {"key": "value"}

    def test_returns_none_for_invalid(self) -> None:
        from diagnostic_runner import _extract_json

        assert _extract_json("not json at all") is None

    def test_extracts_from_plain_code_block(self) -> None:
        from diagnostic_runner import _extract_json

        text = '```\n{"key": "value"}\n```'
        assert _extract_json(text) == {"key": "value"}


class TestBuildDiagnosisPrompt:
    def test_includes_cause_and_phase(self) -> None:
        from diagnostic_runner import _build_diagnosis_prompt

        ctx = EscalationContext(cause="CI failed", origin_phase="review")
        prompt = _build_diagnosis_prompt(1, "Bug", "Fix it", ctx)
        assert "CI failed" in prompt
        assert "review" in prompt

    def test_includes_ci_logs_when_present(self) -> None:
        from diagnostic_runner import _build_diagnosis_prompt

        ctx = EscalationContext(
            cause="CI failed",
            origin_phase="review",
            ci_logs="FAIL test_foo.py",
        )
        prompt = _build_diagnosis_prompt(1, "Bug", "Fix it", ctx)
        assert "FAIL test_foo.py" in prompt

    def test_omits_empty_fields(self) -> None:
        from diagnostic_runner import _build_diagnosis_prompt

        ctx = EscalationContext(cause="test", origin_phase="review")
        prompt = _build_diagnosis_prompt(1, "Bug", "Fix it", ctx)
        assert "CI Logs" not in prompt
        assert "Review Feedback" not in prompt
        assert "PR Diff" not in prompt

    def test_includes_review_comments(self) -> None:
        from diagnostic_runner import _build_diagnosis_prompt

        ctx = EscalationContext(
            cause="review",
            origin_phase="review",
            review_comments=["Missing tests", "Wrong type"],
        )
        prompt = _build_diagnosis_prompt(1, "Bug", "Fix it", ctx)
        assert "Missing tests" in prompt
        assert "Wrong type" in prompt

    def test_includes_pr_diff(self) -> None:
        from diagnostic_runner import _build_diagnosis_prompt

        ctx = EscalationContext(
            cause="review",
            origin_phase="review",
            pr_diff="+ added line",
        )
        prompt = _build_diagnosis_prompt(1, "Bug", "Fix it", ctx)
        assert "added line" in prompt

    def test_includes_code_scanning_alerts(self) -> None:
        from diagnostic_runner import _build_diagnosis_prompt

        ctx = EscalationContext(
            cause="security",
            origin_phase="review",
            code_scanning_alerts=["SQL injection risk"],
        )
        prompt = _build_diagnosis_prompt(1, "Bug", "Fix it", ctx)
        assert "SQL injection risk" in prompt

    def test_includes_previous_attempts(self) -> None:
        from diagnostic_runner import _build_diagnosis_prompt
        from models import AttemptRecord

        ctx = EscalationContext(
            cause="ci",
            origin_phase="implement",
            previous_attempts=[
                AttemptRecord(
                    attempt_number=1,
                    changes_made=True,
                    error_summary="tests still failed",
                    timestamp="2026-04-05T00:00:00Z",
                )
            ],
        )
        prompt = _build_diagnosis_prompt(1, "Bug", "Fix it", ctx)
        assert "Attempt 1" in prompt
        assert "tests still failed" in prompt

    def test_truncates_agent_transcript(self) -> None:
        from diagnostic_runner import _build_diagnosis_prompt

        long_transcript = "x" * 5000
        ctx = EscalationContext(
            cause="ci",
            origin_phase="review",
            agent_transcript=long_transcript,
        )
        prompt = _build_diagnosis_prompt(1, "Bug", "Fix it", ctx)
        # 4000 chars max of transcript
        assert "x" * 4000 in prompt
        assert "x" * 4001 not in prompt

    def test_includes_issue_number(self) -> None:
        from diagnostic_runner import _build_diagnosis_prompt

        ctx = EscalationContext(cause="ci", origin_phase="review")
        prompt = _build_diagnosis_prompt(99, "My Bug", "Details", ctx)
        assert "Issue #99" in prompt


class TestDiagnosticRunner:
    @pytest.fixture
    def runner(self):
        from diagnostic_runner import DiagnosticRunner

        config = MagicMock()
        config.repo_root = "/tmp/repo"
        config.implementation_tool = "claude"
        config.model = "claude-opus-4-5"
        bus = MagicMock()
        return DiagnosticRunner(config=config, event_bus=bus)

    @pytest.mark.asyncio
    async def test_diagnose_parses_structured_result(self, runner, monkeypatch) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")
        diagnosis_json = json.dumps(
            {
                "root_cause": "Missing import",
                "severity": "P2",
                "fixable": True,
                "fix_plan": "Add import on line 5",
                "human_guidance": "Straightforward fix",
                "affected_files": ["src/app.py"],
            }
        )

        async def fake_execute(*args, **kwargs):
            return f"```json\n{diagnosis_json}\n```"

        monkeypatch.setattr(runner, "_execute", fake_execute)
        result = await runner.diagnose(
            issue_number=42, issue_title="Bug", issue_body="Fix it", context=ctx
        )
        assert isinstance(result, DiagnosisResult)
        assert result.severity == Severity.P2_FUNCTIONAL
        assert result.fixable is True
        assert result.root_cause == "Missing import"
        assert result.affected_files == ["src/app.py"]

    @pytest.mark.asyncio
    async def test_diagnose_returns_unfixable_on_parse_error(
        self, runner, monkeypatch
    ) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        async def fake_execute(*args, **kwargs):
            return "I couldn't figure it out"

        monkeypatch.setattr(runner, "_execute", fake_execute)
        result = await runner.diagnose(
            issue_number=42, issue_title="Bug", issue_body="Fix it", context=ctx
        )
        assert isinstance(result, DiagnosisResult)
        assert result.fixable is False
        assert "Manual review" in result.human_guidance

    @pytest.mark.asyncio
    async def test_diagnose_returns_unfixable_on_crash(
        self, runner, monkeypatch
    ) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        async def failing_execute(*args, **kwargs):
            raise RuntimeError("agent crashed")

        monkeypatch.setattr(runner, "_execute", failing_execute)
        result = await runner.diagnose(
            issue_number=42, issue_title="Bug", issue_body="Fix it", context=ctx
        )
        assert result.fixable is False
        assert "crashed" in result.root_cause.lower()

    @pytest.mark.asyncio
    async def test_diagnose_returns_partial_on_validation_failure(
        self, runner, monkeypatch
    ) -> None:
        """When JSON parses but model_validate fails, return partial result."""
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        async def fake_execute(*args, **kwargs):
            # Missing required fields — will fail model_validate
            return '```json\n{"root_cause": "Bad schema", "severity": "INVALID"}\n```'

        monkeypatch.setattr(runner, "_execute", fake_execute)
        result = await runner.diagnose(
            issue_number=42, issue_title="Bug", issue_body="Fix it", context=ctx
        )
        assert result.fixable is False
        assert result.root_cause == "Bad schema"
        assert "Manual review" in result.human_guidance

    @pytest.mark.asyncio
    async def test_fix_returns_success_when_quality_passes(
        self, runner, monkeypatch
    ) -> None:
        from models import LoopResult

        diagnosis = DiagnosisResult(
            root_cause="Missing import",
            severity=Severity.P2_FUNCTIONAL,
            fixable=True,
            fix_plan="Add import",
            human_guidance="Simple",
            affected_files=["src/app.py"],
        )

        async def fake_execute(*args, **kwargs):
            return "Fixed the import"

        async def fake_verify(path):
            return LoopResult(passed=True, summary="OK")

        monkeypatch.setattr(runner, "_execute", fake_execute)
        monkeypatch.setattr(runner, "_verify_quality", fake_verify)
        success, transcript = await runner.fix(
            42, "Bug", "Fix it", diagnosis, "/tmp/wt"
        )
        assert success is True
        assert transcript == "Fixed the import"

    @pytest.mark.asyncio
    async def test_fix_returns_failure_when_quality_fails(
        self, runner, monkeypatch
    ) -> None:
        from models import LoopResult

        diagnosis = DiagnosisResult(
            root_cause="Missing import",
            severity=Severity.P2_FUNCTIONAL,
            fixable=True,
            fix_plan="Add import",
            human_guidance="Simple",
            affected_files=["src/app.py"],
        )

        async def fake_execute(*args, **kwargs):
            return "Tried to fix"

        async def fake_verify(path):
            return LoopResult(passed=False, summary="Tests failed")

        monkeypatch.setattr(runner, "_execute", fake_execute)
        monkeypatch.setattr(runner, "_verify_quality", fake_verify)
        success, transcript = await runner.fix(
            42, "Bug", "Fix it", diagnosis, "/tmp/wt"
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_fix_returns_failure_on_crash(self, runner, monkeypatch) -> None:
        diagnosis = DiagnosisResult(
            root_cause="Missing import",
            severity=Severity.P2_FUNCTIONAL,
            fixable=True,
            fix_plan="Add import",
            human_guidance="Simple",
        )

        async def failing_execute(*args, **kwargs):
            raise RuntimeError("agent blew up")

        monkeypatch.setattr(runner, "_execute", failing_execute)
        success, transcript = await runner.fix(
            42, "Bug", "Fix it", diagnosis, "/tmp/wt"
        )
        assert success is False
        assert "crashed" in transcript.lower()

    @pytest.mark.asyncio
    async def test_diagnose_empty_transcript(self, runner, monkeypatch) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        async def fake_execute(*args, **kwargs):
            return ""

        monkeypatch.setattr(runner, "_execute", fake_execute)
        result = await runner.diagnose(
            issue_number=42, issue_title="Bug", issue_body="Fix it", context=ctx
        )
        assert result.fixable is False
        assert result.root_cause == "No output"
