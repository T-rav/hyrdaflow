"""Tests for the Gemini CLI command builder."""

from __future__ import annotations

from agent_cli import build_agent_command, build_lightweight_command


def test_build_agent_command_gemini_base_flags() -> None:
    cmd = build_agent_command(tool="gemini", model="gemini-3-pro")
    assert cmd[0] == "gemini"
    assert "-p" in cmd
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gemini-3-pro"
    assert "--approval-mode" in cmd
    assert cmd[cmd.index("--approval-mode") + 1] == "yolo"


def test_build_agent_command_gemini_has_no_prompt_value() -> None:
    """`-p` must be present without an inline value; runner splices the prompt."""
    cmd = build_agent_command(tool="gemini", model="gemini-3-pro")
    p_idx = cmd.index("-p")
    assert cmd[p_idx + 1].startswith("--"), (
        "prompt must not be baked in; runner splices it after -p"
    )


def test_build_lightweight_command_gemini_passes_prompt_after_p() -> None:
    cmd, stdin_bytes = build_lightweight_command(
        tool="gemini",
        model="gemini-3-pro",
        prompt="hello world",
    )
    assert cmd[0] == "gemini"
    p_idx = cmd.index("-p")
    assert cmd[p_idx + 1] == "hello world"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gemini-3-pro"
    assert stdin_bytes is None


def test_build_lightweight_command_gemini_uses_stdin_for_large_prompt() -> None:
    huge = "x" * 150_000  # > 100 KB threshold
    cmd, stdin_bytes = build_lightweight_command(
        tool="gemini",
        model="gemini-3-pro",
        prompt=huge,
    )
    assert stdin_bytes == huge.encode()
    assert "-p" in cmd
    p_idx = cmd.index("-p")
    assert cmd[p_idx + 1] == "-"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gemini-3-pro"
