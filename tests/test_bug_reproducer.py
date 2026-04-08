"""Tests for bug_reproducer.BugReproducer (#6424)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bug_reproducer import REPRO_END, REPRO_START, BugReproducer
from models import ReproductionOutcome, Task

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def _task(issue_id: int = 42) -> Task:
    return Task(id=issue_id, title="Bug: thing breaks", body="when N=0 it crashes")


@dataclass
class _StubConfig:
    dry_run: bool = False
    repo_root: Path = Path("/tmp")
    state_dir: Path = Path("/tmp/state")
    log_dir: Path = Path("/tmp/logs")
    transcript_dir: Path = Path("/tmp/transcripts")


def _reproducer(*, dry_run: bool = False) -> BugReproducer:
    config = _StubConfig(dry_run=dry_run)
    bus = AsyncMock()
    reproducer = BugReproducer.__new__(BugReproducer)
    reproducer._config = config  # type: ignore[assignment]
    reproducer._bus = bus  # type: ignore[assignment]
    return reproducer


def _wrap(body: str) -> str:
    return f"preamble\n{REPRO_START}\n{body}\n{REPRO_END}\nsuffix"


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_includes_issue_id_in_test_path(self) -> None:
        prompt = BugReproducer._build_prompt(_task(issue_id=4242))
        assert "tests/regressions/test_issue_4242.py" in prompt

    def test_includes_issue_title_and_body(self) -> None:
        prompt = BugReproducer._build_prompt(_task())
        assert "Bug: thing breaks" in prompt
        assert "when N=0 it crashes" in prompt

    def test_lists_three_outcomes(self) -> None:
        prompt = BugReproducer._build_prompt(_task())
        for outcome in ("success", "partial", "unable"):
            assert f"**{outcome}**" in prompt

    def test_includes_marker_contract(self) -> None:
        prompt = BugReproducer._build_prompt(_task())
        assert REPRO_START in prompt
        assert REPRO_END in prompt

    def test_explicit_no_src_modification(self) -> None:
        """The prompt must explicitly forbid src/ writes — the
        reproducer is diagnostic only."""
        prompt = BugReproducer._build_prompt(_task())
        assert "src/" in prompt
        assert "Do NOT modify any file under `src/`" in prompt
        assert "Do NOT fix the bug" in prompt


# ---------------------------------------------------------------------------
# _parse_outcome
# ---------------------------------------------------------------------------


class TestParseOutcomeMarkers:
    def test_no_markers_returns_unable(self) -> None:
        result = BugReproducer._parse_outcome("nothing here")
        assert result.outcome == ReproductionOutcome.UNABLE
        assert result.test_path == ""
        assert result.confidence == 0.0

    def test_only_start_marker_returns_unable(self) -> None:
        result = BugReproducer._parse_outcome(f"{REPRO_START}\nOutcome: success")
        assert result.outcome == ReproductionOutcome.UNABLE

    def test_only_end_marker_returns_unable(self) -> None:
        result = BugReproducer._parse_outcome(f"Outcome: success\n{REPRO_END}")
        assert result.outcome == ReproductionOutcome.UNABLE

    def test_end_before_start_returns_unable(self) -> None:
        result = BugReproducer._parse_outcome(
            f"{REPRO_END}\nOutcome: success\n{REPRO_START}"
        )
        assert result.outcome == ReproductionOutcome.UNABLE


class TestParseOutcomeSuccess:
    def test_full_success_record(self) -> None:
        body = (
            "Outcome: success\n"
            "Test_path: tests/regressions/test_issue_42.py\n"
            "Confidence: 0.95\n"
            "Failing_output: AssertionError: expected 1, got 0"
        )
        result = BugReproducer._parse_outcome(_wrap(body))
        assert result.outcome == ReproductionOutcome.SUCCESS
        assert result.test_path == "tests/regressions/test_issue_42.py"
        assert result.confidence == pytest.approx(0.95)
        assert "AssertionError" in result.failing_output

    def test_outcome_case_insensitive(self) -> None:
        body = "Outcome: SUCCESS"
        result = BugReproducer._parse_outcome(_wrap(body))
        assert result.outcome == ReproductionOutcome.SUCCESS

    def test_test_path_alternative_keys(self) -> None:
        # The regex accepts `Test_path:` and `Test path:` (underscore
        # or whitespace separator) so reviewers don't have to bikeshed.
        body = "Outcome: success\nTest path: tests/regressions/test_x.py"
        result = BugReproducer._parse_outcome(_wrap(body))
        assert result.test_path == "tests/regressions/test_x.py"


class TestParseOutcomePartial:
    def test_partial_with_repro_script(self) -> None:
        body = (
            "Outcome: partial\n"
            "Repro_script: curl -X POST http://localhost:8000/foo\n"
            "Confidence: 0.6"
        )
        result = BugReproducer._parse_outcome(_wrap(body))
        assert result.outcome == ReproductionOutcome.PARTIAL
        assert "curl" in result.repro_script
        assert result.confidence == pytest.approx(0.6)


class TestParseOutcomeUnable:
    def test_unable_with_investigation(self) -> None:
        body = "Outcome: unable\nInvestigation: issue body lacks the stack trace needed"
        result = BugReproducer._parse_outcome(_wrap(body))
        assert result.outcome == ReproductionOutcome.UNABLE
        assert "stack trace" in result.investigation

    def test_unable_with_no_extra_keys_still_parses(self) -> None:
        body = "Outcome: unable"
        result = BugReproducer._parse_outcome(_wrap(body))
        assert result.outcome == ReproductionOutcome.UNABLE
        assert result.investigation == ""
        assert result.test_path == ""


class TestParseOutcomeRobustness:
    def test_unknown_outcome_falls_back_to_unable(self) -> None:
        body = "Outcome: bogus\nTest_path: tests/x.py"
        result = BugReproducer._parse_outcome(_wrap(body))
        # Default UNABLE preserved when the outcome string is invalid.
        assert result.outcome == ReproductionOutcome.UNABLE
        # But other keys still parse — partial parse is OK.
        assert result.test_path == "tests/x.py"

    def test_confidence_above_one_clamped(self) -> None:
        body = "Outcome: success\nConfidence: 1.5"
        result = BugReproducer._parse_outcome(_wrap(body))
        assert result.confidence == 1.0

    def test_confidence_below_zero_clamped(self) -> None:
        body = "Outcome: success\nConfidence: -0.3"
        result = BugReproducer._parse_outcome(_wrap(body))
        assert result.confidence == 0.0

    def test_malformed_confidence_defaults_to_zero(self) -> None:
        body = "Outcome: success\nConfidence: not-a-number"
        result = BugReproducer._parse_outcome(_wrap(body))
        assert result.confidence == 0.0

    def test_garbage_lines_ignored(self) -> None:
        body = (
            "Some prose at the top\n"
            "Outcome: success\n"
            "Random garbage line\n"
            "Test_path: tests/regressions/test_x.py\n"
            "More garbage"
        )
        result = BugReproducer._parse_outcome(_wrap(body))
        assert result.outcome == ReproductionOutcome.SUCCESS
        assert result.test_path == "tests/regressions/test_x.py"


# ---------------------------------------------------------------------------
# reproduce() orchestration
# ---------------------------------------------------------------------------


class TestReproduceOrchestration:
    @pytest.mark.asyncio
    async def test_dry_run_returns_unable_without_subprocess(self) -> None:
        reproducer = _reproducer(dry_run=True)
        result = await reproducer.reproduce(_task())
        assert result.outcome == ReproductionOutcome.UNABLE
        assert "Dry-run" in result.investigation

    @pytest.mark.asyncio
    async def test_subprocess_exception_recorded(self) -> None:
        reproducer = _reproducer()
        with patch.object(
            BugReproducer,
            "_run_reproducer_subprocess",
            side_effect=RuntimeError("agent crashed"),
        ):
            result = await reproducer.reproduce(_task())
        assert result.outcome == ReproductionOutcome.UNABLE
        assert result.error is not None
        assert "agent crashed" in result.error

    @pytest.mark.asyncio
    async def test_success_outcome_round_trip(self) -> None:
        reproducer = _reproducer()
        body = (
            "Outcome: success\n"
            "Test_path: tests/regressions/test_issue_42.py\n"
            "Confidence: 0.9\n"
            "Failing_output: ZeroDivisionError"
        )
        with patch.object(
            BugReproducer,
            "_run_reproducer_subprocess",
            return_value=_wrap(body),
        ):
            result = await reproducer.reproduce(_task())
        assert result.outcome == ReproductionOutcome.SUCCESS
        assert result.test_path == "tests/regressions/test_issue_42.py"
        assert result.confidence == pytest.approx(0.9)
        assert "ZeroDivisionError" in result.failing_output

    @pytest.mark.asyncio
    async def test_partial_outcome_round_trip(self) -> None:
        """Verify that a `partial` transcript flows through reproduce()
        correctly — the outcome lands as PARTIAL and repro_script is
        populated. Catches a regression where the field-by-field copy
        in reproduce() drops the repro_script line."""
        reproducer = _reproducer()
        body = (
            "Outcome: partial\n"
            "Repro_script: curl -X POST http://localhost:8000/foo\n"
            "Confidence: 0.6\n"
            "Investigation: manual reproduction works but no automated test"
        )
        with patch.object(
            BugReproducer,
            "_run_reproducer_subprocess",
            return_value=_wrap(body),
        ):
            result = await reproducer.reproduce(_task())
        assert result.outcome == ReproductionOutcome.PARTIAL
        assert "curl" in result.repro_script
        assert result.confidence == pytest.approx(0.6)
        assert "manual reproduction works" in result.investigation
        # Issue number is set from the orchestration call site, not the
        # parser default of 0.
        assert result.issue_number == 42

    @pytest.mark.asyncio
    async def test_unable_outcome_round_trip(self) -> None:
        reproducer = _reproducer()
        body = "Outcome: unable\nInvestigation: bug body has no repro steps"
        with patch.object(
            BugReproducer,
            "_run_reproducer_subprocess",
            return_value=_wrap(body),
        ):
            result = await reproducer.reproduce(_task())
        assert result.outcome == ReproductionOutcome.UNABLE
        assert "no repro steps" in result.investigation

    @pytest.mark.asyncio
    async def test_subprocess_default_raises_not_wired(self) -> None:
        reproducer = _reproducer()
        result = await reproducer.reproduce(_task())
        assert result.outcome == ReproductionOutcome.UNABLE
        assert result.error is not None
        assert "not wired" in result.error.lower()
