"""Tests for precheck.py — shared precheck utilities."""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from escalation_gate import EscalationDecision
from precheck import (
    PrecheckResult,
    build_debug_command,
    build_subskill_command,
    parse_precheck_transcript,
    run_precheck_context,
)
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# PrecheckResult dataclass
# ---------------------------------------------------------------------------


class TestPrecheckResult:
    """Tests for the PrecheckResult frozen dataclass."""

    def test_precheck_result_has_expected_defaults(self) -> None:
        result = PrecheckResult()
        assert result.risk == "medium"
        assert result.confidence == 0.0
        assert result.escalate is False
        assert result.summary == ""
        assert result.parse_failed is True

    def test_custom_values(self) -> None:
        result = PrecheckResult(
            risk="high",
            confidence=0.85,
            escalate=True,
            summary="Risky change.",
            parse_failed=False,
        )
        assert result.risk == "high"
        assert result.confidence == 0.85
        assert result.escalate is True
        assert result.summary == "Risky change."
        assert result.parse_failed is False

    def test_precheck_result_is_immutable(self) -> None:
        result = PrecheckResult()
        with pytest.raises(FrozenInstanceError):
            result.risk = "high"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# parse_precheck_transcript
# ---------------------------------------------------------------------------


class TestParsePrecheckTranscript:
    """Tests for parse_precheck_transcript module-level function."""

    def test_all_fields_present(self) -> None:
        transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.95\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: All looks good.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.risk == "low"
        assert result.confidence == 0.95
        assert result.escalate is False
        assert result.summary == "All looks good."
        assert result.parse_failed is False

    def test_missing_risk_defaults_to_medium(self) -> None:
        transcript = (
            "PRECHECK_CONFIDENCE: 0.8\nPRECHECK_ESCALATE: no\nPRECHECK_SUMMARY: Fine.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.risk == "medium"
        assert result.parse_failed is True

    def test_missing_confidence_defaults_to_zero(self) -> None:
        transcript = (
            "PRECHECK_RISK: high\nPRECHECK_ESCALATE: yes\nPRECHECK_SUMMARY: Risky.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.confidence == 0.0
        assert result.parse_failed is True

    def test_escalate_yes(self) -> None:
        transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Needs debug.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.escalate is True

    def test_escalate_no(self) -> None:
        transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.9\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: OK.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.escalate is False

    def test_case_insensitive_parsing(self) -> None:
        transcript = (
            "precheck_risk: HIGH\n"
            "precheck_confidence: 0.42\n"
            "precheck_escalate: YES\n"
            "precheck_summary: Mixed case.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.risk == "high"
        assert result.confidence == 0.42
        assert result.escalate is True
        assert result.summary == "Mixed case."
        assert result.parse_failed is False

    def test_empty_string_returns_defaults(self) -> None:
        result = parse_precheck_transcript("")
        assert result.risk == "medium"
        assert result.confidence == 0.0
        assert result.escalate is False
        assert result.summary == ""
        assert result.parse_failed is True

    def test_missing_summary_only(self) -> None:
        transcript = (
            "PRECHECK_RISK: low\nPRECHECK_CONFIDENCE: 0.8\nPRECHECK_ESCALATE: no\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.risk == "low"
        assert result.confidence == 0.8
        assert result.escalate is False
        assert result.summary == ""
        assert result.parse_failed is True

    def test_missing_escalate_only(self) -> None:
        transcript = (
            "PRECHECK_RISK: medium\n"
            "PRECHECK_CONFIDENCE: 0.5\n"
            "PRECHECK_SUMMARY: Partial.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.escalate is False
        assert result.parse_failed is True

    def test_preamble_text_ignored(self) -> None:
        transcript = (
            "Some preamble.\n"
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.95\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: All looks good.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.risk == "low"
        assert result.confidence == 0.95
        assert result.parse_failed is False


# ---------------------------------------------------------------------------
# build_subskill_command / build_debug_command
# ---------------------------------------------------------------------------


class TestBuildSubskillCommand:
    """Tests for build_subskill_command."""

    def test_claude_backend(self) -> None:
        cfg = ConfigFactory.create(subskill_tool="claude", subskill_model="haiku")
        cmd = build_subskill_command(cfg)
        assert "claude" in cmd
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "haiku"

    def test_codex_backend(self) -> None:
        cfg = ConfigFactory.create(subskill_tool="codex", subskill_model="gpt-4")
        cmd = build_subskill_command(cfg)
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert cmd[cmd.index("--model") + 1] == "gpt-4"


class TestBuildDebugCommand:
    """Tests for build_debug_command."""

    def test_claude_backend(self) -> None:
        cfg = ConfigFactory.create(debug_tool="claude", debug_model="opus")
        cmd = build_debug_command(cfg)
        assert "claude" in cmd
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "opus"

    def test_codex_backend(self) -> None:
        cfg = ConfigFactory.create(debug_tool="codex", debug_model="gpt-5")
        cmd = build_debug_command(cfg)
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert cmd[cmd.index("--model") + 1] == "gpt-5"


# ---------------------------------------------------------------------------
# run_precheck_context
# ---------------------------------------------------------------------------


class TestRunPrecheckContext:
    """Tests for run_precheck_context shared orchestration."""

    @pytest.mark.asyncio
    async def test_disabled_returns_message(self) -> None:
        cfg = ConfigFactory.create(max_subskill_attempts=0)
        mock_execute = AsyncMock()
        result = await run_precheck_context(
            config=cfg,
            prompt="test prompt",
            diff="diff",
            execute=mock_execute,
            debug_message="DEBUG",
            logger=__import__("logging").getLogger("test"),
        )
        assert result == "Low-tier precheck disabled."
        mock_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_no_escalation(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            subskill_confidence_threshold=0.7,
            debug_escalation_enabled=False,
            repo_root=tmp_path / "repo",
        )
        valid_transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.95\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: All clear.\n"
        )
        mock_execute = AsyncMock(return_value=valid_transcript)
        result = await run_precheck_context(
            config=cfg,
            prompt="test prompt",
            diff="diff",
            execute=mock_execute,
            debug_message="DEBUG",
            logger=__import__("logging").getLogger("test"),
        )
        assert "Precheck risk: low" in result
        assert "Precheck confidence: 0.95" in result
        assert "Precheck summary: All clear." in result
        assert "Debug escalation: no" in result
        mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_on_parse_failure(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=3,
            debug_escalation_enabled=False,
            repo_root=tmp_path / "repo",
        )
        garbage = "No parseable fields here."
        valid_transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.9\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: Finally parsed.\n"
        )
        mock_execute = AsyncMock(side_effect=[garbage, garbage, valid_transcript])
        result = await run_precheck_context(
            config=cfg,
            prompt="test prompt",
            diff="diff",
            execute=mock_execute,
            debug_message="DEBUG",
            logger=__import__("logging").getLogger("test"),
        )
        assert mock_execute.call_count == 3
        assert "Precheck risk: low" in result
        assert "Precheck summary: Finally parsed." in result

    @pytest.mark.asyncio
    async def test_escalates_to_debug(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            debug_escalation_enabled=True,
            max_debug_attempts=1,
            subskill_confidence_threshold=0.7,
            repo_root=tmp_path / "repo",
        )
        high_risk_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Risky change.\n"
        )
        debug_transcript = "Debug: found critical issues."
        mock_execute = AsyncMock(side_effect=[high_risk_transcript, debug_transcript])
        result = await run_precheck_context(
            config=cfg,
            prompt="test prompt",
            diff="diff",
            execute=mock_execute,
            debug_message="DEBUG MODE: focus on ambiguity.",
            logger=__import__("logging").getLogger("test"),
        )
        assert mock_execute.call_count == 2
        assert "Precheck risk: high" in result
        assert "Debug escalation: yes" in result
        assert "Debug precheck transcript:" in result
        assert "Debug: found critical issues." in result
        assert "Escalation reasons:" in result

    @pytest.mark.asyncio
    async def test_no_debug_when_max_debug_zero(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            debug_escalation_enabled=True,
            max_debug_attempts=0,
            subskill_confidence_threshold=0.7,
            repo_root=tmp_path / "repo",
        )
        high_risk_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Risky.\n"
        )
        mock_execute = AsyncMock(return_value=high_risk_transcript)
        result = await run_precheck_context(
            config=cfg,
            prompt="test prompt",
            diff="diff",
            execute=mock_execute,
            debug_message="DEBUG",
            logger=__import__("logging").getLogger("test"),
        )
        assert mock_execute.call_count == 1
        assert "Debug escalation: yes" in result
        assert "Debug precheck transcript:" not in result

    @pytest.mark.asyncio
    async def test_exception_returns_fallback(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            repo_root=tmp_path / "repo",
        )
        mock_execute = AsyncMock(side_effect=RuntimeError("subprocess crashed"))
        result = await run_precheck_context(
            config=cfg,
            prompt="test prompt",
            diff="diff",
            execute=mock_execute,
            debug_message="DEBUG",
            logger=__import__("logging").getLogger("test"),
        )
        assert (
            result == "Low-tier precheck failed; continuing without precheck context."
        )

    @pytest.mark.asyncio
    async def test_debug_transcript_truncated_to_1000(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            debug_escalation_enabled=True,
            max_debug_attempts=1,
            subskill_confidence_threshold=0.7,
            repo_root=tmp_path / "repo",
        )
        high_risk_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Risky.\n"
        )
        long_debug = "D" * 2000
        mock_execute = AsyncMock(side_effect=[high_risk_transcript, long_debug])
        result = await run_precheck_context(
            config=cfg,
            prompt="test prompt",
            diff="diff",
            execute=mock_execute,
            debug_message="DEBUG",
            logger=__import__("logging").getLogger("test"),
        )
        assert "D" * 1000 in result
        assert "D" * 1001 not in result

    @pytest.mark.asyncio
    async def test_high_risk_diff_passes_true(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            repo_root=tmp_path / "repo",
        )
        precheck_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.5\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: risky auth change\n"
        )
        auth_diff = "diff --git a/src/auth/login.py b/src/auth/login.py\n+pass"
        mock_execute = AsyncMock(return_value=precheck_transcript)

        with patch(
            "precheck.should_escalate_debug",
            return_value=EscalationDecision(escalate=False, reasons=[]),
        ) as mock_escalate:
            await run_precheck_context(
                config=cfg,
                prompt="test prompt",
                diff=auth_diff,
                execute=mock_execute,
                debug_message="DEBUG",
                logger=__import__("logging").getLogger("test"),
            )

        mock_escalate.assert_called_once()
        assert mock_escalate.call_args[1]["high_risk_files_touched"] is True

    @pytest.mark.asyncio
    async def test_safe_diff_passes_false(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            repo_root=tmp_path / "repo",
        )
        precheck_transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.9\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: safe change\n"
        )
        safe_diff = "diff --git a/src/utils.py b/src/utils.py\n+pass"
        mock_execute = AsyncMock(return_value=precheck_transcript)

        with patch(
            "precheck.should_escalate_debug",
            return_value=EscalationDecision(escalate=False, reasons=[]),
        ) as mock_escalate:
            await run_precheck_context(
                config=cfg,
                prompt="test prompt",
                diff=safe_diff,
                execute=mock_execute,
                debug_message="DEBUG",
                logger=__import__("logging").getLogger("test"),
            )

        mock_escalate.assert_called_once()
        assert mock_escalate.call_args[1]["high_risk_files_touched"] is False

    @pytest.mark.asyncio
    async def test_debug_message_appended_to_prompt(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            debug_escalation_enabled=True,
            max_debug_attempts=1,
            subskill_confidence_threshold=0.7,
            repo_root=tmp_path / "repo",
        )
        high_risk_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Risky.\n"
        )
        mock_execute = AsyncMock(side_effect=[high_risk_transcript, "debug output"])
        await run_precheck_context(
            config=cfg,
            prompt="original prompt",
            diff="diff",
            execute=mock_execute,
            debug_message="DEBUG MODE: focus on ambiguity.",
            logger=__import__("logging").getLogger("test"),
        )
        # The debug call (second call) should include the debug message
        debug_call_prompt = mock_execute.call_args_list[1][0][1]
        assert "DEBUG MODE: focus on ambiguity." in debug_call_prompt
        assert "original prompt" in debug_call_prompt
