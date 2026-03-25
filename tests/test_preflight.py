"""Tests for startup preflight dependency checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from preflight import (
    CheckResult,
    CheckStatus,
    _check_agent_cli,
    _check_disk_space,
    _check_docker,
    _check_gh_auth,
    _check_gh_cli,
    _check_git,
    _check_repo_root,
    log_preflight_results,
    run_preflight_checks,
)

# ---------------------------------------------------------------------------
# _check_git
# ---------------------------------------------------------------------------


def test_check_git_found() -> None:
    with patch("preflight.shutil.which", return_value="/usr/bin/git"):
        result = _check_git()
    assert result.status == CheckStatus.PASS
    assert result.name == "git"


def test_check_git_missing() -> None:
    with patch("preflight.shutil.which", return_value=None):
        result = _check_git()
    assert result.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# _check_gh_cli
# ---------------------------------------------------------------------------


def test_check_gh_cli_found() -> None:
    with patch("preflight.shutil.which", return_value="/usr/bin/gh"):
        result = _check_gh_cli()
    assert result.status == CheckStatus.PASS


def test_check_gh_cli_missing() -> None:
    with patch("preflight.shutil.which", return_value=None):
        result = _check_gh_cli()
    assert result.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# _check_gh_auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_gh_auth_ok() -> None:
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/gh"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await _check_gh_auth()
    assert result.status == CheckStatus.PASS


@pytest.mark.asyncio
async def test_check_gh_auth_not_authenticated() -> None:
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=1)
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/gh"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await _check_gh_auth()
    assert result.status == CheckStatus.FAIL
    assert "not authenticated" in result.message


@pytest.mark.asyncio
async def test_check_gh_auth_gh_missing() -> None:
    with patch("preflight.shutil.which", return_value=None):
        result = await _check_gh_auth()
    assert result.status == CheckStatus.FAIL
    assert "not found" in result.message


@pytest.mark.asyncio
async def test_check_gh_auth_oserror() -> None:
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/gh"),
        patch(
            "preflight.asyncio.create_subprocess_exec",
            side_effect=OSError("spawn failed"),
        ),
    ):
        result = await _check_gh_auth()
    assert result.status == CheckStatus.FAIL
    assert "spawn failed" in result.message


# ---------------------------------------------------------------------------
# _check_repo_root
# ---------------------------------------------------------------------------


def test_check_repo_root_valid(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = _check_repo_root(tmp_path)
    assert result.status == CheckStatus.PASS


def test_check_repo_root_no_git(tmp_path: Path) -> None:
    result = _check_repo_root(tmp_path)
    assert result.status == CheckStatus.WARN


def test_check_repo_root_missing() -> None:
    result = _check_repo_root(Path("/nonexistent/path"))
    assert result.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# _check_disk_space
# ---------------------------------------------------------------------------


def test_check_disk_space_plenty(tmp_path: Path) -> None:
    with patch(
        "preflight.shutil.disk_usage",
        return_value=MagicMock(free=10 * 1024**3),
    ):
        result = _check_disk_space(tmp_path)
    assert result.status == CheckStatus.PASS


def test_check_disk_space_low(tmp_path: Path) -> None:
    with patch(
        "preflight.shutil.disk_usage",
        return_value=MagicMock(free=500 * 1024**2),  # 500 MB
    ):
        result = _check_disk_space(tmp_path)
    assert result.status == CheckStatus.WARN
    assert "Low disk space" in result.message


def test_check_disk_space_oserror(tmp_path: Path) -> None:
    with patch("preflight.shutil.disk_usage", side_effect=OSError("no access")):
        result = _check_disk_space(tmp_path)
    assert result.status == CheckStatus.WARN


def test_check_disk_space_nonexistent_path() -> None:
    """Should walk up to find an existing ancestor."""
    with patch(
        "preflight.shutil.disk_usage",
        return_value=MagicMock(free=5 * 1024**3),
    ):
        result = _check_disk_space(Path("/tmp/nonexistent/deeply/nested"))
    assert result.status == CheckStatus.PASS


# ---------------------------------------------------------------------------
# _check_docker
# ---------------------------------------------------------------------------


def test_check_docker_missing() -> None:
    with patch("preflight.shutil.which", return_value=None):
        result = _check_docker()
    assert result.status == CheckStatus.FAIL
    assert "not found" in result.message


def test_check_docker_ok() -> None:
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run", return_value=MagicMock(returncode=0)),
    ):
        result = _check_docker()
    assert result.status == CheckStatus.PASS


def test_check_docker_daemon_down() -> None:
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run", return_value=MagicMock(returncode=1)),
    ):
        result = _check_docker()
    assert result.status == CheckStatus.FAIL
    assert "not reachable" in result.message


def test_check_docker_timeout() -> None:
    import subprocess

    with (
        patch("preflight.shutil.which", return_value="/usr/bin/docker"),
        patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired("docker info", 10),
        ),
    ):
        result = _check_docker()
    assert result.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# _check_agent_cli
# ---------------------------------------------------------------------------


def test_check_agent_cli_found() -> None:
    with patch("preflight.shutil.which", return_value="/usr/local/bin/claude"):
        result = _check_agent_cli("claude")
    assert result.status == CheckStatus.PASS
    assert result.name == "agent-cli-claude"


def test_check_agent_cli_missing() -> None:
    with patch("preflight.shutil.which", return_value=None):
        result = _check_agent_cli("codex")
    assert result.status == CheckStatus.WARN
    assert "codex" in result.message


# ---------------------------------------------------------------------------
# log_preflight_results
# ---------------------------------------------------------------------------


def test_log_preflight_results_all_pass() -> None:
    results = [
        CheckResult("a", CheckStatus.PASS, "ok"),
        CheckResult("b", CheckStatus.WARN, "meh"),
    ]
    assert log_preflight_results(results) is True


def test_log_preflight_results_has_fail() -> None:
    results = [
        CheckResult("a", CheckStatus.PASS, "ok"),
        CheckResult("b", CheckStatus.FAIL, "bad"),
    ]
    assert log_preflight_results(results) is False


def test_log_preflight_results_empty() -> None:
    assert log_preflight_results([]) is True


# ---------------------------------------------------------------------------
# run_preflight_checks integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_preflight_checks_host_mode(tmp_path: Path) -> None:
    """Covers the full run with execution_mode='host'."""
    config = MagicMock()
    config.repo_root = tmp_path
    config.data_root = tmp_path
    config.execution_mode = "host"
    config.implementation_tool = "claude"
    config.review_tool = "claude"
    config.planner_tool = "claude"

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with (
        patch("preflight.shutil.which", return_value="/usr/bin/git"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "preflight.shutil.disk_usage",
            return_value=MagicMock(free=10 * 1024**3),
        ),
    ):
        results = await run_preflight_checks(config)

    # git, gh-cli, gh-auth, repo-root, disk-space, 3x agent-cli
    assert len(results) == 8
    # No docker check in host mode
    assert not any(r.name == "docker" for r in results)


@pytest.mark.asyncio
async def test_run_preflight_checks_docker_mode(tmp_path: Path) -> None:
    """Docker mode adds a docker check."""
    config = MagicMock()
    config.repo_root = tmp_path
    config.data_root = tmp_path
    config.execution_mode = "docker"
    config.implementation_tool = "claude"
    config.review_tool = "claude"
    config.planner_tool = "claude"

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with (
        patch("preflight.shutil.which", return_value="/usr/bin/something"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "preflight.shutil.disk_usage",
            return_value=MagicMock(free=10 * 1024**3),
        ),
        patch("subprocess.run", return_value=MagicMock(returncode=0)),
    ):
        results = await run_preflight_checks(config)

    assert any(r.name == "docker" for r in results)
    assert len(results) == 9  # 8 base + docker


@pytest.mark.asyncio
async def test_run_preflight_checks_deduplicates_tools(tmp_path: Path) -> None:
    """When all tools are the same, we still get 3 agent-cli checks (one per field)."""
    config = MagicMock()
    config.repo_root = tmp_path
    config.data_root = tmp_path
    config.execution_mode = "host"
    config.implementation_tool = "codex"
    config.review_tool = "codex"
    config.planner_tool = "codex"

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with (
        patch("preflight.shutil.which", return_value="/usr/bin/x"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "preflight.shutil.disk_usage",
            return_value=MagicMock(free=10 * 1024**3),
        ),
    ):
        results = await run_preflight_checks(config)

    agent_checks = [r for r in results if r.name.startswith("agent-cli")]
    assert len(agent_checks) == 3


# ---------------------------------------------------------------------------
# server._run_preflight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_run_preflight_skipped() -> None:
    """skip_preflight=True bypasses checks."""
    from server import _run_preflight

    config = MagicMock()
    config.skip_preflight = True
    assert await _run_preflight(config) is True


@pytest.mark.asyncio
async def test_server_run_preflight_passes() -> None:
    """Healthy checks let startup proceed."""
    from server import _run_preflight

    config = MagicMock()
    config.skip_preflight = False

    with (
        patch(
            "preflight.run_preflight_checks",
            return_value=[CheckResult("a", CheckStatus.PASS, "ok")],
        ),
        patch("preflight.log_preflight_results", return_value=True),
    ):
        assert await _run_preflight(config) is True


@pytest.mark.asyncio
async def test_server_run_preflight_fails() -> None:
    """Failed checks block startup."""
    from server import _run_preflight

    config = MagicMock()
    config.skip_preflight = False

    with (
        patch(
            "preflight.run_preflight_checks",
            return_value=[CheckResult("a", CheckStatus.FAIL, "bad")],
        ),
        patch("preflight.log_preflight_results", return_value=False),
    ):
        assert await _run_preflight(config) is False


@pytest.mark.asyncio
async def test_server_run_aborts_on_preflight_failure() -> None:
    """_run should return early without calling dashboard/headless when preflight fails."""
    from server import _run

    config = MagicMock()
    config.skip_preflight = False
    config.dashboard_enabled = True

    with (
        patch("server._run_preflight", return_value=False),
        patch("server._run_with_dashboard") as mock_dash,
        patch("server._run_headless") as mock_headless,
    ):
        await _run(config)

    mock_dash.assert_not_called()
    mock_headless.assert_not_called()


@pytest.mark.asyncio
async def test_server_run_proceeds_on_preflight_success() -> None:
    """_run should proceed to dashboard when preflight passes."""
    from server import _run

    config = MagicMock()
    config.skip_preflight = False
    config.dashboard_enabled = True

    with (
        patch("server._run_preflight", return_value=True),
        patch("server._run_with_dashboard") as mock_dash,
    ):
        await _run(config)

    mock_dash.assert_called_once_with(config)
