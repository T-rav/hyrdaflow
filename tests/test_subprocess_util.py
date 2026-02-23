"""Tests for the shared subprocess helper."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from subprocess_util import (
    AuthenticationError,
    CreditExhaustedError,
    SubprocessTimeoutError,
    _is_auth_error,
    _is_retryable_error,
    make_clean_env,
    make_docker_env,
    run_subprocess,
    run_subprocess_with_retry,
)


def _make_proc(
    returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""
) -> AsyncMock:
    """Build a minimal mock subprocess object."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


# --- success path ---


@pytest.mark.asyncio
async def test_returns_stdout_on_success() -> None:
    proc = _make_proc(stdout=b"  hello world  ")
    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        result = await run_subprocess("echo", "hi")

    assert result == "hello world"
    mock_exec.assert_awaited_once()


# --- error path ---


@pytest.mark.asyncio
async def test_raises_runtime_error_on_nonzero_exit() -> None:
    proc = _make_proc(returncode=1, stderr=b"boom")
    with (
        patch("asyncio.create_subprocess_exec", return_value=proc),
        pytest.raises(RuntimeError, match=r"boom"),
    ):
        await run_subprocess("false")


@pytest.mark.asyncio
async def test_error_message_includes_command_and_returncode() -> None:
    proc = _make_proc(returncode=42, stderr=b"bad stuff")
    with (
        patch("asyncio.create_subprocess_exec", return_value=proc),
        pytest.raises(RuntimeError, match=r"rc=42") as exc_info,
    ):
        await run_subprocess("git", "status")
    assert "('git', 'status')" in str(exc_info.value)


# --- environment ---


@pytest.mark.asyncio
async def test_strips_claudecode_from_env() -> None:
    proc = _make_proc()
    with (
        patch.dict("os.environ", {"CLAUDECODE": "1", "HOME": "/tmp"}, clear=False),
        patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
    ):
        await run_subprocess("ls")

    call_kwargs = mock_exec.call_args.kwargs
    assert "CLAUDECODE" not in call_kwargs["env"]


@pytest.mark.asyncio
async def test_sets_gh_token_when_provided() -> None:
    proc = _make_proc()
    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await run_subprocess("gh", "pr", "list", gh_token="ghp_secret")

    call_kwargs = mock_exec.call_args.kwargs
    assert call_kwargs["env"]["GH_TOKEN"] == "ghp_secret"


@pytest.mark.asyncio
async def test_no_gh_token_when_empty() -> None:
    """When gh_token is empty, GH_TOKEN is not injected into the env."""
    proc = _make_proc()
    env_without_token = {"HOME": "/tmp", "PATH": "/usr/bin"}
    with (
        patch.dict("os.environ", env_without_token, clear=True),
        patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
    ):
        await run_subprocess("gh", "pr", "list", gh_token="")

    call_kwargs = mock_exec.call_args.kwargs
    assert "GH_TOKEN" not in call_kwargs["env"]


@pytest.mark.asyncio
async def test_does_not_inject_gh_token_when_absent_from_env() -> None:
    proc = _make_proc()
    env_without_token = {"HOME": "/tmp", "PATH": "/usr/bin"}
    with (
        patch.dict("os.environ", env_without_token, clear=True),
        patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
    ):
        await run_subprocess("ls", gh_token="")

    call_kwargs = mock_exec.call_args.kwargs
    assert "GH_TOKEN" not in call_kwargs["env"]


# --- cwd ---


@pytest.mark.asyncio
async def test_passes_cwd_when_provided() -> None:
    proc = _make_proc()
    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await run_subprocess("ls", cwd=Path("/some/dir"))

    call_kwargs = mock_exec.call_args.kwargs
    assert call_kwargs["cwd"] == "/some/dir"


@pytest.mark.asyncio
async def test_no_cwd_when_none() -> None:
    proc = _make_proc()
    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await run_subprocess("ls")

    call_kwargs = mock_exec.call_args.kwargs
    assert call_kwargs["cwd"] is None


