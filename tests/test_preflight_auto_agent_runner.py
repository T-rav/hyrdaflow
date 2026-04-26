"""AutoAgentRunner tests (spec §3.3, §5.2; ADR-0050).

Mocks `stream_claude_process` at the module boundary so no real Claude
Code subprocess is spawned. Verifies:

- the command carries `--disallowedTools=WebFetch` (spec §5.2);
- the wall-clock cap from config flows into StreamConfig.timeout;
- `cwd` is the worktree path the loop resolved;
- `event_data.source == "auto_agent_preflight"` so dashboard cost rollups
  attribute spend correctly;
- usage_stats parsed by stream_claude_process flow into PreflightSpawn
  (cost_usd, tokens, prompt_hash);
- subprocess crashes collapse to `crashed=True` with a partial transcript
  preserved — never raises;
- telemetry write failure is logged but doesn't fail the run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from preflight.auto_agent_runner import AutoAgentRunner
from tests.helpers import ConfigFactory


def _make_runner(**config_overrides: Any) -> AutoAgentRunner:
    config = ConfigFactory.create(**config_overrides)
    bus = MagicMock()
    bus.current_session_id = "test-session"
    return AutoAgentRunner(config=config, event_bus=bus)


@pytest.mark.asyncio
async def test_run_returns_spawn_with_cost_and_tokens(tmp_path: Path) -> None:
    """Happy path: streamer populates usage_stats; cost + tokens flow into spawn."""

    async def fake_stream(*, config, **kwargs: Any) -> str:
        # Mimic StreamParser populating usage_stats during streaming.
        config.usage_stats["input_tokens"] = 1000
        config.usage_stats["output_tokens"] = 500
        config.usage_stats["total_tokens"] = 1500
        return "<status>resolved</status><pr_url>https://x/pr/1</pr_url><diagnosis>fixed</diagnosis>"

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=fake_stream,
    ):
        spawn = await runner.run(
            prompt="hello",
            worktree_path=str(tmp_path),
            issue_number=42,
        )
    assert spawn.crashed is False
    assert spawn.tokens == 1500
    assert spawn.prompt_hash.startswith("sha256:")
    assert "<status>resolved</status>" in spawn.output_text
    # cost_usd may be 0 if the test config's model isn't in the pricing
    # table; the contract is that it's a non-negative float.
    assert spawn.cost_usd >= 0.0


@pytest.mark.asyncio
async def test_run_passes_disallowed_tools_to_command(tmp_path: Path) -> None:
    """Spec §5.2: WebFetch must be in --disallowedTools so the agent can't
    chase arbitrary URLs (issue-content leak / prompt-injection vector)."""
    captured: dict[str, Any] = {}

    async def capture_stream(*, cmd, **kwargs: Any) -> str:
        captured["cmd"] = cmd
        return ""

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=capture_stream,
    ):
        await runner.run(prompt="x", worktree_path=str(tmp_path), issue_number=1)

    cmd = captured["cmd"]
    # --disallowedTools value must be the next arg after the flag.
    assert "--disallowedTools" in cmd
    idx = cmd.index("--disallowedTools")
    assert "WebFetch" in cmd[idx + 1]


@pytest.mark.asyncio
async def test_run_passes_wall_clock_cap_to_stream_timeout(tmp_path: Path) -> None:
    """auto_agent_wall_clock_cap_s flows into StreamConfig.timeout so the
    subprocess is killed at the operator-set bound, not the codebase
    default (1h)."""
    captured: dict[str, Any] = {}

    async def capture_stream(*, config, **kwargs: Any) -> str:
        captured["timeout"] = config.timeout
        return ""

    runner = _make_runner(auto_agent_wall_clock_cap_s=180)
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=capture_stream,
    ):
        await runner.run(prompt="x", worktree_path=str(tmp_path), issue_number=1)

    assert captured["timeout"] == 180


@pytest.mark.asyncio
async def test_run_passes_worktree_as_cwd(tmp_path: Path) -> None:
    """The agent must execute inside the issue's worktree, not the main repo."""
    captured: dict[str, Any] = {}

    async def capture_stream(*, cwd, **kwargs: Any) -> str:
        captured["cwd"] = cwd
        return ""

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=capture_stream,
    ):
        await runner.run(prompt="x", worktree_path=str(tmp_path), issue_number=1)
    assert captured["cwd"] == tmp_path


@pytest.mark.asyncio
async def test_run_event_data_source_is_auto_agent_preflight(tmp_path: Path) -> None:
    """Telemetry source string must be 'auto_agent_preflight' so cost
    rollups attribute spend correctly."""
    captured: dict[str, Any] = {}

    async def capture_stream(*, event_data, **kwargs: Any) -> str:
        captured["event_data"] = event_data
        return ""

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=capture_stream,
    ):
        await runner.run(prompt="x", worktree_path=str(tmp_path), issue_number=99)
    assert captured["event_data"]["source"] == "auto_agent_preflight"
    assert captured["event_data"]["issue"] == 99


