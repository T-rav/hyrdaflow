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
    async def test_subprocess_calls_base_runner_execute(self) -> None:
        """The wired subprocess delegates to BaseRunner._execute,
        passing the prompt built from _build_prompt and the repo_root
        cwd. Patches _execute (the BaseRunner method) instead of
        _run_reproducer_subprocess to verify the wiring at one level
        deeper than the other orchestration tests.
        """
        reproducer = _reproducer()
        body = (
            "Outcome: success\n"
            "Test_path: tests/regressions/test_issue_42.py\n"
            "Confidence: 0.9"
        )
        execute_calls: list[dict] = []

        async def _fake_execute(cmd, prompt, cwd, event_data, **kwargs):
            del kwargs
            execute_calls.append(
                {
                    "cmd": cmd,
                    "prompt": prompt,
                    "cwd": cwd,
                    "event_data": event_data,
                }
            )
            return _wrap(body)

        with (
            patch.object(BugReproducer, "_execute", side_effect=_fake_execute),
            patch.object(
                BugReproducer,
                "_build_command",
                return_value=["claude", "-p"],
            ),
        ):
            result = await reproducer.reproduce(_task())

        assert result.outcome == ReproductionOutcome.SUCCESS
        assert len(execute_calls) == 1
        # The prompt routed through _build_prompt — check task title,
        # body, the test path template, and the marker contract.
        prompt = execute_calls[0]["prompt"]
        assert "Bug: thing breaks" in prompt  # task title
        assert "when N=0 it crashes" in prompt  # task body
        assert "tests/regressions/test_issue_42.py" in prompt  # test path
        assert REPRO_START in prompt  # marker contract
        assert REPRO_END in prompt
        # Event data carries source + issue id for tracing.
        assert execute_calls[0]["event_data"]["source"] == "bug_reproducer"
        assert execute_calls[0]["event_data"]["issue"] == 42

    @pytest.mark.asyncio
    async def test_subprocess_passes_on_output_callback_that_terminates_on_marker(
        self,
    ) -> None:
        """The on_output callback returns True when REPRO_END appears
        in the accumulated stream. Catches a regression where the
        callback always returns False (subprocess never terminates).
        """
        reproducer = _reproducer()
        captured_callbacks: list = []

        async def _capture_execute(cmd, prompt, cwd, event_data, **kwargs):
            del cmd, prompt, cwd, event_data
            on_output = kwargs.get("on_output")
            if on_output is not None:
                captured_callbacks.append(on_output)
            return _wrap("Outcome: success")

        with (
            patch.object(BugReproducer, "_execute", side_effect=_capture_execute),
            patch.object(
                BugReproducer,
                "_build_command",
                return_value=["claude", "-p"],
            ),
        ):
            await reproducer.reproduce(_task())

        assert len(captured_callbacks) == 1
        callback = captured_callbacks[0]
        # No END marker yet → keep streaming.
        assert callback("partial reproducer output") is False
        # END marker present → terminate.
        assert callback(f"some output\n{REPRO_END}\n") is True
