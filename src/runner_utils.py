"""Shared subprocess streaming utilities for agent runners."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
from collections.abc import Callable
from pathlib import Path

from events import EventBus, EventType, HydraFlowEvent
from execution import SubprocessRunner, get_default_runner
from models import TranscriptEventData
from stream_parser import StreamParser
from subprocess_util import (
    CreditExhaustedError,
    is_credit_exhaustion,
    make_clean_env,
    parse_credit_resume_time,
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
    on_output: Callable[[str], bool] | None = None,
    timeout: float = 3600.0,
    runner: SubprocessRunner | None = None,
    usage_stats: dict[str, object] | None = None,
    gh_token: str = "",
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
    on_output:
        Optional callback receiving accumulated display text.
        Return ``True`` to kill the process early.
    usage_stats:
        Optional dict populated with normalized usage totals and metadata
        (availability status, backend, and raw usage blobs when emitted).

    Returns
    -------
    str
        The transcript string, using the fallback chain:
        result_text → accumulated_text → raw_lines.
    """
    env = make_clean_env(gh_token)

    if runner is None:
        runner = get_default_runner()
    use_codex_exec = len(cmd) >= 2 and cmd[0] == "codex" and cmd[1] == "exec"
    use_pi_print = cmd and cmd[0] == "pi" and ("-p" in cmd or "--print" in cmd)
    use_claude_print = cmd and cmd[0] == "claude" and "-p" in cmd
    use_prompt_arg = use_codex_exec or use_pi_print or use_claude_print
    cmd_to_run = [*cmd, prompt] if use_prompt_arg else cmd
    stdin_mode = (
        asyncio.subprocess.DEVNULL if use_prompt_arg else asyncio.subprocess.PIPE
    )

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

        stdout_stream = proc.stdout  # capture for nested function

        if not use_prompt_arg:
            assert proc.stdin is not None
            proc.stdin.write(prompt.encode())
            await proc.stdin.drain()
            proc.stdin.close()

        # Drain stderr in background to prevent deadlock
        stderr_task = asyncio.create_task(proc.stderr.read())

        parser = StreamParser()
        raw_lines: list[str] = []
        result_text = ""
        accumulated_text = ""
        early_killed = False

        async def _stream_body() -> str:
            nonlocal result_text, accumulated_text, early_killed

            async for raw in stdout_stream:
                line = raw.decode(errors="replace").rstrip("\n")
                raw_lines.append(line)
                if not line.strip():
                    continue

                display, result = parser.parse(line)
                if result is not None:
                    result_text = result

                if display.strip():
                    accumulated_text += display + "\n"
                    await event_bus.publish(
                        HydraFlowEvent(
                            type=EventType.TRANSCRIPT_LINE,
                            data={**event_data, "line": display},
                        )
                    )

                if (
                    on_output is not None
                    and not early_killed
                    and on_output(accumulated_text)
                ):
                    early_killed = True
                    proc.kill()
                    break

            stderr_bytes = await stderr_task
            await proc.wait()

            stderr_text = stderr_bytes.decode(errors="replace").strip()

            if not early_killed and proc.returncode != 0:
                logger.warning(
                    "Process exited with code %d: %s",
                    proc.returncode,
                    stderr_text[:500],
                )

            # Detect authentication failures from stream-json output.
            # Claude CLI emits '"error":"authentication_failed"' when it
            # has no valid API key or OAuth session (common in Docker
            # containers without ANTHROPIC_API_KEY).
            raw_output = "\n".join(raw_lines)
            if "authentication_failed" in raw_output:
                raise RuntimeError(
                    "Agent CLI authentication failed — set ANTHROPIC_API_KEY "
                    "in .env for Docker execution mode"
                )

            # Check for credit exhaustion in both stderr and transcript.
            # Skip when early_killed=True — the process was intentionally killed by us
            # because it produced its expected output; credit phrases in legitimate
            # transcript content would otherwise cause false-positive pauses.
            combined = f"{stderr_text}\n{accumulated_text}"
            if not early_killed and is_credit_exhaustion(combined):
                resume_at = parse_credit_resume_time(combined)
                raise CreditExhaustedError(
                    "API credit limit reached", resume_at=resume_at
                )

            if usage_stats is not None:
                usage_stats.update(parser.usage_snapshot)

            transcript = (
                result_text or accumulated_text.rstrip("\n") or "\n".join(raw_lines)
            )

            # Log stderr when transcript is empty — this is the only place
            # stderr content is available and it's critical for diagnosing
            # silent subprocess failures (e.g. CLI auth errors, missing flags).
            if not transcript.strip() and stderr_text:
                logger.warning(
                    "Process produced empty stdout (rc=%d), stderr: %s",
                    proc.returncode or 0,
                    stderr_text[:500],
                )

            return transcript

        return await asyncio.wait_for(_stream_body(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Agent process timed out after {timeout}s") from None
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