# --- make_clean_env ---


def test_make_clean_env_strips_claudecode() -> None:
    with patch.dict("os.environ", {"CLAUDECODE": "1", "HOME": "/tmp"}, clear=False):
        env = make_clean_env()
    assert "CLAUDECODE" not in env


def test_make_clean_env_preserves_other_vars() -> None:
    with patch.dict("os.environ", {"FOO": "bar", "HOME": "/tmp"}, clear=True):
        env = make_clean_env()
    assert env["FOO"] == "bar"
    assert env["HOME"] == "/tmp"


def test_make_clean_env_sets_gh_token() -> None:
    env = make_clean_env(gh_token="ghp_secret")
    assert env["GH_TOKEN"] == "ghp_secret"


def test_make_clean_env_no_gh_token() -> None:
    env_without_token = {"HOME": "/tmp", "PATH": "/usr/bin"}
    with patch.dict("os.environ", env_without_token, clear=True):
        env = make_clean_env()
    assert "GH_TOKEN" not in env


def test_make_clean_env_does_not_mutate_os_environ() -> None:
    with patch.dict("os.environ", {"CLAUDECODE": "1"}, clear=False):
        make_clean_env(gh_token="ghp_secret")
        # Verify os.environ was NOT mutated inside the same context:
        # CLAUDECODE should still be present (not popped from the real env)
        import os

        assert os.environ.get("CLAUDECODE") == "1"


# --- _is_retryable_error ---


class TestIsRetryableError:
    """Tests for the _is_retryable_error helper."""

    def test_retryable_on_rate_limit(self) -> None:
        assert _is_retryable_error("API rate limit exceeded") is True

    def test_retryable_on_timeout(self) -> None:
        assert _is_retryable_error("connection timeout") is True

    def test_retryable_on_connection_error(self) -> None:
        assert _is_retryable_error("connection refused") is True

    def test_retryable_on_502(self) -> None:
        assert _is_retryable_error("502 Bad Gateway") is True

    def test_retryable_on_503(self) -> None:
        assert _is_retryable_error("503 Service Unavailable") is True

    def test_retryable_on_504(self) -> None:
        assert _is_retryable_error("504 Gateway Timeout") is True

    def test_not_retryable_on_401(self) -> None:
        assert _is_retryable_error("401 Unauthorized") is False

    def test_not_retryable_on_403_without_rate_limit(self) -> None:
        assert _is_retryable_error("403 Forbidden") is False

    def test_retryable_on_403_with_rate_limit(self) -> None:
        assert _is_retryable_error("403 rate limit exceeded") is True

    def test_not_retryable_on_404(self) -> None:
        assert _is_retryable_error("404 Not Found") is False

    def test_not_retryable_on_generic_error(self) -> None:
        assert _is_retryable_error("something else went wrong") is False


# --- run_subprocess_with_retry ---


