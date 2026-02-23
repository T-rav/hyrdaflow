"""Shared async subprocess helper for HydraFlow."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.subprocess")


class AuthenticationError(RuntimeError):
    """Raised when a subprocess fails due to GitHub authentication issues."""


class SubprocessTimeoutError(RuntimeError):
    """Raised when a subprocess exceeds its allowed execution time."""


class CreditExhaustedError(RuntimeError):
    """Raised when a subprocess fails because API credits are exhausted.

    Attributes
    ----------
    resume_at:
        The datetime (UTC) when credits are expected to reset, or ``None``
        if no reset time could be parsed from the error output.
    """

    def __init__(self, message: str = "", *, resume_at: datetime | None = None) -> None:
        super().__init__(message)
        self.resume_at = resume_at


_AUTH_PATTERNS = ("401", "not logged in", "authentication required", "auth token")

_CREDIT_PATTERNS = (
    "usage limit reached",
    "credit balance is too low",
)

# Matches e.g. "reset at 3pm (America/New_York)" or "reset at 3am"
_RESET_TIME_RE = re.compile(
    r"reset\s+at\s+(\d{1,2})\s*(am|pm)"
    r"(?:\s*\(([^)]+)\))?",
    re.IGNORECASE,
)


def is_credit_exhaustion(text: str) -> bool:
    """Check if *text* indicates an API credit exhaustion condition."""
    text_lower = text.lower()
    return any(p in text_lower for p in _CREDIT_PATTERNS)


def parse_credit_resume_time(text: str) -> datetime | None:
    """Extract the credit reset time from an error message.

    Looks for patterns like ``"reset at 3pm (America/New_York)"`` or
    ``"reset at 3am"``. Returns a timezone-aware UTC datetime, or
    ``None`` if no parseable time is found.

    When the parsed time is already past, we assume the reset is
    tomorrow at the same time.
    """
    match = _RESET_TIME_RE.search(text)
    if not match:
        return None

    hour = int(match.group(1))
    ampm = match.group(2).lower()
    tz_name = match.group(3)

    # Validate 12-hour clock range (1–12)
    if hour < 1 or hour > 12:
        return None

    # Convert 12-hour to 24-hour
    if ampm == "am":
        hour_24 = 0 if hour == 12 else hour
    else:
        hour_24 = hour if hour == 12 else hour + 12

    # Resolve timezone
    tz = UTC
    if tz_name:
        try:
            tz = ZoneInfo(tz_name.strip())
        except (KeyError, ValueError):
            logger.warning(
                "Could not parse timezone %r — falling back to local time", tz_name
            )
            tz = datetime.now().astimezone().tzinfo or UTC

    now = datetime.now(tz=tz)
    reset = now.replace(hour=hour_24, minute=0, second=0, microsecond=0)

    # If the reset time is already past, assume it means tomorrow
    if reset <= now:
        reset += timedelta(days=1)

    return reset.astimezone(UTC)


def _is_auth_error(stderr: str) -> bool:
    """Check if stderr indicates a GitHub authentication failure."""
    stderr_lower = stderr.lower()
    return any(p in stderr_lower for p in _AUTH_PATTERNS)


def make_clean_env(gh_token: str = "") -> dict[str, str]:
    """Build a subprocess env dict with ``CLAUDECODE`` stripped.

    When *gh_token* is non-empty it is injected as ``GH_TOKEN``.
    """
    env = {**os.environ}
    env.pop("CLAUDECODE", None)
    if gh_token:
        env["GH_TOKEN"] = gh_token
    return env


def make_docker_env(
    gh_token: str = "",
    git_user_name: str = "",
    git_user_email: str = "",
) -> dict[str, str]:
    """Build a minimal env dict for Docker container execution.

    Unlike :func:`make_clean_env` which inherits the full host env, this
    passes only the variables necessary for agent operation inside a container.
    """
    env: dict[str, str] = {"HOME": "/root"}

    if gh_token:
        env["GH_TOKEN"] = gh_token

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    if git_user_name:
        env["GIT_AUTHOR_NAME"] = git_user_name
        env["GIT_COMMITTER_NAME"] = git_user_name
    if git_user_email:
        env["GIT_AUTHOR_EMAIL"] = git_user_email
        env["GIT_COMMITTER_EMAIL"] = git_user_email

    return env


async def run_subprocess(
    *cmd: str,
    cwd: Path | None = None,
    gh_token: str = "",
    timeout: float = 120.0,
    runner: SubprocessRunner | None = None,
) -> str:
    """Run a subprocess and return stripped stdout.

    Strips the ``CLAUDECODE`` key from the environment to prevent
    nesting detection.  When *gh_token* is non-empty it is injected
    as ``GH_TOKEN``.

    Raises :class:`SubprocessTimeoutError` if the command exceeds *timeout* seconds.
    Raises :class:`RuntimeError` on non-zero exit.
    """
    from execution import get_default_runner

    env = make_clean_env(gh_token)

    if runner is None:
        runner = get_default_runner()
    try:
        result = await runner.run_simple(
            list(cmd),
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            timeout=timeout,
        )
    except TimeoutError:
        raise SubprocessTimeoutError(
            f"Command {cmd!r} timed out after {timeout}s"
        ) from None
    if result.returncode != 0:
        msg = f"Command {cmd!r} failed (rc={result.returncode}): {result.stderr}"
        if _is_auth_error(result.stderr):
            raise AuthenticationError(msg)
        raise RuntimeError(msg)
    return result.stdout


_RETRYABLE_PATTERNS = (
    "rate limit",
    "timeout",
    "timed out",
    "connection",
    "502",
    "503",
    "504",
)
_NON_RETRYABLE_PATTERNS = ("401", "403", "404")


def _is_retryable_error(stderr: str) -> bool:
    """Check if a subprocess error indicates a transient/retryable condition."""
    stderr_lower = stderr.lower()
    for pattern in _NON_RETRYABLE_PATTERNS:
        if pattern in stderr_lower:
            # 403 with "rate limit" IS retryable
            if pattern == "403" and "rate limit" in stderr_lower:
                continue
            return False
    return any(p in stderr_lower for p in _RETRYABLE_PATTERNS)


async def run_subprocess_with_retry(
    *cmd: str,
    cwd: Path | None = None,
    gh_token: str = "",
    max_retries: int = 3,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 30.0,
    timeout: float = 120.0,
    runner: SubprocessRunner | None = None,
) -> str:
    """Run a subprocess with exponential backoff retry on transient errors.

    Retries on: rate-limit, timeout, connection errors, 502/503/504.
    Does NOT retry on: auth (401), forbidden (403 without rate-limit), not-found (404).

    Raises :class:`RuntimeError` after all retries are exhausted.
    """
    last_error: RuntimeError | None = None
    for attempt in range(max_retries + 1):
        try:
            return await run_subprocess(
                *cmd, cwd=cwd, gh_token=gh_token, timeout=timeout, runner=runner
            )
        except RuntimeError as exc:
            if isinstance(exc, AuthenticationError | CreditExhaustedError):
                raise
            last_error = exc
            error_msg = str(exc)
            if attempt >= max_retries or not _is_retryable_error(error_msg):
                raise
            delay = min(base_delay_seconds * (2**attempt), max_delay_seconds)
            jitter = random.uniform(0, delay * 0.5)  # noqa: S311
            total_delay = delay + jitter
            logger.warning(
                "Retryable error (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                max_retries,
                total_delay,
                error_msg[:200],
            )
            await asyncio.sleep(total_delay)
    # Should not reach here, but satisfy type checker
    assert last_error is not None  # noqa: S101
    raise last_error
