"""Startup dependency health checks for HydraFlow."""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.preflight")


class CheckStatus(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str


async def run_preflight_checks(config: HydraFlowConfig) -> list[CheckResult]:
    """Run all preflight checks and return results."""
    results: list[CheckResult] = []
    results.append(_check_git())
    results.append(_check_gh_cli())
    results.append(await _check_gh_auth())
    results.append(_check_repo_root(config.repo_root))
    results.append(_check_disk_space(config.data_root))
    if config.execution_mode == "docker":
        results.append(_check_docker())
    # Check configured agent CLIs
    for tool_field in ("implementation_tool", "review_tool", "planner_tool"):
        tool = getattr(config, tool_field)
        if tool != "inherit":
            results.append(_check_agent_cli(tool))
    return results


def _check_git() -> CheckResult:
    """Check that git is available on PATH."""
    if shutil.which("git"):
        return CheckResult("git", CheckStatus.PASS, "git found on PATH")
    return CheckResult("git", CheckStatus.FAIL, "git not found on PATH")


def _check_gh_cli() -> CheckResult:
    """Check that the GitHub CLI is available on PATH."""
    if shutil.which("gh"):
        return CheckResult("gh-cli", CheckStatus.PASS, "gh CLI found on PATH")
    return CheckResult("gh-cli", CheckStatus.FAIL, "gh CLI not found on PATH")


async def _check_gh_auth() -> CheckResult:
    """Check that gh CLI is authenticated."""
    if not shutil.which("gh"):
        return CheckResult(
            "gh-auth", CheckStatus.FAIL, "gh CLI not found — cannot check auth"
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "auth",
            "status",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        if rc == 0:
            return CheckResult("gh-auth", CheckStatus.PASS, "gh CLI authenticated")
        return CheckResult(
            "gh-auth",
            CheckStatus.FAIL,
            "gh CLI not authenticated (run 'gh auth login')",
        )
    except OSError as exc:
        return CheckResult("gh-auth", CheckStatus.FAIL, f"gh auth check failed: {exc}")


def _check_repo_root(path: Path) -> CheckResult:
    """Check that repo_root exists and contains a .git directory."""
    if not path.exists():
        return CheckResult(
            "repo-root", CheckStatus.FAIL, f"repo_root does not exist: {path}"
        )
    if not (path / ".git").exists():
        return CheckResult(
            "repo-root", CheckStatus.WARN, f"repo_root has no .git directory: {path}"
        )
    return CheckResult("repo-root", CheckStatus.PASS, f"repo_root valid: {path}")


def _check_disk_space(path: Path) -> CheckResult:
    """Warn if less than 1 GB free disk space at the given path."""
    try:
        resolved = path if path.exists() else path.parent
        # Walk up to find an existing ancestor
        while not resolved.exists() and resolved != resolved.parent:
            resolved = resolved.parent
        usage = shutil.disk_usage(resolved)
        free_gb = usage.free / (1024**3)
        if free_gb < 1.0:
            return CheckResult(
                "disk-space",
                CheckStatus.WARN,
                f"Low disk space: {free_gb:.2f} GB free at {path}",
            )
        return CheckResult(
            "disk-space",
            CheckStatus.PASS,
            f"{free_gb:.1f} GB free at {path}",
        )
    except OSError as exc:
        return CheckResult(
            "disk-space", CheckStatus.WARN, f"Could not check disk space: {exc}"
        )


def _check_docker() -> CheckResult:
    """Check that Docker is available and responsive."""
    if not shutil.which("docker"):
        return CheckResult("docker", CheckStatus.FAIL, "docker not found on PATH")
    import subprocess  # noqa: PLC0415

    try:
        result = subprocess.run(  # noqa: S603, S607
            ["docker", "info"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return CheckResult("docker", CheckStatus.PASS, "Docker daemon reachable")
        return CheckResult("docker", CheckStatus.FAIL, "Docker daemon not reachable")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult("docker", CheckStatus.FAIL, f"Docker check failed: {exc}")


def _check_agent_cli(tool: str) -> CheckResult:
    """Check that the agent CLI binary is on PATH."""
    binary = tool  # claude, codex, pi — the binary name matches the tool name
    if shutil.which(binary):
        return CheckResult(
            f"agent-cli-{tool}", CheckStatus.PASS, f"{binary} found on PATH"
        )
    return CheckResult(
        f"agent-cli-{tool}",
        CheckStatus.WARN,
        f"{binary} not found on PATH (needed for {tool} tool)",
    )


def log_preflight_results(results: list[CheckResult]) -> bool:
    """Log each preflight result and return True if no FAIL results."""
    for r in results:
        if r.status == CheckStatus.PASS:
            logger.info("[PASS] %s — %s", r.name, r.message)
        elif r.status == CheckStatus.WARN:
            logger.warning("[WARN] %s — %s", r.name, r.message)
        else:
            logger.error("[FAIL] %s — %s", r.name, r.message)
    return not any(r.status == CheckStatus.FAIL for r in results)
