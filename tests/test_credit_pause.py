"""Tests for credit exhaustion detection and pause mechanism."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable
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
from tests.helpers import ConfigFactory, make_streaming_proc, mock_fetcher_noop

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


async def _poll_then_stop(
    condition: Callable[[], bool],
    orch: HydraFlowOrchestrator,
    *,
    max_iters: int = 20000,
    timeout_s: float = 15.0,
) -> None:
    """Poll *condition* with zero-sleep yields, then stop the orchestrator.

    Raises AssertionError if *condition* is still False after *max_iters*
    iterations so that test failures point at the unmet condition rather
    than at downstream assertions.
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    iters = 0
    while iters < max_iters and asyncio.get_running_loop().time() < deadline:
        if condition():
            break
        iters += 1
        await asyncio.sleep(0)
    else:
        raise AssertionError(
            "_poll_then_stop: condition never became True "
            f"after {iters} iterations in {timeout_s:.2f}s"
        )
    await orch.stop()


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

    def test_detects_youve_hit_your_limit(self) -> None:
        assert is_credit_exhaustion("You've hit your limit · resets 5am") is True

    def test_is_case_insensitive(self) -> None:
        assert is_credit_exhaustion("USAGE LIMIT REACHED") is True
        assert is_credit_exhaustion("Credit Balance Is Too Low") is True
        assert is_credit_exhaustion("YOU'VE HIT YOUR LIMIT") is True

    def test_detects_hit_your_usage_limit(self) -> None:
        """Exact message from Claude CLI when quota is exhausted."""
        assert (
            is_credit_exhaustion(
                "You've hit your usage limit. To get more access now, "
                "send a request to your admin or try again at 3:29 PM."
            )
            is True
        )


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

    def test_extracts_resets_format(self) -> None:
        """Matches 'resets 5am (America/Denver)' — no 'at', verb is 'resets'."""
        text = "You've hit your limit · resets 5am (America/Denver)"
        result = parse_credit_resume_time(text)
        assert result is not None
        denver = result.astimezone(ZoneInfo("America/Denver"))
        assert denver.hour == 5

    def test_extracts_resets_at_format(self) -> None:
        """Matches 'resets at 5am' — 'resets' + 'at'."""
        text = "resets at 5am"
        result = parse_credit_resume_time(text)
        assert result is not None

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
            result = await stream_claude_process(
                **_default_stream_kwargs(event_bus, on_output=kill_immediately)
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_raises_credit_exhausted_on_hit_limit_message(
        self, event_bus
    ) -> None:
        """'You've hit your limit' in stdout triggers CreditExhaustedError with parsed resume_at."""
        mock_create = make_streaming_proc(
            returncode=1,
            stdout="You've hit your limit · resets 5am (America/Denver)",
            stderr="",
        )

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(CreditExhaustedError) as exc_info,
        ):
            await stream_claude_process(**_default_stream_kwargs(event_bus))

        assert exc_info.value.resume_at is not None
        denver = exc_info.value.resume_at.astimezone(ZoneInfo("America/Denver"))
        assert denver.hour == 5

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

    def test_reset_clears_credit_resume_event(self, config: HydraFlowConfig) -> None:
        """reset() must clear _credit_resume_event to avoid stale-event bugs on restart."""
        orch = HydraFlowOrchestrator(config)
        orch._credit_resume_event.set()
        orch.reset()
        assert not orch._credit_resume_event.is_set()


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
        orch._svc.prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        mock_fetcher_noop(orch)

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

        orch._svc.triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._svc.planner_phase.plan_issues = credit_failing_plan  # type: ignore[method-assign]
        orch._svc.implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def instant_sleep(seconds: int | float) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        await asyncio.wait_for(
            asyncio.gather(
                orch.run(),
                _poll_then_stop(
                    lambda: any(
                        e.type == EventType.SYSTEM_ALERT
                        and "credit" in e.data.get("message", "").lower()
                        for e in event_bus.get_history()
                    ),
                    orch,
                ),
            ),
            timeout=20.0,
        )

        alert_events = [
            e for e in event_bus.get_history() if e.type == EventType.SYSTEM_ALERT
        ]
        # Should have at least the credit pause alert
        credit_alerts = [
            e for e in alert_events if "credit" in e.data.get("message", "").lower()
        ]
        assert len(credit_alerts) >= 1
        assert credit_alerts[0].data["source"] == "plan"
        assert "resume_at" in credit_alerts[0].data
        # resume_at should be a valid ISO 8601 timestamp
        from datetime import datetime as _dt

        _dt.fromisoformat(credit_alerts[0].data["resume_at"])
        # regression: UTC time must NOT be embedded in the message string (issue #2665)
        assert "UTC" not in credit_alerts[0].data["message"]

    @pytest.mark.asyncio
    async def test_credit_exhaustion_pauses_and_resumes(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Credit exhaustion should pause all loops and resume after the wait."""
        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch._svc.prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        mock_fetcher_noop(orch)

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

        orch._svc.triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._svc.planner_phase.plan_issues = credit_failing_then_ok  # type: ignore[method-assign]
        orch._svc.implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def instant_sleep(seconds: int | float) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        async def instant_resume(_resume_at: datetime) -> None:
            await asyncio.sleep(0)

        orch._sleep_until_resume = instant_resume  # type: ignore[method-assign]

        await asyncio.wait_for(
            asyncio.gather(
                orch.run(),
                _poll_then_stop(lambda: call_count >= 2, orch),
            ),
            timeout=20.0,
        )

        # After resume, the plan function should have been called again
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_credit_exhaustion_default_pause_when_no_time(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """When no resume time is parseable, a default pause duration is used."""
        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch._svc.prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        mock_fetcher_noop(orch)

        call_count = 0

        async def credit_failing_no_time() -> list[PlanResult]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CreditExhaustedError("credits out", resume_at=None)
            return []

        orch._svc.triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._svc.planner_phase.plan_issues = credit_failing_no_time  # type: ignore[method-assign]
        orch._svc.implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        resume_times: list[datetime] = []

        async def capture_resume(resume_at: datetime) -> None:
            resume_times.append(resume_at)

        async def instant_sleep(seconds: int | float) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]
        orch._sleep_until_resume = capture_resume  # type: ignore[method-assign]

        await asyncio.wait_for(
            asyncio.gather(
                orch.run(),
                _poll_then_stop(lambda: len(resume_times) >= 1, orch),
            ),
            timeout=20.0,
        )

        # The resume time should be approximately 5 hours + 1 minute buffer from now
        assert len(resume_times) >= 1
        pause_seconds = (resume_times[0] - datetime.now(UTC)).total_seconds()
        assert pause_seconds > 17000  # roughly 5 hours

    @pytest.mark.asyncio
    async def test_credit_exhaustion_terminates_active_processes(
        self, config: HydraFlowConfig
    ) -> None:
        """Credit exhaustion should terminate all active subprocesses."""
        orch = HydraFlowOrchestrator(config)
        orch._svc.prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        mock_fetcher_noop(orch)

        terminate_calls = {"planners": 0, "agents": 0, "reviewers": 0, "hitl": 0}

        def track_planner_terminate() -> None:
            terminate_calls["planners"] += 1

        def track_agent_terminate() -> None:
            terminate_calls["agents"] += 1

        def track_reviewer_terminate() -> None:
            terminate_calls["reviewers"] += 1

        def track_hitl_terminate() -> None:
            terminate_calls["hitl"] += 1

        orch._svc.planners.terminate = track_planner_terminate  # type: ignore[method-assign]
        orch._svc.agents.terminate = track_agent_terminate  # type: ignore[method-assign]
        orch._svc.reviewers.terminate = track_reviewer_terminate  # type: ignore[method-assign]
        orch._svc.hitl_runner.terminate = track_hitl_terminate  # type: ignore[method-assign]

        call_count = 0

        async def credit_failing_triage() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CreditExhaustedError(
                    "credits out",
                    resume_at=datetime.now(UTC) + timedelta(seconds=0.05),
                )

        orch._svc.triager.triage_issues = credit_failing_triage  # type: ignore[method-assign]
        orch._svc.planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._svc.implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def instant_sleep(seconds: int | float) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        await asyncio.wait_for(
            asyncio.gather(
                orch.run(),
                _poll_then_stop(
                    lambda: all(v >= 1 for v in terminate_calls.values()), orch
                ),
            ),
            timeout=20.0,
        )

        # All terminate methods should have been called at least once
        # (once during pause, once during final cleanup)
        assert terminate_calls["planners"] >= 1
        assert terminate_calls["agents"] >= 1
        assert terminate_calls["reviewers"] >= 1
        assert terminate_calls["hitl"] >= 1

    def test_clear_credit_pause_sets_event_and_clears_timestamp(
        self, config: HydraFlowConfig
    ) -> None:
        """clear_credit_pause() should set the resume event and clear _credits_paused_until."""
        orch = HydraFlowOrchestrator(config)
        orch._credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
        orch.clear_credit_pause()
        assert orch._credits_paused_until is None
        assert orch._credit_resume_event.is_set()

    @pytest.mark.asyncio
    async def test_sleep_until_resume_wakes_on_credit_resume_event(
        self, config: HydraFlowConfig
    ) -> None:
        """_sleep_until_resume should return early when _credit_resume_event is set."""
        orch = HydraFlowOrchestrator(config)
        resume_at = datetime.now(UTC) + timedelta(hours=5)

        async def set_resume_event() -> None:
            await asyncio.sleep(0.05)
            orch._credit_resume_event.set()

        asyncio.create_task(set_resume_event())
        # Should return in ~0.05s, not 5 hours
        await asyncio.wait_for(orch._sleep_until_resume(resume_at), timeout=5.0)

    @pytest.mark.asyncio
    async def test_credit_pause_interrupted_by_stop(
        self, config: HydraFlowConfig
    ) -> None:
        """Calling stop() during a credit pause should interrupt the wait."""
        orch = HydraFlowOrchestrator(config)
        orch._svc.prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        mock_fetcher_noop(orch)

        async def credit_failing_implement() -> None:
            raise CreditExhaustedError(
                "credits out",
                resume_at=datetime.now(UTC) + timedelta(hours=5),
            )

        orch._svc.triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._svc.planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._svc.implementer.run_batch = credit_failing_implement  # type: ignore[method-assign]
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        # Should complete quickly (not wait 5 hours) because stop() interrupts
        await asyncio.wait_for(
            asyncio.gather(
                orch.run(),
                _poll_then_stop(lambda: orch._credits_paused_until is not None, orch),
            ),
            timeout=20.0,
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

    def test_credit_pause_buffer_default_is_one_minute(self) -> None:
        config = ConfigFactory.create()
        assert config.credit_pause_buffer_minutes == 1

    def test_credit_pause_buffer_accepts_custom_minutes(self) -> None:
        config = ConfigFactory.create(credit_pause_buffer_minutes=5)
        assert config.credit_pause_buffer_minutes == 5


# ===========================================================================
# orchestrator — try_clear_credit_pause
# ===========================================================================


class TestTryClearCreditPause:
    """Tests for the try_clear_credit_pause method."""

    def test_returns_false_when_not_paused(self, config: HydraFlowConfig) -> None:
        """try_clear_credit_pause returns False when no pause is active."""
        orch = HydraFlowOrchestrator(config)
        assert orch.try_clear_credit_pause() is False

    def test_returns_true_and_sets_event_when_paused(
        self, config: HydraFlowConfig
    ) -> None:
        """try_clear_credit_pause returns True and sets the resume event."""
        orch = HydraFlowOrchestrator(config)
        orch._credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
        assert orch.try_clear_credit_pause() is True
        assert orch._credit_resume_event.is_set()

    def test_reset_clears_stale_credit_resume_event(
        self, config: HydraFlowConfig
    ) -> None:
        """Regression: reset() must create a fresh event so a previously-set
        event does not immediately wake the next pause cycle."""
        orch = HydraFlowOrchestrator(config)
        orch._credit_resume_event.set()
        orch._stop_event.set()
        orch.reset()
        # After reset, the event must NOT be set
        assert not orch._credit_resume_event.is_set()

    @pytest.mark.asyncio
    async def test_sleep_until_resume_wakes_on_credit_resume_event(
        self, config: HydraFlowConfig
    ) -> None:
        """_sleep_until_resume should return early when _credit_resume_event is set."""
        orch = HydraFlowOrchestrator(config)
        resume_at = datetime.now(UTC) + timedelta(hours=5)

        async def set_event_soon() -> None:
            await asyncio.sleep(0.05)
            orch._credit_resume_event.set()

        asyncio.create_task(set_event_soon())
        # Should complete quickly (not wait 5 hours)
        await asyncio.wait_for(orch._sleep_until_resume(resume_at), timeout=5.0)

    @pytest.mark.asyncio
    async def test_credit_refresh_triggers_loop_resume(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """try_clear_credit_pause during a credit pause should resume loops."""
        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch._svc.prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        mock_fetcher_noop(orch)

        call_count = 0

        async def credit_failing_then_ok() -> list[PlanResult]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CreditExhaustedError(
                    "credits out",
                    resume_at=datetime.now(UTC) + timedelta(hours=5),
                )
            return []

        orch._svc.triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._svc.planner_phase.plan_issues = credit_failing_then_ok  # type: ignore[method-assign]
        orch._svc.implementer.run_batch = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        async def instant_sleep(seconds: int | float) -> None:
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        async def trigger_refresh_after_pause() -> None:
            """Wait for pause, then trigger refresh."""
            deadline = asyncio.get_running_loop().time() + 5.0
            while asyncio.get_running_loop().time() < deadline:
                if orch._credits_paused_until is not None:
                    break
                await asyncio.sleep(0)
            # Trigger refresh
            assert orch.try_clear_credit_pause() is True
            # Wait for loops to resume and call the plan function again
            while asyncio.get_running_loop().time() < deadline:
                if call_count >= 2:
                    break
                await asyncio.sleep(0)
            await orch.stop()

        await asyncio.wait_for(
            asyncio.gather(orch.run(), trigger_refresh_after_pause()),
            timeout=10.0,
        )
        # Plan function was called at least twice (once failing, once after resume)
        assert call_count >= 2


# ===========================================================================
# dashboard route — POST /api/control/credit-refresh
# ===========================================================================


class TestCreditRefreshEndpoint:
    """Tests for the credit-refresh API endpoint."""

    @pytest.mark.asyncio
    async def test_returns_not_paused_when_no_pause(
        self, config: HydraFlowConfig, event_bus, state, tmp_path
    ) -> None:
        """POST /api/control/credit-refresh returns not_paused when idle."""
        from tests.helpers import find_endpoint, make_dashboard_router

        orch = HydraFlowOrchestrator(config, event_bus=event_bus, state=state)
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: orch
        )
        endpoint = find_endpoint(router, "/api/control/credit-refresh", "POST")
        assert endpoint is not None
        response = await endpoint()
        data = __import__("json").loads(response.body)
        assert data["status"] == "not_paused"

    @pytest.mark.asyncio
    async def test_returns_resuming_when_paused_and_credits_available(
        self, config: HydraFlowConfig, event_bus, state, tmp_path
    ) -> None:
        """POST /api/control/credit-refresh returns resuming when probe succeeds."""
        from tests.helpers import find_endpoint, make_dashboard_router

        orch = HydraFlowOrchestrator(config, event_bus=event_bus, state=state)
        orch._credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: orch
        )
        endpoint = find_endpoint(router, "/api/control/credit-refresh", "POST")
        assert endpoint is not None
        with patch(
            "subprocess_util.probe_credit_availability",
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await endpoint()
        data = __import__("json").loads(response.body)
        assert data["status"] == "resuming"
        assert orch._credit_resume_event.is_set()

    @pytest.mark.asyncio
    async def test_returns_still_exhausted_when_probe_fails(
        self, config: HydraFlowConfig, event_bus, state, tmp_path
    ) -> None:
        """POST /api/control/credit-refresh returns still_exhausted when
        the probe confirms credits are still unavailable."""
        from tests.helpers import find_endpoint, make_dashboard_router

        orch = HydraFlowOrchestrator(config, event_bus=event_bus, state=state)
        orch._credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: orch
        )
        endpoint = find_endpoint(router, "/api/control/credit-refresh", "POST")
        assert endpoint is not None
        with patch(
            "subprocess_util.probe_credit_availability",
            new_callable=AsyncMock,
            return_value=False,
        ):
            response = await endpoint()
        data = __import__("json").loads(response.body)
        assert data["status"] == "still_exhausted"
        # Pause must NOT have been cleared
        assert not orch._credit_resume_event.is_set()
        assert orch._credits_paused_until is not None

    @pytest.mark.asyncio
    async def test_returns_error_when_no_orchestrator(
        self, config: HydraFlowConfig, event_bus, state, tmp_path
    ) -> None:
        """POST /api/control/credit-refresh returns 400 when no orchestrator."""
        from tests.helpers import find_endpoint, make_dashboard_router

        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: None
        )
        endpoint = find_endpoint(router, "/api/control/credit-refresh", "POST")
        assert endpoint is not None
        response = await endpoint()
        assert response.status_code == 400


# ===========================================================================
# probe_credit_availability
# ===========================================================================


class TestProbeCreditAvailability:
    """Tests for the lightweight Anthropic API credit probe."""

    @pytest.mark.asyncio
    async def test_returns_true_when_no_api_key(self) -> None:
        """Without ANTHROPIC_API_KEY, probe assumes credits are available."""
        from subprocess_util import probe_credit_availability

        with patch.dict("os.environ", {}, clear=True):
            result = await probe_credit_availability()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_on_200_response(self) -> None:
        """A 200 response means credits are available."""
        from unittest.mock import MagicMock

        from subprocess_util import probe_credit_availability

        mock_response = MagicMock(status_code=200, text="ok")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            result = await probe_credit_availability()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_credit_exhaustion_response(self) -> None:
        """A 429 with credit exhaustion body returns False."""
        from unittest.mock import MagicMock

        from subprocess_util import probe_credit_availability

        mock_response = MagicMock(
            status_code=429,
            text="Your credit balance is too low to access the API.",
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            result = await probe_credit_availability()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_non_credit_error(self) -> None:
        """A non-credit error (e.g. 401 auth) should not block resume."""
        from unittest.mock import MagicMock

        from subprocess_util import probe_credit_availability

        mock_response = MagicMock(status_code=401, text="Invalid API key")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            result = await probe_credit_availability()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_network_error(self) -> None:
        """Network failures should be treated as credits unavailable (fail-safe)."""
        from subprocess_util import probe_credit_availability

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=ConnectionError("timeout"))

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            result = await probe_credit_availability()
        assert result is False


# ===========================================================================
# structural guard — asyncio.Event fields must be cleared in reset()
# ===========================================================================


class TestAsyncioEventResetGuard:
    """AST-based guard: every asyncio.Event field in __init__ must be cleared in reset()."""

    def test_all_asyncio_events_are_cleared_in_reset(self) -> None:
        import ast
        from pathlib import Path

        src = (Path(__file__).parent.parent / "src" / "orchestrator.py").read_text()
        tree = ast.parse(src)

        orchestrator_cls = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "HydraFlowOrchestrator"
        )

        # Collect asyncio.Event() assignments in __init__: self._X = asyncio.Event()
        init_events: set[str] = set()
        for method in orchestrator_cls.body:
            if isinstance(method, ast.FunctionDef) and method.name == "__init__":
                for stmt in ast.walk(method):
                    if (
                        isinstance(stmt, ast.Assign)
                        and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Attribute)
                        and isinstance(stmt.targets[0].value, ast.Name)
                        and stmt.targets[0].value.id == "self"
                        and isinstance(stmt.value, ast.Call)
                        and isinstance(stmt.value.func, ast.Attribute)
                        and stmt.value.func.attr == "Event"
                        and isinstance(stmt.value.func.value, ast.Name)
                        and stmt.value.func.value.id == "asyncio"
                    ):
                        init_events.add(stmt.targets[0].attr)

        # Collect self._X.clear() calls in reset()
        reset_cleared: set[str] = set()
        for method in orchestrator_cls.body:
            if isinstance(method, ast.FunctionDef) and method.name == "reset":
                for stmt in ast.walk(method):
                    if (
                        isinstance(stmt, ast.Expr)
                        and isinstance(stmt.value, ast.Call)
                        and isinstance(stmt.value.func, ast.Attribute)
                        and stmt.value.func.attr == "clear"
                        and isinstance(stmt.value.func.value, ast.Attribute)
                        and isinstance(stmt.value.func.value.value, ast.Name)
                        and stmt.value.func.value.value.id == "self"
                    ):
                        reset_cleared.add(stmt.value.func.value.attr)

        missing = init_events - reset_cleared
        assert not missing, (
            f"asyncio.Event field(s) in __init__ not cleared in reset(): {missing}. "
            "Add self.<field>.clear() to HydraFlowOrchestrator.reset()."
        )
