"""Agent CLI command builders for Claude and Codex backends."""

from __future__ import annotations

from typing import Literal

AgentTool = Literal["claude", "codex"]


def build_agent_command(
    *,
    tool: AgentTool,
    model: str,
    disallowed_tools: str | None = None,
    max_turns: int | None = None,
) -> list[str]:
    """Build a non-interactive command for an agent stage."""
    if tool == "codex":
        return _build_codex_command(model=model)

    cmd = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--model",
        model,
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
    ]
    if disallowed_tools:
        cmd.extend(["--disallowedTools", disallowed_tools])
    if max_turns is not None:
        cmd.extend(["--max-turns", str(max_turns)])
    return cmd


def _build_codex_command(*, model: str) -> list[str]:
    """Build a Codex `exec` command with non-interactive automation settings."""
    return [
        "codex",
        "exec",
        "--json",
        "--model",
        model,
        "--sandbox",
        "danger-full-access",
        "--ask-for-approval",
        "never",
        "--skip-git-repo-check",
    ]
