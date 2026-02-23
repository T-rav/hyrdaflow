"""Tests for credit exhaustion detection and pause mechanism."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventType
from models import PlanResult
from orchestrator import HydraFlowOrchestrator
from subprocess_util import (
    CreditExhaustedError,
    is_credit_exhaustion,
    parse_credit_resume_time,
)
from tests.helpers import ConfigFactory, make_streaming_proc

if TYPE_CHECKING:
    from config import HydraFlowConfig

from runner_utils import stream_claude_process

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_stream_kwargs(event_bus, **overrides):
    """Build default kwargs for stream_claude_process."""
    defaults = {
        "cmd": ["claude", "-p"],
        "prompt": "test prompt",
        "cwd": Path("/tmp/test"),
        "active_procs": set(),
        "event_bus": event_bus,
        "event_data": {"issue": 1},
        "logger": logging.getLogger("test"),
    }
    defaults.update(overrides)
    return defaults


def _mock_fetcher_noop(orch: HydraFlowOrchestrator) -> None:
    """Mock store and fetcher methods so no real gh CLI calls are made."""
    orch._store.get_triageable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.get_plannable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.get_reviewable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.start = AsyncMock()  # type: ignore[method-assign]
    orch._store.get_active_issues = lambda: {}  # type: ignore[method-assign]
    orch._fetcher.fetch_issue_by_number = AsyncMock(return_value=None)  # type: ignore[method-assign]
    orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]


# ===========================================================================
# subprocess_util — is_credit_exhaustion
# ===========================================================================


class TestIsCreditExhaustion:
    """Tests for the is_credit_exhaustion helper."""

    def test_detects_usage_limit_reached(self) -> None:
        assert is_credit_exhaustion("Your usage limit reached") is True

    def test_detects_credit_balance_too_low(self) -> None:
        assert is_credit_exhaustion("Your credit balance is too low") is True

    def test_does_not_detect_transient_rate_limit_as_credit_exhaustion(self) -> None:
        # rate_limit_error is a per-minute API rate limit, not a credit exhaustion
        assert is_credit_exhaustion("error: rate_limit_error") is False

    def test_returns_false_for_normal_text(self) -> None:
        assert is_credit_exhaustion("Everything is fine") is False

    def test_is_case_insensitive(self) -> None:
        assert is_credit_exhaustion("USAGE LIMIT REACHED") is True
        assert is_credit_exhaustion("Credit Balance Is Too Low") is True


# ===========================================================================
# subprocess_util — parse_credit_resume_time
# ===========================================================================


class TestParseCreditResumeTime:
    """Tests for parsing reset time from error messages."""

    def test_extracts_time_with_timezone(self) -> None:
        text = "Your limit will reset at 3pm (America/New_York)"
        result = parse_credit_resume_time(text)
        assert result is not None
        # Should be in UTC
        assert result.tzinfo is not None
        # The hour in ET should be 3pm = 15:00
        et = result.astimezone(ZoneInfo("America/New_York"))
        assert et.hour == 15

    def test_extracts_time_without_timezone(self) -> None:
        text = "Your limit will reset at 3am"
        result = parse_credit_resume_time(text)
        assert result is not None
        assert result.tzinfo is not None

    def test_returns_none_for_no_match(self) -> None:
        text = "Something went wrong with no time info"
        result = parse_credit_resume_time(text)
        assert result is None

    def test_handles_12hr_format_12pm(self) -> None:
        text = "reset at 12pm"
        result = parse_credit_resume_time(text)
        assert result is not None
        # 12pm should remain hour 12
        assert result.astimezone(UTC).minute == 0

    def test_handles_12hr_format_12am(self) -> None:
        text = "reset at 12am"
        result = parse_credit_resume_time(text)
        assert result is not None

    def test_handles_12hr_format_1am(self) -> None:
        text = "reset at 1am"
        result = parse_credit_resume_time(text)
        assert result is not None

    def test_reset_time_in_past_assumes_tomorrow(self) -> None:
        """If the parsed time is already past, assume tomorrow."""
        now_utc = datetime.now(UTC)
        # Use the current UTC hour — replace() sets minute/second to 0
        # which is guaranteed <= now, so the function must roll to tomorrow
        cur = now_utc.hour
        if cur == 0:
            h12, ampm = 12, "am"
        elif cur < 12:
            h12, ampm = cur, "am"
        elif cur == 12:
            h12, ampm = 12, "pm"
        else:
            h12, ampm = cur - 12, "pm"
        text = f"reset at {h12}{ampm} (UTC)"
        result = parse_credit_resume_time(text)
        assert result is not None
        # Should be tomorrow (since HH:00:00 <= now always)
        assert result > now_utc

    def test_returns_none_for_invalid_hour(self) -> None:
        """Hours outside 1-12 range should return None instead of crashing."""
        assert parse_credit_resume_time("reset at 0am") is None
        assert parse_credit_resume_time("reset at 13pm") is None
        assert parse_credit_resume_time("reset at 99am") is None

    def test_invalid_timezone_falls_back(self) -> None:
        """Unknown timezone should not crash, falls back to local time."""
        text = "reset at 3pm (Invalid/Timezone)"
        result = parse_credit_resume_time(text)
        # Should still parse (with fallback timezone)
        assert result is not None


# ===========================================================================
# subprocess_util — CreditExhaustedError
# ===========================================================================


class TestCreditExhaustedError:
    """Tests for the CreditExhaustedError exception class."""

    def test_inherits_runtime_error(self) -> None:
        err = CreditExhaustedError("credits out")
        assert isinstance(err, RuntimeError)

    def test_has_resume_at_attribute(self) -> None:
        resume = datetime.now(UTC) + timedelta(hours=3)
        err = CreditExhaustedError("credits out", resume_at=resume)
        assert err.resume_at == resume

    def test_resume_at_defaults_to_none(self) -> None:
        err = CreditExhaustedError("credits out")
        assert err.resume_at is None

    def test_message_is_preserved(self) -> None:
        err = CreditExhaustedError("API credit limit reached")
        assert str(err) == "API credit limit reached"


# ===========================================================================
# runner_utils — credit detection in stream_claude_process
# ===========================================================================


class TestStreamClaudeProcessCreditDetection:
    """Tests for credit exhaustion detection in stream_claude_process."""

    @pytest.mark.asyncio
    async def test_raises_credit_exhausted_on_stderr_match(self, event_bus) -> None:
        """stderr with credit message should raise CreditExhaustedError."""
        mock_create = make_streaming_proc(
            returncode=1,
            stdout="some output",
            stderr="Error: usage limit reached. Your limit will reset at 3am",
        )

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(CreditExhaustedError) as exc_info,
        ):
            await stream_claude_process(**_default_stream_kwargs(event_bus))

        assert exc_info.value.resume_at is not None

    @pytest.mark.asyncio
    async def test_raises_credit_exhausted_on_transcript_match(self, event_bus) -> None:
        """stdout with credit message should raise CreditExhaustedError."""
        mock_create = make_streaming_proc(
            returncode=0,
            stdout="credit balance is too low",
            stderr="",
        )

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(CreditExhaustedError),
        ):
            await stream_claude_process(**_default_stream_kwargs(event_bus))

    @pytest.mark.asyncio
    async def test_does_not_raise_for_normal_output(self, event_bus) -> None:
        """Normal output should not raise CreditExhaustedError."""
        mock_create = make_streaming_proc(returncode=0, stdout="All good", stderr="")

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await stream_claude_process(**_default_stream_kwargs(event_bus))

        assert result == "All good"

    @pytest.mark.asyncio
    async def test_no_false_positive_when_early_killed(self, event_bus) -> None:
        """Credit phrases in transcript should not raise when early_killed=True.

        If on_output kills the process early because it got what it needed,
        and the accumulated text happens to mention 'usage limit reached' as
        part of legitimate content, we must NOT trigger a credit pause.
        """
        # Transcript contains a credit phrase as part of legitimate content
        legitimate_output = "The API usage limit reached its maximum throughput"
        mock_create = make_streaming_proc(
            returncode=0,
            stdout=legitimate_output,
            stderr="",
        )

        # on_output returns True immediately -> early_killed=True
        def kill_immediately(_text: str) -> bool:
            return True

        with patch("asyncio.create_subprocess_exec", mock_create):
            # Should NOT raise CreditExhaustedError
            await stream_claude_process(
                **_default_stream_kwargs(event_bus, on_output=kill_immediately)
            )

    @pytest.mark.asyncio
    async def test_credit_exhausted_with_no_time_has_none_resume(
        self, event_bus
    ) -> None:
        """Credit exhaustion without reset time info should have resume_at=None."""
        mock_create = make_streaming_proc(
            returncode=1,
            stdout="",
            stderr="credit balance is too low",
        )

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(CreditExhaustedError) as exc_info,
        ):
            await stream_claude_process(**_default_stream_kwargs(event_bus))

        assert exc_info.value.resume_at is None


# ===========================================================================
# orchestrator — run_status with credits_paused
# ===========================================================================


class TestRunStatusCreditsPaused:
    """Tests for run_status returning 'credits_paused'."""

    def test_run_status_returns_credits_paused(self, config: HydraFlowConfig) -> None:
        """run_status returns 'credits_paused' when _credits_paused_until is in the future."""
        orch = HydraFlowOrchestrator(config)
        orch._credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
        assert orch.run_status == "credits_paused"

    def test_run_status_returns_running_after_credits_pause_expires(
        self, config: HydraFlowConfig
    ) -> None:
        """run_status does NOT return 'credits_paused' when the pause is in the past."""
        orch = HydraFlowOrchestrator(config)
        orch._credits_paused_until = datetime.now(UTC) - timedelta(hours=1)
        orch._running = True
        assert orch.run_status == "running"

    def test_run_status_auth_failed_takes_precedence_over_credits_paused(
        self, config: HydraFlowConfig
    ) -> None:
        """auth_failed should take precedence over credits_paused."""
        orch = HydraFlowOrchestrator(config)
        orch._auth_failed = True
        orch._credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
        assert orch.run_status == "auth_failed"

    def test_reset_clears_credits_paused(self, config: HydraFlowConfig) -> None:
        """reset() should clear _credits_paused_until."""
        orch = HydraFlowOrchestrator(config)
        orch._credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
        orch._stop_event.set()
        orch.reset()
        assert orch._credits_paused_until is None


# ===========================================================================
# orchestrator — credit exhaustion pause and resume
# ===========================================================================


class TestCreditExhaustionPauseResume:
    """Tests for credit exhaustion triggering pause and resume in the orchestrator."""

    @pytest.mark.asyncio
    async def test_credit_exhaustion_publishes_system_alert(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Credit exhaustion in a loop should publish a SYSTEM_ALERT event."""
        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        call_count = 0

        async def credit_failing_plan() -> list[PlanResult]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CreditExhaustedError(
                    "credits out",
                    resume_at=datetime.now(UTC) + timedelta(seconds=0.1),
                )
            return []

        orch._triager.triage_issues = AsyncMock()  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = credit_failing_plan  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def instant_sleep(seconds: int | float) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        # Stop after a short time so the test doesn't hang
        async def stop_soon() -> None:
            await asyncio.sleep(0.2)
            await orch.stop()

        await asyncio.gather(orch.run(), stop_soon())

        alert_events = [
            e for e in event_bus.get_history() if e.type == EventType.SYSTEM_ALERT
        ]
        # Should have at least the credit pause alert
        credit_alerts = [
            e for e in alert_events if "credit" in e.data.get("message", "").lower()
        ]
        assert len(credit_alerts) >= 1
        assert credit_alerts[0].data["source"] == "plan"

    @pytest.mark.asyncio
    async def test_credit_exhaustion_pauses_and_resumes(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Credit exhaustion should pause all loops and resume after the wait."""
        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        call_count = 0

        async def credit_failing_then_ok() -> list[PlanResult]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CreditExhaustedError(
                    "credits out",
                    resume_at=datetime.now(UTC) + timedelta(seconds=0.05),
                )
            return []

        orch._triager.triage_issues = AsyncMock()  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = credit_failing_then_ok  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def instant_sleep(seconds: int | float) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        async def stop_after_resume() -> None:
            # Wait long enough for the pause+resume cycle
            await asyncio.sleep(0.5)
            await orch.stop()

        await asyncio.gather(orch.run(), stop_after_resume())

        # After resume, the plan function should have been called again
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_credit_exhaustion_default_pause_when_no_time(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """When no resume time is parseable, a default pause duration is used."""
        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        call_count = 0

        async def credit_failing_no_time() -> list[PlanResult]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CreditExhaustedError("credits out", resume_at=None)
            return []

        orch._triager.triage_issues = AsyncMock()  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = credit_failing_no_time  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        sleep_durations: list[float] = []

        async def capture_sleep(seconds: int | float) -> None:
            sleep_durations.append(float(seconds))
            await asyncio.sleep(0)

        orch._sleep_or_stop = capture_sleep  # type: ignore[method-assign]

        async def stop_soon() -> None:
            await asyncio.sleep(0.2)
            await orch.stop()

        await asyncio.gather(orch.run(), stop_soon())

        # The first sleep should be for the default 5 hours + buffer
        credit_sleep = [s for s in sleep_durations if s > 3600]
        assert len(credit_sleep) >= 1
        # Should be approximately 5 hours + 1 minute buffer = 18060 seconds
        assert credit_sleep[0] > 17000  # roughly 5 hours

    @pytest.mark.asyncio
    async def test_credit_exhaustion_terminates_active_processes(
        self, config: HydraFlowConfig
    ) -> None:
        """Credit exhaustion should terminate all active subprocesses."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        terminate_calls = {"planners": 0, "agents": 0, "reviewers": 0, "hitl": 0}

        def track_planner_terminate() -> None:
            terminate_calls["planners"] += 1

        def track_agent_terminate() -> None:
            terminate_calls["agents"] += 1

        def track_reviewer_terminate() -> None:
            terminate_calls["reviewers"] += 1

        def track_hitl_terminate() -> None:
            terminate_calls["hitl"] += 1

        orch._planners.terminate = track_planner_terminate  # type: ignore[method-assign]
        orch._agents.terminate = track_agent_terminate  # type: ignore[method-assign]
        orch._reviewers.terminate = track_reviewer_terminate  # type: ignore[method-assign]
        orch._hitl_runner.terminate = track_hitl_terminate  # type: ignore[method-assign]

        call_count = 0

        async def credit_failing_triage() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CreditExhaustedError(
                    "credits out",
                    resume_at=datetime.now(UTC) + timedelta(seconds=0.05),
                )

        orch._triager.triage_issues = credit_failing_triage  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def instant_sleep(seconds: int | float) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        async def stop_soon() -> None:
            await asyncio.sleep(0.3)
            await orch.stop()

        await asyncio.gather(orch.run(), stop_soon())

        # All terminate methods should have been called at least once
        # (once during pause, once during final cleanup)
        assert terminate_calls["planners"] >= 1
        assert terminate_calls["agents"] >= 1
        assert terminate_calls["reviewers"] >= 1
        assert terminate_calls["hitl"] >= 1

    @pytest.mark.asyncio
    async def test_credit_pause_interrupted_by_stop(
        self, config: HydraFlowConfig
    ) -> None:
        """Calling stop() during a credit pause should interrupt the wait."""
        orch = HydraFlowOrchestrator(config)
        orch._prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        _mock_fetcher_noop(orch)

        async def credit_failing_implement() -> None:
            raise CreditExhaustedError(
                "credits out",
                resume_at=datetime.now(UTC) + timedelta(hours=5),
            )

        orch._triager.triage_issues = AsyncMock()  # type: ignore[method-assign]
        orch._planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._implementer.run_batch = credit_failing_implement  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def stop_quickly() -> None:
            await asyncio.sleep(0.2)
            await orch.stop()

        # Should complete quickly (not wait 5 hours) because stop() interrupts
        await asyncio.wait_for(
            asyncio.gather(orch.run(), stop_quickly()),
            timeout=5.0,
        )
        assert not orch.running
        # run_status must NOT be "credits_paused" after stop — it should clear
        # the pause state so the user can restart once the orchestrator is idle.
        assert orch.run_status != "credits_paused"


# ===========================================================================
# config — credit_pause_buffer_minutes
# ===========================================================================


class TestConfigCreditPauseBuffer:
    """Tests for the credit_pause_buffer_minutes config field."""

    def test_default_value(self) -> None:
        config = ConfigFactory.create()
        assert config.credit_pause_buffer_minutes == 1

    def test_custom_value(self) -> None:
        config = ConfigFactory.create(credit_pause_buffer_minutes=5)
        assert config.credit_pause_buffer_minutes == 5
