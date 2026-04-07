"""Test that BaseRunner allocates unique subprocess_idx for every _execute call.

Without this, skill loops, pre-quality review loops, and quality fix loops
would all create TraceCollector(subprocess_idx=0) and overwrite each other's
``subprocess-0.json`` files inside the same ``run-N/`` directory.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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
    br._trace_subprocess_counter = 0
    br._credentials = MagicMock()
    br._credentials.gh_token = ""
    br._wiki_store = None
    br._log = MagicMock()
    return br


class TestSubprocessCounter:
    def test_set_tracing_context_resets_counter_to_zero(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        runner._trace_subprocess_counter = 99
        runner.set_tracing_context(
            TracingContext(
                issue_number=1, phase="implement", source="implementer", run_id=1
            )
        )
        assert runner._trace_subprocess_counter == 0

    def test_clear_tracing_context_resets_counter_to_zero(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        runner.set_tracing_context(
            TracingContext(
                issue_number=1, phase="implement", source="implementer", run_id=1
            )
        )
        runner._trace_subprocess_counter = 5
        runner.clear_tracing_context()
        assert runner._trace_subprocess_counter == 0

    def test_allocate_returns_monotonic_indices(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        runner.set_tracing_context(
            TracingContext(
                issue_number=1, phase="implement", source="implementer", run_id=1
            )
        )
        assert runner._allocate_trace_subprocess_idx() == 0
        assert runner._allocate_trace_subprocess_idx() == 1
        assert runner._allocate_trace_subprocess_idx() == 2

    @pytest.mark.asyncio
    async def test_repeated_execute_calls_get_unique_indices(self, tmp_path: Path):
        """Each _execute call within one phase run gets a unique subprocess_idx."""
        runner = _make_runner(tmp_path)
        runner.set_tracing_context(
            TracingContext(
                issue_number=42, phase="implement", source="implementer", run_id=1
            )
        )

        captured_indices: list[int] = []

        async def fake_stream(**kwargs):
            collector = kwargs["trace_collector"]
            captured_indices.append(collector._subprocess_idx)
            return "transcript"

        with patch("base_runner.stream_claude_process", side_effect=fake_stream):
            for _ in range(5):
                await runner._execute(
                    cmd=["claude", "-p"],
                    prompt="test",
                    cwd=tmp_path,
                    event_data={"issue": 42, "source": "implementer"},
                )

        # Five calls → five unique indices 0..4
        assert captured_indices == [0, 1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_no_collector_when_ctx_unset_does_not_bump_counter(
        self, tmp_path: Path
    ):
        runner = _make_runner(tmp_path)
        # No context set

        async def fake_stream(**kwargs):
            assert kwargs["trace_collector"] is None
            return "transcript"

        with patch("base_runner.stream_claude_process", side_effect=fake_stream):
            await runner._execute(
                cmd=["claude", "-p"],
                prompt="test",
                cwd=tmp_path,
                event_data={"issue": 42, "source": "implementer"},
            )
        assert runner._trace_subprocess_counter == 0
