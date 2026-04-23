"""Tests for gemini prompt routing and backend detection in runner_utils."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from runner_utils import StreamConfig, _route_prompt_to_cmd, stream_claude_process
from tests.helpers import make_streaming_proc


def _default_kwargs(event_bus, **overrides):
    """Build default kwargs for stream_claude_process.

    Keys that belong on :class:`StreamConfig` (``on_output``, ``timeout``,
    ``runner``, ``usage_stats``, ``gh_token``, ``trace_collector``) are
    extracted and bundled into a ``config`` kwarg automatically.
    """
    _CONFIG_KEYS = {
        "on_output",
        "timeout",
        "runner",
        "usage_stats",
        "gh_token",
        "trace_collector",
    }
    config_overrides = {
        k: overrides.pop(k) for k in list(overrides) if k in _CONFIG_KEYS
    }
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
    if config_overrides:
        defaults["config"] = StreamConfig(**config_overrides)
    return defaults


def test_route_prompt_splices_after_p_for_gemini() -> None:
    cmd = [
        "gemini",
        "-p",
        "--output-format",
        "stream-json",
        "--model",
        "gemini-3.1-pro-preview",
    ]
    cmd_to_run, stdin_mode = _route_prompt_to_cmd(cmd, "do the thing")

    p_idx = cmd_to_run.index("-p")
    assert cmd_to_run[p_idx + 1] == "do the thing"
    assert cmd_to_run[p_idx + 2] == "--output-format"
    assert stdin_mode == asyncio.subprocess.DEVNULL


def test_route_prompt_leaves_non_gemini_cmds_alone() -> None:
    cmd = ["pytest", "-v"]
    cmd_to_run, stdin_mode = _route_prompt_to_cmd(cmd, "hello")
    assert cmd_to_run == cmd
    assert stdin_mode == asyncio.subprocess.PIPE


class TestGeminiIntegration:
    """Integration tests for gemini prompt passing through stream_claude_process."""

    @pytest.mark.asyncio
    async def test_gemini_passes_prompt_as_argument(self, event_bus) -> None:
        """Gemini print mode should insert prompt right after -p."""
        mock_create = make_streaming_proc(returncode=0, stdout="ok")
        cmd = [
            "gemini",
            "-p",
            "--output-format",
            "stream-json",
            "--model",
            "gemini-3.1-pro-preview",
        ]
        prompt = "do the thing"

        with patch("asyncio.create_subprocess_exec", mock_create) as mock_exec:
            await stream_claude_process(
                **_default_kwargs(event_bus, cmd=cmd, prompt=prompt)
            )

        args = list(mock_exec.call_args[0])
        kwargs = mock_exec.call_args[1]
        # Prompt must be immediately after -p for the CLI to recognise it.
        p_idx = args.index("-p")
        assert args[p_idx + 1] == prompt
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
