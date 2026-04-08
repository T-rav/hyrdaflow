"""Agent CLI command builders for Claude, Codex, and Pi backends."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

AgentTool = Literal["claude", "codex", "pi"]

# Pre-cloned plugin directories baked into the Docker image.
# Each entry becomes a ``--plugin-dir <path>`` flag on Claude CLI invocations.
_DOCKER_PLUGIN_DIRS: tuple[str, ...] = (
    "/opt/plugins/claude-plugins-official",
    "/opt/plugins/superpowers",
    "/opt/plugins/lightfactory",
)


def _plugin_dir_flags() -> list[str]:
    """Return ``--plugin-dir`` flags for plugin dirs that exist on disk."""
    flags: list[str] = []
    for d in _DOCKER_PLUGIN_DIRS:
        if Path(d).is_dir():
            flags.extend(["--plugin-dir", d])
    return flags


def build_agent_command(
    *,
    tool: AgentTool,
    model: str,
    disallowed_tools: str | None = None,
    max_turns: int | None = None,
    effort: str | None = None,
) -> list[str]:
    """Build a non-interactive command for an agent stage.

    *effort* sets the reasoning effort level (``"low"``, ``"medium"``,
    ``"high"``, ``"max"``).  When ``None``, the CLI default is used.
    """
    if tool == "codex":
        return _build_codex_command(model=model)
    if tool == "pi":
        return _build_pi_command(
            model=model,
            max_turns=max_turns,
            disallowed_tools=disallowed_tools,
        )

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
    cmd.extend(_plugin_dir_flags())
    if disallowed_tools:
        cmd.extend(["--disallowedTools", disallowed_tools])
    if max_turns is not None:
        cmd.extend(["--max-turns", str(max_turns)])
    if effort is not None:
        cmd.extend(["--effort", effort])
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
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
    ]


def build_lightweight_command(
    *,
    tool: AgentTool,
    model: str,
    prompt: str,
) -> tuple[list[str], bytes | None]:
    """Build a simple CLI command for lightweight (non-streaming) callers.

    Unlike :func:`build_agent_command` which builds streaming commands for
    the full agent runners, this builds simple one-shot commands used by
    background workers (ADR reviewer, memory compaction, PR unsticker,
    transcript summarizer).

    Returns ``(cmd, input_bytes)`` where *input_bytes* is the prompt
    encoded as UTF-8 bytes when passed via stdin, or ``None`` when the
    prompt is short enough to pass as a CLI argument.

    Large prompts are passed via stdin to avoid hitting the OS
    ``ARG_MAX`` limit (typically ~130 KB on macOS/Linux).
    """
    if tool == "codex":
        cmd = _build_codex_command(model=model)
        cmd.append(prompt)
        return cmd, None

    # For large prompts, pass via stdin to avoid OS ARG_MAX limit.
    prompt_bytes = prompt.encode()
    use_stdin = len(prompt_bytes) > 100_000  # ~100 KB threshold

    if use_stdin:
        cmd = [tool, "-p", "-", "--model", model]
        input_bytes: bytes | None = prompt_bytes
    else:
        cmd = [tool, "-p", prompt, "--model", model]
        input_bytes = None

    if tool == "claude":
        cmd.extend(_plugin_dir_flags())
    return cmd, input_bytes


def _build_pi_command(
    *,
    model: str,
    max_turns: int | None = None,
    disallowed_tools: str | None = None,
) -> list[str]:
    """Build a Pi headless command that emits machine-readable output."""
    cmd = [
        "pi",
        "-p",
        "--mode",
        "json",
        "--model",
        model,
    ]

    guidance: list[str] = []
    # Pi has no native max-turns flag; add explicit stop guidance instead.
    if max_turns is not None:
        guidance.append(
            f"Limit yourself to at most {max_turns} assistant turn(s) and then stop."
        )
    if disallowed_tools:
        blocked = ",".join(t.strip() for t in disallowed_tools.split(",") if t.strip())
        if blocked:
            guidance.append(
                "Do not invoke these tools under any circumstances: "
                f"{blocked}. If needed, explain the limitation and continue."
            )
    for line in guidance:
        cmd.extend(["--append-system-prompt", line])
    return cmd
