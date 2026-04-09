"""Tests for plan_reviewer.PlanReviewer (#6421).

Covers the pure helpers (prompt builder, findings parser, summary)
end-to-end without spawning subprocesses, plus the orchestration
``review`` entry point with the subprocess hook patched. The dry-run
shortcut and degenerate input paths are exercised against a real
runner instance built from a stub config.

Per CLAUDE.md → Avoided Patterns: when adding new fields to
PlanReview/PlanFinding, update the serialization tests in
test_swamp_lifecycle_models.py and the parser fixtures here together.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import (
    PlanFindingSeverity,
    PlanResult,
    PlanReview,
    Task,
)
from plan_reviewer import (
    PLAN_REVIEW_END,
    PLAN_REVIEW_START,
    REVIEW_DIMENSIONS,
    PlanReviewer,
)

# ---------------------------------------------------------------------------
# Stub fixtures — minimal Task / PlanResult / Config / EventBus
# ---------------------------------------------------------------------------


def _task(
    issue_id: int = 42, title: str = "Add foo", body: str = "do the thing"
) -> Task:
    return Task(id=issue_id, title=title, body=body)


def _plan_result(
    issue_id: int = 42,
    *,
    success: bool = True,
    plan: str = "PLAN_START\nstep 1\nPLAN_END",
) -> PlanResult:
    return PlanResult(issue_number=issue_id, success=success, plan=plan)


@dataclass
class _StubConfig:
    """Minimum config surface PlanReviewer needs at construction time."""

    dry_run: bool = False
    repo_root: Path = Path("/tmp")
    state_dir: Path = Path("/tmp/state")
    log_dir: Path = Path("/tmp/logs")
    transcript_dir: Path = Path("/tmp/transcripts")


def _reviewer(*, dry_run: bool = False) -> PlanReviewer:
    """Build a PlanReviewer without going through service_registry.

    BaseRunner only touches the methods we override here, so the stub
    config is enough — no SubprocessRunner, no EventBus consumers.
    """
    config = _StubConfig(dry_run=dry_run)
    bus = AsyncMock()
    # PlanReviewer inherits BaseRunner.__init__ which expects a real
    # HydraFlowConfig but only reads .dry_run / .repo_root / etc. on the
    # paths we exercise. We bypass __init__ entirely to avoid the type
    # gymnastics — PlanReviewer's review() method only touches
    # self._config (via the dry-run check) and self._log.
    reviewer = PlanReviewer.__new__(PlanReviewer)
    reviewer._config = config  # type: ignore[assignment]
    reviewer._bus = bus  # type: ignore[assignment]
    return reviewer


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_includes_issue_title_and_body(self) -> None:
        prompt = PlanReviewer._build_prompt(
            _task(title="Fix the widget", body="here is the body"),
            "the plan",
        )
        assert "Fix the widget" in prompt
        assert "here is the body" in prompt
        assert "the plan" in prompt

    def test_includes_all_review_dimensions(self) -> None:
        prompt = PlanReviewer._build_prompt(_task(), "plan")
        for dim in REVIEW_DIMENSIONS:
            assert f"- {dim}" in prompt

    def test_includes_marker_contract(self) -> None:
        prompt = PlanReviewer._build_prompt(_task(), "plan")
        assert PLAN_REVIEW_START in prompt
        assert PLAN_REVIEW_END in prompt

    def test_includes_severity_scale(self) -> None:
        prompt = PlanReviewer._build_prompt(_task(), "plan")
        for sev in ("critical", "high", "medium", "low", "info"):
            assert f"**{sev}**" in prompt

    def test_includes_issue_number(self) -> None:
        prompt = PlanReviewer._build_prompt(_task(issue_id=4242), "plan")
        assert "#4242" in prompt


# ---------------------------------------------------------------------------
# _parse_findings
# ---------------------------------------------------------------------------


def _wrap(body: str) -> str:
    """Wrap *body* in PLAN_REVIEW_START/END markers for parser tests."""
    return f"preamble\n{PLAN_REVIEW_START}\n{body}\n{PLAN_REVIEW_END}\nsuffix"


class TestParseFindings:
    def test_no_markers_returns_empty(self) -> None:
        assert PlanReviewer._parse_findings("nothing here") == []

    def test_empty_marker_block_returns_empty(self) -> None:
        assert PlanReviewer._parse_findings(_wrap("")) == []

    def test_marker_block_with_only_prose_returns_empty(self) -> None:
        body = "The plan looks reasonable.\nNo findings."
        assert PlanReviewer._parse_findings(_wrap(body)) == []

    def test_single_critical_finding(self) -> None:
        body = "- [critical] correctness: missing edge case for N=0"
        findings = PlanReviewer._parse_findings(_wrap(body))
        assert len(findings) == 1
        assert findings[0].severity == PlanFindingSeverity.CRITICAL
        assert findings[0].dimension == "correctness"
        assert findings[0].description == "missing edge case for N=0"
        assert findings[0].suggestion == ""

    def test_finding_with_suggestion(self) -> None:
        body = (
            "- [high] test_strategy: no test for the error path\n"
            "  Suggestion: add tests/regressions/test_error_path.py"
        )
        findings = PlanReviewer._parse_findings(_wrap(body))
        assert len(findings) == 1
        assert findings[0].severity == PlanFindingSeverity.HIGH
        assert findings[0].dimension == "test_strategy"
        assert "tests/regressions" in findings[0].suggestion

    def test_multiple_findings_preserved_in_order(self) -> None:
        body = (
            "- [critical] correctness: thing 1\n"
            "- [high] test_strategy: thing 2\n"
            "- [medium] scope_creep: thing 3"
        )
        findings = PlanReviewer._parse_findings(_wrap(body))
        assert [f.severity for f in findings] == [
            PlanFindingSeverity.CRITICAL,
            PlanFindingSeverity.HIGH,
            PlanFindingSeverity.MEDIUM,
        ]
        assert [f.dimension for f in findings] == [
            "correctness",
            "test_strategy",
            "scope_creep",
        ]

    def test_suggestion_attaches_to_in_flight_finding_only(self) -> None:
        body = (
            "- [critical] correctness: bad logic\n"
            "  Suggestion: rewrite the loop\n"
            "- [low] convention: minor"
        )
        findings = PlanReviewer._parse_findings(_wrap(body))
        assert len(findings) == 2
        assert findings[0].suggestion == "rewrite the loop"
        # The second finding has no suggestion — proves the suggestion
        # didn't bleed across finding boundaries.
        assert findings[1].suggestion == ""

    def test_unknown_severity_skipped(self) -> None:
        """An invalid severity tag must NOT crash the parser; it skips
        the malformed line and continues."""
        body = (
            "- [bogus] correctness: invalid severity\n- [high] test_strategy: real one"
        )
        findings = PlanReviewer._parse_findings(_wrap(body))
        # Only the valid finding survives.
        assert len(findings) == 1
        assert findings[0].dimension == "test_strategy"

    def test_case_insensitive_severity(self) -> None:
        body = "- [HIGH] correctness: shout case"
        findings = PlanReviewer._parse_findings(_wrap(body))
        assert len(findings) == 1
        assert findings[0].severity == PlanFindingSeverity.HIGH

    def test_garbage_lines_in_marker_block_ignored(self) -> None:
        body = (
            "Some prose at the top.\n"
            "- [high] correctness: real finding\n"
            "Random other line that doesn't parse.\n"
            "  Suggestion: fix it\n"
            "Another stray line."
        )
        findings = PlanReviewer._parse_findings(_wrap(body))
        assert len(findings) == 1
        assert findings[0].suggestion == "fix it"

    def test_only_start_marker_returns_empty(self) -> None:
        transcript = f"{PLAN_REVIEW_START}\n- [high] x: y"
        assert PlanReviewer._parse_findings(transcript) == []

    def test_only_end_marker_returns_empty(self) -> None:
        transcript = f"- [high] x: y\n{PLAN_REVIEW_END}"
        assert PlanReviewer._parse_findings(transcript) == []

    def test_end_before_start_returns_empty(self) -> None:
        transcript = f"{PLAN_REVIEW_END}\n- [high] x: y\n{PLAN_REVIEW_START}"
        assert PlanReviewer._parse_findings(transcript) == []


# ---------------------------------------------------------------------------
# _summarize_findings
# ---------------------------------------------------------------------------


class TestSummarizeFindings:
    def test_empty_returns_clean_message(self) -> None:
        assert "clean" in PlanReviewer._summarize_findings([]).lower()

    def test_counts_by_severity(self) -> None:
        from models import PlanFinding

        findings = [
            PlanFinding(
                severity=PlanFindingSeverity.CRITICAL,
                dimension="correctness",
                description="x",
            ),
            PlanFinding(
                severity=PlanFindingSeverity.CRITICAL,
                dimension="security",
                description="x",
            ),
            PlanFinding(
                severity=PlanFindingSeverity.HIGH,
                dimension="test_strategy",
                description="x",
            ),
        ]
        summary = PlanReviewer._summarize_findings(findings)
        assert "2 critical" in summary
        assert "1 high" in summary

    def test_omits_zero_count_severities(self) -> None:
        from models import PlanFinding

        findings = [
            PlanFinding(
                severity=PlanFindingSeverity.LOW,
                dimension="convention",
                description="x",
            ),
        ]
        summary = PlanReviewer._summarize_findings(findings)
        assert "1 low" in summary
        assert "critical" not in summary
        assert "high" not in summary


# ---------------------------------------------------------------------------
# review() orchestration
# ---------------------------------------------------------------------------


class TestReviewOrchestration:
    @pytest.mark.asyncio
    async def test_dry_run_returns_clean_review_without_subprocess(self) -> None:
        reviewer = _reviewer(dry_run=True)
        result = await reviewer.review(_task(), _plan_result())
        assert result.success is True
        assert result.is_clean is True
        assert result.findings == []
        assert "Dry-run" in result.summary
        # plan_version defaults to 1 when not passed.
        assert result.plan_version == 1

    @pytest.mark.asyncio
    async def test_review_skipped_when_plan_failed(self) -> None:
        reviewer = _reviewer()
        plan = _plan_result(success=False, plan="")
        result = await reviewer.review(_task(), plan)
        assert result.success is False
        assert result.error == "no plan to review"
        assert result.findings == []

    @pytest.mark.asyncio
    async def test_review_skipped_when_plan_text_empty(self) -> None:
        reviewer = _reviewer()
        plan = _plan_result(success=True, plan="")
        result = await reviewer.review(_task(), plan)
        assert result.success is False
        assert result.error == "no plan to review"

    @pytest.mark.asyncio
    async def test_subprocess_exception_recorded_as_error(self) -> None:
        reviewer = _reviewer()
        with patch.object(
            PlanReviewer,
            "_run_review_subprocess",
            side_effect=RuntimeError("agent crashed"),
        ):
            result = await reviewer.review(_task(), _plan_result())
        assert result.success is False
        assert result.error is not None
        assert "agent crashed" in result.error
        assert result.findings == []

    @pytest.mark.asyncio
    async def test_clean_review_passes_through(self) -> None:
        """A reviewer transcript with empty markers yields a clean review."""
        reviewer = _reviewer()
        transcript = f"{PLAN_REVIEW_START}\n{PLAN_REVIEW_END}"
        with patch.object(
            PlanReviewer,
            "_run_review_subprocess",
            return_value=transcript,
        ):
            result = await reviewer.review(_task(), _plan_result())
        assert result.success is True
        assert result.is_clean is True
        assert result.has_blocking_findings is False
        assert result.findings == []

    @pytest.mark.asyncio
    async def test_critical_finding_blocks_review(self) -> None:
        reviewer = _reviewer()
        body = "- [critical] correctness: bad logic"
        transcript = f"{PLAN_REVIEW_START}\n{body}\n{PLAN_REVIEW_END}"
        with patch.object(
            PlanReviewer,
            "_run_review_subprocess",
            return_value=transcript,
        ):
            result = await reviewer.review(_task(), _plan_result())
        assert result.success is True  # the run completed
        assert result.is_clean is False  # but the plan is blocked
        assert result.has_blocking_findings is True
        assert len(result.findings) == 1

    @pytest.mark.asyncio
    async def test_medium_finding_does_not_block(self) -> None:
        reviewer = _reviewer()
        body = "- [medium] scope_creep: nice-to-have refactor"
        transcript = f"{PLAN_REVIEW_START}\n{body}\n{PLAN_REVIEW_END}"
        with patch.object(
            PlanReviewer,
            "_run_review_subprocess",
            return_value=transcript,
        ):
            result = await reviewer.review(_task(), _plan_result())
        assert result.is_clean is True
        assert len(result.findings) == 1

    @pytest.mark.asyncio
    async def test_plan_version_is_propagated(self) -> None:
        reviewer = _reviewer()
        transcript = f"{PLAN_REVIEW_START}\n{PLAN_REVIEW_END}"
        with patch.object(
            PlanReviewer,
            "_run_review_subprocess",
            return_value=transcript,
        ):
            result = await reviewer.review(_task(), _plan_result(), plan_version=3)
        assert result.plan_version == 3

    @pytest.mark.asyncio
    async def test_subprocess_calls_base_runner_execute(self) -> None:
        """The wired subprocess delegates to BaseRunner._execute,
        passing the prompt built from _build_prompt and the repo_root
        cwd. Patches _execute (the BaseRunner method) instead of
        _run_review_subprocess to verify the wiring at one level
        deeper than the other orchestration tests.
        """
        reviewer = _reviewer()
        plan = _plan_result()

        clean_transcript = f"{PLAN_REVIEW_START}\n{PLAN_REVIEW_END}"
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
            return clean_transcript

        # Patch _execute and _build_command — _build_command needs a
        # real config attribute (planner_tool/planner_model) which the
        # stub config lacks, so we stub it.
        with (
            patch.object(PlanReviewer, "_execute", side_effect=_fake_execute),
            patch.object(PlanReviewer, "_build_command", return_value=["claude", "-p"]),
        ):
            result = await reviewer.review(_task(), plan)

        assert result.success is True
        assert result.is_clean is True
        assert len(execute_calls) == 1
        # The prompt routed through _build_prompt — check the issue
        # title, body, plan text, and marker contract are present
        # so a regression that drops _build_prompt's output (e.g.
        # passing prompt="") would fail this test.
        prompt = execute_calls[0]["prompt"]
        assert "Add foo" in prompt  # task title
        assert "do the thing" in prompt  # task body
        assert "step 1" in prompt  # plan text
        assert PLAN_REVIEW_START in prompt  # marker contract
        assert PLAN_REVIEW_END in prompt
        # Event data carries source + issue id for tracing.
        assert execute_calls[0]["event_data"]["source"] == "plan_reviewer"
        assert execute_calls[0]["event_data"]["issue"] == 42

    @pytest.mark.asyncio
    async def test_subprocess_passes_on_output_callback_that_terminates_on_marker(
        self,
    ) -> None:
        """The on_output callback passed to _execute returns True when
        PLAN_REVIEW_END appears in the accumulated stream. A regression
        where the callback always returns False would let the
        subprocess run forever; this test catches that.
        """
        reviewer = _reviewer()
        captured_callbacks: list = []

        async def _capture_execute(cmd, prompt, cwd, event_data, **kwargs):
            del cmd, prompt, cwd, event_data
            on_output = kwargs.get("on_output")
            if on_output is not None:
                captured_callbacks.append(on_output)
            return f"{PLAN_REVIEW_START}\n{PLAN_REVIEW_END}"

        with (
            patch.object(PlanReviewer, "_execute", side_effect=_capture_execute),
            patch.object(PlanReviewer, "_build_command", return_value=["claude", "-p"]),
        ):
            await reviewer.review(_task(), _plan_result())

        assert len(captured_callbacks) == 1
        callback = captured_callbacks[0]
        # No END marker yet → keep streaming.
        assert callback("partial output\nsome prose") is False
        # END marker present → terminate.
        assert callback(f"some output\n{PLAN_REVIEW_END}\n") is True


# ---------------------------------------------------------------------------
# Integration with PlanReview model gating
# ---------------------------------------------------------------------------


class TestPlanReviewModelGating:
    """End-to-end: parse a transcript, build a PlanReview, confirm the
    `is_clean` / `has_blocking_findings` properties surface the right
    verdict for the route-back gate."""

    def test_high_finding_blocks(self) -> None:
        body = "- [high] test_strategy: missing regression test"
        review = PlanReview(
            issue_number=42,
            success=True,
            findings=PlanReviewer._parse_findings(_wrap(body)),
        )
        assert review.has_blocking_findings is True
        assert review.is_clean is False

    def test_low_only_does_not_block(self) -> None:
        body = "- [low] convention: rename for clarity"
        review = PlanReview(
            issue_number=42,
            success=True,
            findings=PlanReviewer._parse_findings(_wrap(body)),
        )
        assert review.has_blocking_findings is False
        assert review.is_clean is True
