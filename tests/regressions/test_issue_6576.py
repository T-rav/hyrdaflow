"""Regression test for issue #6576.

``_check_gh_auth`` spawns ``gh auth status`` as an async subprocess. Without
a bounded ``proc.wait()``, a hung ``gh`` CLI (network proxy issue, credential
store deadlock) would block server startup forever.

By contrast, ``_check_docker()`` in the same file correctly uses
``subprocess.run(..., timeout=10)``.

These tests verify that ``_check_gh_auth`` (a) wraps ``proc.wait()`` in
``asyncio.wait_for`` with a bounded timeout, and (b) kills the hung process
on timeout. Whether the result is FAIL or WARN is a separate policy choice
(see ``test_preflight.py``); this file only guards against the unbounded-wait
regression.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from preflight import _check_gh_auth

# ---------------------------------------------------------------------------
# Test 1 — _check_gh_auth hangs indefinitely when proc.wait() never returns
# ---------------------------------------------------------------------------


class TestGhAuthTimeout:
    """_check_gh_auth must complete within a bounded time even when gh hangs."""

    @pytest.mark.asyncio
    async def test_check_gh_auth_completes_when_process_hangs(self) -> None:
        """If the gh subprocess hangs forever, _check_gh_auth must still
        return a result within a bounded time, not block forever.

        Simulates a hung process via a ``proc.wait()`` that sleeps
        indefinitely. The production timeout is patched to a small value so
        the test runs quickly; the outer ``asyncio.wait_for`` is the regression
        guard — if the inner timeout were missing, it would fire.
        """

        async def hang_forever() -> int:
            await asyncio.sleep(3600)
            return 0  # never reached

        mock_proc = MagicMock()
        mock_proc.wait = hang_forever
        mock_proc.kill = MagicMock()

        with (
            patch("preflight._GH_AUTH_TIMEOUT_S", 0.1),
            patch("preflight.shutil.which", return_value="/usr/bin/gh"),
            patch(
                "preflight.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ),
        ):
            try:
                result = await asyncio.wait_for(_check_gh_auth(), timeout=2.0)
            except TimeoutError:
                pytest.fail(
                    "_check_gh_auth blocked indefinitely when gh process hung — "
                    "proc.wait() has no timeout (issue #6576)"
                )

        # Returning at all (rather than hanging) is the regression guard.
        # Message must indicate the timeout path was taken.
        assert "did not complete" in result.message.lower(), (
            "_check_gh_auth should report the hang via its timeout branch, "
            f"but got: {result.message!r}"
        )


# ---------------------------------------------------------------------------
# Test 2 — _check_gh_auth must kill the hung subprocess before returning
# ---------------------------------------------------------------------------


class TestGhAuthKillsHungProcess:
    """When gh hangs and _check_gh_auth times out, it must kill the process."""

    @pytest.mark.asyncio
    async def test_hung_process_is_killed_on_timeout(self) -> None:
        """After timing out, the subprocess must be killed so it doesn't
        linger as an orphan.
        """

        async def hang_forever() -> int:
            await asyncio.sleep(3600)
            return 0

        mock_proc = MagicMock()
        mock_proc.wait = hang_forever
        mock_proc.kill = MagicMock()

        with (
            patch("preflight._GH_AUTH_TIMEOUT_S", 0.1),
            patch("preflight.shutil.which", return_value="/usr/bin/gh"),
            patch(
                "preflight.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ),
        ):
            try:
                await asyncio.wait_for(_check_gh_auth(), timeout=2.0)
            except TimeoutError:
                pytest.fail(
                    "_check_gh_auth blocked indefinitely — cannot verify "
                    "kill() behavior because timeout is missing (issue #6576)"
                )

        mock_proc.kill.assert_called_once()
