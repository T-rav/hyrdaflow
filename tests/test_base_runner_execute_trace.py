"""Test that BaseRunner._execute creates and finalizes a TraceCollector
when a tracing context is set."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402

from base_runner import BaseRunner  # noqa: E402
from tracing_context import TracingContext  # noqa: E402


def _make_runner(tmp_path: Path) -> BaseRunner:
    config = MagicMock()
    config.data_root = tmp_path
    config.agent_timeout = 60
    event_bus = MagicMock()
    event_bus.current_session_id = None
    runner = MagicMock()
    br = BaseRunner.__new__(BaseRunner)
    br._config = config
    br._bus = event_bus
    br._active_procs = set()
    br._runner = runner
    br._prompt_telemetry = MagicMock()
    br._last_context_stats = {"cache_hits": 0, "cache_misses": 0}
    br._hindsight = None
    br._tracing_ctx = None
    br._credentials = MagicMock()
    br._credentials.gh_token = ""
    br._wiki_store = None
    br._log = MagicMock()
    return br


@pytest.mark.asyncio
async def test_execute_passes_collector_when_ctx_set(tmp_path: Path):
    runner = _make_runner(tmp_path)
    runner.set_tracing_context(
        TracingContext(
            issue_number=42, phase="implement", source="implementer", run_id=1
        )
    )

    captured_kwargs = {}

    async def fake_stream(**kwargs):
        captured_kwargs.update(kwargs)
        return "transcript"

    with patch("base_runner.stream_claude_process", side_effect=fake_stream):
        await runner._execute(
            cmd=["claude", "-p"],
            prompt="test",
            cwd=tmp_path,
            event_data={"issue": 42, "source": "implementer"},
        )

    assert captured_kwargs.get("trace_collector") is not None
    # The collector instance should be built from the context values
    collector = captured_kwargs["trace_collector"]
    assert collector._issue_number == 42
    assert collector._phase == "implement"
    assert collector._run_id == 1


@pytest.mark.asyncio
async def test_execute_passes_no_collector_when_ctx_unset(tmp_path: Path):
    runner = _make_runner(tmp_path)
    # No tracing context set

    captured_kwargs = {}

    async def fake_stream(**kwargs):
        captured_kwargs.update(kwargs)
        return "transcript"

    with patch("base_runner.stream_claude_process", side_effect=fake_stream):
        await runner._execute(
            cmd=["claude", "-p"],
            prompt="test",
            cwd=tmp_path,
            event_data={"issue": 42, "source": "implementer"},
        )

    assert captured_kwargs.get("trace_collector") is None


@pytest.mark.asyncio
async def test_execute_finalizes_collector_on_success(tmp_path: Path):
    runner = _make_runner(tmp_path)
    runner.set_tracing_context(
        TracingContext(
            issue_number=42, phase="implement", source="implementer", run_id=1
        )
    )

    finalize_calls: list[bool] = []

    def fake_finalize(self, *, success):
        finalize_calls.append(success)

    async def fake_stream(**kwargs):
        return "transcript"

    with (
        patch("base_runner.stream_claude_process", side_effect=fake_stream),
        patch(
            "trace_collector.TraceCollector.finalize",
            new=fake_finalize,
        ),
    ):
        await runner._execute(
            cmd=["claude", "-p"],
            prompt="test",
            cwd=tmp_path,
            event_data={"issue": 42, "source": "implementer"},
        )

    assert finalize_calls == [True]


@pytest.mark.asyncio
async def test_execute_finalizes_collector_on_failure(tmp_path: Path):
    runner = _make_runner(tmp_path)
    runner.set_tracing_context(
        TracingContext(
            issue_number=42, phase="implement", source="implementer", run_id=1
        )
    )

    finalize_calls: list[bool] = []

    def fake_finalize(self, *, success):
        finalize_calls.append(success)

    async def fake_stream(**kwargs):
        raise RuntimeError("boom")

    with (
        patch("base_runner.stream_claude_process", side_effect=fake_stream),
        patch(
            "trace_collector.TraceCollector.finalize",
            new=fake_finalize,
        ),
        pytest.raises(RuntimeError, match="boom"),
    ):
        await runner._execute(
            cmd=["claude", "-p"],
            prompt="test",
            cwd=tmp_path,
            event_data={"issue": 42, "source": "implementer"},
        )

    assert finalize_calls == [False]