class TestRunSubprocessWithRetry:
    """Tests for run_subprocess_with_retry."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self) -> None:
        with patch(
            "subprocess_util.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = "ok"
            result = await run_subprocess_with_retry("gh", "pr", "list")
        assert result == "ok"
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_succeeds_after_transient_failure(self) -> None:
        with (
            patch("subprocess_util.run_subprocess", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_run.side_effect = [
                RuntimeError("Command failed (rc=1): 503 Service Unavailable"),
                "ok",
            ]
            result = await run_subprocess_with_retry("gh", "pr", "list", max_retries=3)
        assert result == "ok"
        assert mock_run.await_count == 2
        mock_sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exhausts_all_attempts(self) -> None:
        with (
            patch("subprocess_util.run_subprocess", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.side_effect = RuntimeError("Command failed (rc=1): timeout")
            with pytest.raises(RuntimeError, match="timeout"):
                await run_subprocess_with_retry("gh", "pr", "list", max_retries=2)
        # 1 initial + 2 retries = 3 total calls
        assert mock_run.await_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(self) -> None:
        with patch(
            "subprocess_util.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = RuntimeError(
                "Command failed (rc=1): 401 Unauthorized"
            )
            with pytest.raises(RuntimeError, match="401"):
                await run_subprocess_with_retry("gh", "pr", "list")
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_retry_on_404(self) -> None:
        with patch(
            "subprocess_util.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = RuntimeError("Command failed (rc=1): 404 Not Found")
            with pytest.raises(RuntimeError, match="404"):
                await run_subprocess_with_retry("gh", "pr", "list")
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_retry_on_403_without_rate_limit(self) -> None:
        with patch(
            "subprocess_util.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = RuntimeError("Command failed (rc=1): 403 Forbidden")
            with pytest.raises(RuntimeError, match="403"):
                await run_subprocess_with_retry("gh", "pr", "list")
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retry_on_403_rate_limit(self) -> None:
        with (
            patch("subprocess_util.run_subprocess", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.side_effect = [
                RuntimeError("Command failed (rc=1): 403 rate limit exceeded"),
                "ok",
            ]
            result = await run_subprocess_with_retry("gh", "pr", "list", max_retries=3)
        assert result == "ok"
        assert mock_run.await_count == 2

    @pytest.mark.asyncio
    async def test_backoff_increases_exponentially(self) -> None:
        with (
            patch("subprocess_util.run_subprocess", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch("random.uniform", return_value=0.0),
        ):
            mock_run.side_effect = [
                RuntimeError("Command failed (rc=1): 503"),
                RuntimeError("Command failed (rc=1): 503"),
                RuntimeError("Command failed (rc=1): 503"),
                "ok",
            ]
            await run_subprocess_with_retry(
                "gh",
                "pr",
                "list",
                max_retries=3,
                base_delay_seconds=1.0,
            )
        # With jitter=0: delays should be 1.0, 2.0, 4.0
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    async def test_max_delay_cap(self) -> None:
        with (
            patch("subprocess_util.run_subprocess", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch("random.uniform", return_value=0.0),
        ):
            mock_run.side_effect = [
                RuntimeError("Command failed (rc=1): 503"),
                RuntimeError("Command failed (rc=1): 503"),
                "ok",
            ]
            await run_subprocess_with_retry(
                "gh",
                "pr",
                "list",
                max_retries=2,
                base_delay_seconds=10.0,
                max_delay_seconds=15.0,
            )
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        # Attempt 0: min(10*2^0, 15) = 10, attempt 1: min(10*2^1, 15) = 15
        assert delays == [10.0, 15.0]

    @pytest.mark.asyncio
    async def test_zero_max_retries_no_retry(self) -> None:
        with patch(
            "subprocess_util.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = RuntimeError("Command failed (rc=1): 503")
            with pytest.raises(RuntimeError, match="503"):
                await run_subprocess_with_retry("gh", "pr", "list", max_retries=0)
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_retry_on_credit_exhausted_error(self) -> None:
        """CreditExhaustedError should propagate immediately without any retry."""
        with patch(
            "subprocess_util.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = CreditExhaustedError("API credit limit reached")
            with pytest.raises(CreditExhaustedError, match="credit limit"):
                await run_subprocess_with_retry("gh", "pr", "list", max_retries=3)
        # Should not retry — only one call
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_through_cmd_and_kwargs(self) -> None:
        with patch(
            "subprocess_util.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = "ok"
            await run_subprocess_with_retry(
                "gh",
                "pr",
                "list",
                cwd=Path("/tmp/test"),
                gh_token="ghp_test",
                max_retries=1,
            )
        mock_run.assert_awaited_once_with(
            "gh",
            "pr",
            "list",
            cwd=Path("/tmp/test"),
            gh_token="ghp_test",
            timeout=120.0,
            runner=None,
        )


# --- AuthenticationError ---


class TestAuthenticationError:
    """Tests for AuthenticationError and _is_auth_error."""

    def test_auth_error_inherits_runtime_error(self) -> None:
        err = AuthenticationError("auth failed")
        assert isinstance(err, RuntimeError)

    def test_is_auth_error_detects_401(self) -> None:
        assert _is_auth_error("HTTP 401 Unauthorized") is True

    def test_is_auth_error_detects_not_logged_in(self) -> None:
        assert _is_auth_error("gh: not logged in to github.com") is True

    def test_is_auth_error_detects_authentication_required(self) -> None:
        assert _is_auth_error("authentication required") is True

    def test_is_auth_error_detects_auth_token(self) -> None:
        assert _is_auth_error("invalid auth token") is True

    def test_is_auth_error_rejects_generic_error(self) -> None:
        assert _is_auth_error("something else went wrong") is False

    @pytest.mark.asyncio
    async def test_run_subprocess_raises_auth_error_on_401(self) -> None:
        proc = _make_proc(returncode=1, stderr=b"HTTP 401 Unauthorized")
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(AuthenticationError, match="401"),
        ):
            await run_subprocess("gh", "pr", "list")

    @pytest.mark.asyncio
    async def test_run_subprocess_raises_auth_error_on_not_logged_in(self) -> None:
        proc = _make_proc(returncode=1, stderr=b"not logged in to github.com")
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(AuthenticationError, match="not logged in"),
        ):
            await run_subprocess("gh", "auth", "status")

    @pytest.mark.asyncio
    async def test_run_subprocess_with_retry_raises_auth_error(self) -> None:
        with patch(
            "subprocess_util.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = AuthenticationError(
                "Command failed (rc=1): 401 Unauthorized"
            )
            with pytest.raises(AuthenticationError, match="401"):
                await run_subprocess_with_retry("gh", "pr", "list", max_retries=3)
        # Should not retry — only one call
        mock_run.assert_awaited_once()


# --- SubprocessTimeoutError ---


class TestSubprocessTimeoutError:
    """Tests for SubprocessTimeoutError."""

    def test_inherits_runtime_error(self) -> None:
        err = SubprocessTimeoutError("timed out")
        assert isinstance(err, RuntimeError)

    def test_message_preserved(self) -> None:
        err = SubprocessTimeoutError("Command timed out after 120s")
        assert "timed out after 120s" in str(err)


# --- Timeout behavior ---


class TestRunSubprocessTimeout:
    """Tests for run_subprocess timeout behavior."""

    @pytest.mark.asyncio
    async def test_timeout_kills_process_and_raises(self) -> None:
        """When proc.communicate exceeds timeout, process is killed and error raised."""
        proc = AsyncMock()
        proc.returncode = None
        proc.communicate = AsyncMock(side_effect=TimeoutError)
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch("asyncio.wait_for", side_effect=TimeoutError),
            pytest.raises(SubprocessTimeoutError, match="timed out"),
        ):
            await run_subprocess("sleep", "999", timeout=1.0)
        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_default_timeout_is_120(self) -> None:
        """Default timeout should be 120 seconds."""
        import inspect

        sig = inspect.signature(run_subprocess)
        assert sig.parameters["timeout"].default == 120.0

    @pytest.mark.asyncio
    async def test_custom_timeout_value(self) -> None:
        """Custom timeout should be passed to wait_for."""
        proc = _make_proc(stdout=b"ok")
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch("asyncio.wait_for", wraps=asyncio.wait_for) as mock_wait_for,
        ):
            await run_subprocess("echo", "hi", timeout=60.0)
        mock_wait_for.assert_awaited_once()
        # The timeout kwarg should be 60.0
        assert mock_wait_for.call_args.kwargs.get("timeout") == 60.0


class TestRetryWithTimeout:
    """Tests for run_subprocess_with_retry timeout interactions."""

    @pytest.mark.asyncio
    async def test_retry_retries_on_timeout(self) -> None:
        """SubprocessTimeoutError should be retried (matches 'timed out' pattern)."""
        with (
            patch("subprocess_util.run_subprocess", new_callable=AsyncMock) as mock_run,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_run.side_effect = [
                SubprocessTimeoutError("Command ('gh',) timed out after 120s"),
                "ok",
            ]
            result = await run_subprocess_with_retry("gh", "pr", "list", max_retries=3)
        assert result == "ok"
        assert mock_run.await_count == 2

    @pytest.mark.asyncio
    async def test_retry_passes_timeout_to_run_subprocess(self) -> None:
        """run_subprocess_with_retry should forward timeout kwarg."""
        with patch(
            "subprocess_util.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = "ok"
            await run_subprocess_with_retry(
                "gh", "pr", "list", timeout=60.0, max_retries=1
            )
        mock_run.assert_awaited_once_with(
            "gh",
            "pr",
            "list",
            cwd=None,
            gh_token="",
            timeout=60.0,
            runner=None,
        )


# --- make_docker_env ---


class TestMakeDockerEnv:
    """Tests for the make_docker_env helper."""

    def test_sets_home_to_root(self) -> None:
        env = make_docker_env()
        assert env["HOME"] == "/root"

    def test_includes_only_allowed_vars_when_empty(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            env = make_docker_env()
        assert set(env.keys()) == {"HOME"}

    def test_injects_gh_token(self) -> None:
        env = make_docker_env(gh_token="ghp_test123")
        assert env["GH_TOKEN"] == "ghp_test123"

    def test_no_gh_token_when_empty(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            env = make_docker_env(gh_token="")
        assert "GH_TOKEN" not in env

    def test_injects_anthropic_key_from_environ(self) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True):
            env = make_docker_env()
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"

    def test_no_anthropic_key_when_absent(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            env = make_docker_env()
        assert "ANTHROPIC_API_KEY" not in env

    def test_sets_git_identity(self) -> None:
        env = make_docker_env(git_user_name="Bot", git_user_email="bot@test.com")
        assert env["GIT_AUTHOR_NAME"] == "Bot"
        assert env["GIT_COMMITTER_NAME"] == "Bot"
        assert env["GIT_AUTHOR_EMAIL"] == "bot@test.com"
        assert env["GIT_COMMITTER_EMAIL"] == "bot@test.com"

    def test_no_git_identity_when_empty(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            env = make_docker_env(git_user_name="", git_user_email="")
        assert "GIT_AUTHOR_NAME" not in env
        assert "GIT_COMMITTER_NAME" not in env
        assert "GIT_AUTHOR_EMAIL" not in env
        assert "GIT_COMMITTER_EMAIL" not in env

    def test_excludes_host_path(self) -> None:
        with patch.dict(
            "os.environ", {"PATH": "/usr/bin", "PYTHONPATH": "/lib"}, clear=True
        ):
            env = make_docker_env()
        assert "PATH" not in env
        assert "PYTHONPATH" not in env

    def test_excludes_host_specific_vars(self) -> None:
        host_vars = {
            "SHELL": "/bin/zsh",
            "TERM": "xterm-256color",
            "USER": "dev",
            "LANG": "en_US.UTF-8",
            "CLAUDECODE": "1",
        }
        with patch.dict("os.environ", host_vars, clear=True):
            env = make_docker_env()
        for var in host_vars:
            assert var not in env

    def test_all_vars_combined(self) -> None:
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_API_KEY": "sk-test", "PATH": "/usr/bin"},
            clear=True,
        ):
            env = make_docker_env(
                gh_token="ghp_abc",
                git_user_name="Agent",
                git_user_email="agent@example.com",
            )
        expected_keys = {
            "HOME",
            "GH_TOKEN",
            "ANTHROPIC_API_KEY",
            "GIT_AUTHOR_NAME",
            "GIT_COMMITTER_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_EMAIL",
        }
        assert set(env.keys()) == expected_keys
