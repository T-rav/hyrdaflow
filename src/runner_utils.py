"""Shared subprocess streaming utilities for agent runners."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from activity_parser import ActivityParser, get_activity_parser
from events import EventBus, EventType, HydraFlowEvent
from execution import SubprocessRunner, get_default_runner
from models import TranscriptEventData, TranscriptLinePayload
from stream_parser import StreamParser
from subprocess_util import (
    CreditExhaustedError,
    is_credit_exhaustion,
    make_clean_env,
    parse_credit_resume_time,
)

if TYPE_CHECKING:
    from trace_collector import TraceCollector

logger = logging.getLogger("hydraflow.runner_utils")


class AuthenticationRetryError(RuntimeError):
    """Raised when the agent CLI reports authentication_failed.

    Treated as retryable — OAuth token refresh can fail transiently.
    """


# Backend-specific auth-failure signatures. Keep these conservative —
# false positives turn real agent output into spurious retries.
_AUTH_FAILURE_PATTERNS = (
    "authentication_failed",  # claude-code stream-json
    "Please set an Auth method",  # gemini-cli startup
    "AuthenticationError",  # generic SDK exceptions
)


def _is_auth_failure(text: str) -> bool:
    """Check if *text* indicates a retryable authentication failure."""
    return any(pattern in text for pattern in _AUTH_FAILURE_PATTERNS)


@dataclass(frozen=True, slots=True)
class StreamConfig:
    """Rarely-varying options for :func:`stream_claude_process`."""

    on_output: Callable[[str], bool] | None = None
    timeout: float = 3600.0
    runner: SubprocessRunner | None = None
    usage_stats: dict[str, object] | None = field(default=None)
    gh_token: str = ""
    trace_collector: TraceCollector | None = None


def _route_prompt_to_cmd(cmd: list[str], prompt: str) -> tuple[list[str], int]:
    """Decide how to deliver *prompt* to the CLI subprocess.

    Returns ``(cmd_to_run, stdin_mode)`` where *stdin_mode* is either
    ``asyncio.subprocess.DEVNULL`` (prompt embedded in *cmd_to_run*) or
    ``asyncio.subprocess.PIPE`` (caller must write *prompt* to stdin).
    """
    use_codex_exec = len(cmd) >= 2 and cmd[0] == "codex" and cmd[1] == "exec"
    use_pi_print = cmd and cmd[0] == "pi" and ("-p" in cmd or "--print" in cmd)
    use_claude_print = cmd and cmd[0] == "claude" and "-p" in cmd
    # Gemini CLI only supports -p (no --print alias).
    use_gemini_print = cmd and cmd[0] == "gemini" and "-p" in cmd
    use_prompt_arg = (
        use_codex_exec or use_pi_print or use_claude_print or use_gemini_print
    )
    if use_prompt_arg:
        if use_claude_print or use_pi_print or use_gemini_print:
            # Claude / Pi / Gemini all require the prompt immediately after
            # -p/--print; placing it at the end causes CLI errors.
            flag = "-p" if "-p" in cmd else "--print"
            idx = cmd.index(flag)
            cmd_to_run = [*cmd[: idx + 1], prompt, *cmd[idx + 1 :]]
        else:
            # Codex exec: prompt is a trailing positional argument.
            cmd_to_run = [*cmd, prompt]
        return cmd_to_run, asyncio.subprocess.DEVNULL
    return cmd, asyncio.subprocess.PIPE


def _post_stream_result(
    *,
    raw_lines: list[str],
    accumulated_text: str,
    result_text: str,
    early_killed: bool,
    returncode: int | None,
    stderr_text: str,
    parser: StreamParser,
    config: StreamConfig,
    logger: logging.Logger,
) -> str:
    """Validate post-stream state, check for errors, and assemble the transcript.

    Raises :class:`AuthenticationRetryError` or :class:`CreditExhaustedError`
    when the raw output indicates a retryable auth or billing failure
    (skipped when *early_killed* is ``True``).
    """
    if not early_killed and returncode != 0:
        logger.warning(
            "Process exited with code %d: %s",
            returncode,
            stderr_text[:500],
        )

    # Skip auth/credit checks when early_killed — killing the process can cause
    # in-flight API requests to fail with spurious errors.
    raw_output = "\n".join(raw_lines)
    combined_for_auth = f"{stderr_text}\n{raw_output}"
    if not early_killed and _is_auth_failure(combined_for_auth):
        raise AuthenticationRetryError(
            "Agent CLI authentication failed — check the provider's auth "
            "(ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN / GEMINI_API_KEY / "
            "~/.gemini/settings.json / CODEX_HOME)"
        )

    combined = f"{stderr_text}\n{accumulated_text}"
    if not early_killed and is_credit_exhaustion(combined):
        resume_at = parse_credit_resume_time(combined)
        raise CreditExhaustedError("API credit limit reached", resume_at=resume_at)

    if config.usage_stats is not None:
        config.usage_stats.update(parser.usage_snapshot)

    transcript = result_text or accumulated_text.rstrip("\n") or "\n".join(raw_lines)

    if not transcript.strip() and stderr_text:
        logger.warning(
            "Process produced empty stdout (rc=%d), stderr: %s",
            returncode or 0,
            stderr_text[:500],
        )

    return transcript


async def _stream_and_collect(
    proc: asyncio.subprocess.Process,
    stderr_task: asyncio.Task[bytes],
    event_bus: EventBus,
    event_data: TranscriptEventData,
    parser: StreamParser,
    activity_parser: ActivityParser,
    logger: logging.Logger,
    config: StreamConfig,
) -> str:
    """Read *proc* stdout, publish events, and assemble the transcript."""
    raw_lines: list[str] = []
    result_text = ""
    accumulated_text = ""
    early_killed = False

    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip("\n")
        raw_lines.append(line)
        if not line.strip():
            continue

        display, result = parser.parse(line)
        if result is not None:
            result_text = result

        if display.strip():
            accumulated_text += display + "\n"
            line_data: TranscriptLinePayload = {**event_data, "line": display}
            await event_bus.publish(
                HydraFlowEvent(type=EventType.TRANSCRIPT_LINE, data=line_data)
            )

        if (
            config.on_output is not None
            and not early_killed
            and config.on_output(accumulated_text)
        ):
            early_killed = True
            proc.kill()
            break

        # Emit structured activity event (additive — does not replace TRANSCRIPT_LINE)
        try:
            activity = activity_parser.parse(line)
            if activity is not None:
                activity["issue"] = event_data.get("issue", 0)
                activity["source"] = event_data.get("source", "unknown")
                await event_bus.publish(
                    HydraFlowEvent(type=EventType.AGENT_ACTIVITY, data=activity)
                )
        except Exception:
            logger.warning("Activity parsing failed", exc_info=True)

        if config.trace_collector is not None:
            config.trace_collector.record(line)

    # --- Post-stream validation and result assembly ---
    stderr_bytes = await stderr_task
    await proc.wait()
    stderr_text = stderr_bytes.decode(errors="replace").strip()

    return _post_stream_result(
        raw_lines=raw_lines,
        accumulated_text=accumulated_text,
        result_text=result_text,
        early_killed=early_killed,
        returncode=proc.returncode,
        stderr_text=stderr_text,
        parser=parser,
        config=config,
        logger=logger,
    )


async def stream_claude_process(
    *,
    cmd: list[str],
    prompt: str,
    cwd: Path,
    active_procs: set[asyncio.subprocess.Process],
    event_bus: EventBus,
    event_data: TranscriptEventData,
    logger: logging.Logger,
    config: StreamConfig = StreamConfig(),
) -> str:
    """Run an agent subprocess and stream its output.

    Parameters
    ----------
    cmd:
        Command to execute (e.g. ``["claude", "-p", ...]`` or ``["codex", "exec", ...]``).
    prompt:
        Prompt text for the agent. Passed via stdin for Claude-style commands;
        passed as a positional argument for Codex `exec`.
    cwd:
        Working directory for the subprocess.
    active_procs:
        Shared set for tracking active processes (for terminate).
    event_bus:
        For publishing ``TRANSCRIPT_LINE`` events.
    event_data:
        Base dict for event data (runner-specific keys like ``issue``/``pr``/``source``).
        ``"line"`` is added automatically per output line.
    logger:
        Caller's logger for warnings (preserves per-runner log context).
    config:
        Optional streaming configuration (callbacks, timeout, runner, etc.).

    Returns
    -------
    str
        The transcript string, using the fallback chain:
        result_text → accumulated_text → raw_lines.
    """
    env = make_clean_env(config.gh_token)
    runner = config.runner or get_default_runner()
    cmd_to_run, stdin_mode = _route_prompt_to_cmd(cmd, prompt)

    proc = await runner.create_streaming_process(
        cmd_to_run,
        cwd=str(cwd),
        env=env,
        stdin=stdin_mode,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,  # 1 MB — stream-json lines can exceed 64 KB default
        start_new_session=True,  # Own process group for reliable cleanup
    )
    active_procs.add(proc)

    stderr_task: asyncio.Task[bytes] | None = None
    try:
        assert proc.stdout is not None
        assert proc.stderr is not None

        if stdin_mode == asyncio.subprocess.PIPE:
            assert proc.stdin is not None
            proc.stdin.write(prompt.encode())
            await proc.stdin.drain()
            proc.stdin.close()

        stderr_task = asyncio.create_task(proc.stderr.read())

        parser = StreamParser()
        _backend = "claude"
        if cmd and cmd[0] == "codex":
            _backend = "codex"
        elif cmd and cmd[0] == "gemini":
            _backend = "gemini"
        elif cmd and cmd[0] == "pi":
            _backend = "pi"
        activity_parser = get_activity_parser(_backend)

        return await asyncio.wait_for(
            _stream_and_collect(
                proc,
                stderr_task,
                event_bus,
                event_data,
                parser,
                activity_parser,
                logger,
                config,
            ),
            timeout=config.timeout,
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Agent process timed out after {config.timeout}s") from exc
    except asyncio.CancelledError:
        proc.kill()
        raise
    finally:
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
        active_procs.discard(proc)


def terminate_processes(active_procs: set[asyncio.subprocess.Process]) -> None:
    """Kill all processes in *active_procs* and their process groups."""
    for proc in list(active_procs):
        with contextlib.suppress(ProcessLookupError, OSError):
            if proc.pid is not None:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