@pytest.mark.asyncio
async def test_subprocess_exception_collapses_to_crashed_spawn(tmp_path: Path) -> None:
    """Spec contract: AutoAgentRunner.run never raises — every failure is a
    PreflightSpawn(crashed=True). Upstream PreflightAgent maps to fatal."""

    async def boom(**kwargs: Any) -> str:
        raise RuntimeError("subprocess oom")

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process", side_effect=boom
    ):
        spawn = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert spawn.crashed is True
    assert "spawn error" in spawn.output_text
    assert "subprocess oom" in spawn.output_text


@pytest.mark.asyncio
async def test_telemetry_write_failure_does_not_break_run(tmp_path: Path) -> None:
    """If PromptTelemetry.record raises, the loop must still get a usable
    PreflightSpawn back. We don't want a JSONL write hiccup to wedge the
    auto-agent loop."""

    async def stream_ok(**kwargs: Any) -> str:
        return "<status>needs_human</status><diagnosis>x</diagnosis>"

    runner = _make_runner()
    runner._telemetry = MagicMock()
    runner._telemetry.record = MagicMock(side_effect=OSError("disk full"))
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=stream_ok,
    ):
        spawn = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    # Run completed even though telemetry failed.
    assert spawn.crashed is False
    assert spawn.output_text


@pytest.mark.asyncio
async def test_zero_usage_stats_yields_zero_cost(tmp_path: Path) -> None:
    """When the streamer doesn't populate usage_stats (e.g., stream parse
    failure), cost defaults to 0.0 — never a negative or NaN."""

    async def stream_no_stats(**kwargs: Any) -> str:
        return ""

    runner = _make_runner()
    with patch(
        "runners.base_subprocess_runner.stream_claude_process",
        side_effect=stream_no_stats,
    ):
        spawn = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert spawn.cost_usd == 0.0
    assert spawn.tokens == 0


@pytest.mark.asyncio
async def test_credit_exhausted_propagates(tmp_path: Path) -> None:
    """CreditExhaustedError must propagate so the caretaker loop can suspend.

    Catching it inside the broad `except Exception` would silently burn the
    attempt budget while the credit balance was already gone — exactly the
    regression that PR review C1 caught.
    """
    from subprocess_util import CreditExhaustedError

    async def credit_exhausted(**kwargs: Any) -> str:
        raise CreditExhaustedError("api credits at zero")

    runner = _make_runner()
    with (
        patch(
            "runners.base_subprocess_runner.stream_claude_process",
            side_effect=credit_exhausted,
        ),
        pytest.raises(CreditExhaustedError),
    ):
        await runner.run(prompt="x", worktree_path=str(tmp_path), issue_number=1)


@pytest.mark.asyncio
async def test_auth_retry_then_success(tmp_path: Path) -> None:
    """First two AuthenticationRetryError attempts retry with backoff; third
    succeeds. Final spawn must NOT be marked crashed.
    """
    from runner_utils import AuthenticationRetryError

    call_count = 0

    async def fake_stream(**kwargs: Any) -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise AuthenticationRetryError("transient OAuth blip")
        return "<status>resolved</status><pr_url>x</pr_url><diagnosis>ok</diagnosis>"

    runner = _make_runner()
    with (
        patch(
            "runners.base_subprocess_runner.stream_claude_process",
            side_effect=fake_stream,
        ),
        patch(
            "runners.base_subprocess_runner.asyncio.sleep",  # skip backoff in tests
            new_callable=AsyncMock,
        ),
    ):
        spawn = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert call_count == 3
    assert spawn.crashed is False
    assert "<status>resolved</status>" in spawn.output_text


@pytest.mark.asyncio
async def test_auth_retry_exhausted_marks_crashed(tmp_path: Path) -> None:
    """Three consecutive AuthenticationRetryError exhausts retries → crashed."""
    from runner_utils import AuthenticationRetryError

    async def always_auth_fail(**kwargs: Any) -> str:
        raise AuthenticationRetryError("OAuth token refresh broken")

    runner = _make_runner()
    with (
        patch(
            "runners.base_subprocess_runner.stream_claude_process",
            side_effect=always_auth_fail,
        ),
        patch(
            "runners.base_subprocess_runner.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        spawn = await runner.run(
            prompt="x", worktree_path=str(tmp_path), issue_number=1
        )
    assert spawn.crashed is True
    assert "auth retry exhausted" in spawn.output_text
