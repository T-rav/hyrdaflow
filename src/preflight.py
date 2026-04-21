"""Startup dependency health checks for HydraFlow."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
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

    # Plugin skill registry — verify required plugins are installed.
    # Language detection runs per-repo later; at preflight we only check Tier 1.
    results.append(_check_plugins(config, detected_languages=set()))

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
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=1.0)
        except TimeoutError:
            # Kill the hung process so it doesn't linger as an orphan (#6576).
            proc.kill()
            return CheckResult(
                "gh-auth",
                CheckStatus.FAIL,
                "gh auth status timed out after 1s — gh CLI appears hung",
            )
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


def _install_plugin(
    name: str, marketplace: str, *, timeout_s: int = 120
) -> tuple[bool, str]:
    """Attempt ``claude plugin install name@marketplace --scope user``.

    Returns ``(success, detail)`` where ``detail`` is the tail of stderr
    (or a human-readable error string) for logging.
    """

    argv = [
        "claude",
        "plugin",
        "install",
        f"{name}@{marketplace}",
        "--scope",
        "user",
    ]
    try:
        result = subprocess.run(  # noqa: S603
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return False, "`claude` binary not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"install timed out after {timeout_s}s"

    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, (result.stderr or result.stdout or "non-zero exit").strip()


def _check_plugins(  # noqa: PLR0911 — linear gate checks, each with its own return path
    config: HydraFlowConfig,
    *,
    cache_root: Path | None = None,
    detected_languages: set[str] | None = None,
) -> CheckResult:
    """Verify required plugins are installed under the plugin cache.

    - Tier 1 (``config.required_plugins``) missing → attempt auto-install when
      ``config.auto_install_plugins`` is True; otherwise FAIL immediately. FAIL
      with a rich error message if still missing after install.
    - Zero total skills discovered → FAIL.
    - Tier 2 plugin missing for a detected language → best-effort install, then
      WARN if still missing.
    - Everything present → PASS.
    """
    from plugin_skill_registry import (
        _DEFAULT_CACHE_ROOT,  # noqa: PLC0415 — private but already imported elsewhere
        discover_plugin_skills,  # noqa: PLC0415
        parse_plugin_spec,  # noqa: PLC0415
    )

    root = cache_root or _DEFAULT_CACHE_ROOT
    langs = detected_languages or set()

    if root.exists() and not root.is_dir():
        return CheckResult(
            "plugins",
            CheckStatus.FAIL,
            f"Plugin cache path exists but is not a directory: {root}",
        )

    # Collect Tier-1 + Tier-2 specs.
    tier1_specs: list[tuple[str, str]] = []
    for entry in config.required_plugins:
        try:
            tier1_specs.append(parse_plugin_spec(entry))
        except ValueError as exc:
            return CheckResult(
                "plugins", CheckStatus.FAIL, f"Bad required_plugins entry: {exc}"
            )

    tier2_specs: list[tuple[str, str, str]] = []  # (lang, name, marketplace)
    for lang in langs:
        for entry in config.language_plugins.get(lang, []):
            try:
                name, marketplace = parse_plugin_spec(entry)
            except ValueError as exc:
                return CheckResult(
                    "plugins", CheckStatus.FAIL, f"Bad language_plugins entry: {exc}"
                )
            tier2_specs.append((lang, name, marketplace))

    # Identify missing Tier-1 before any install attempt.
    missing_tier1 = [(n, m) for n, m in tier1_specs if not _plugin_exists(root, n)]

    install_errors: list[str] = []
    if missing_tier1 and config.auto_install_plugins:
        for name, marketplace in missing_tier1:
            ok, detail = _install_plugin(name, marketplace)
            if ok:
                logger.info("installed %s@%s", name, marketplace)
            else:
                install_errors.append(f"{name}@{marketplace}: {detail}")

    # Re-check after install attempt.
    still_missing = [(n, m) for n, m in tier1_specs if not _plugin_exists(root, n)]
    if still_missing:
        pretty = ", ".join(f"{n}@{m}" for n, m in still_missing)
        errors_block = (
            "\n".join(f"  {e}" for e in install_errors) or "  (auto-install disabled)"
        )
        return CheckResult(
            "plugins",
            CheckStatus.FAIL,
            (
                f"Plugin install failed for: {pretty}\n"
                f"Last errors:\n{errors_block}\n"
                "Manual fix:\n"
                "  make install-plugins          # preferred — reads config, installs all missing\n"
                "  # or per-plugin:\n"
                "  claude plugin install <name>@<marketplace> --scope user\n"
                "\nIf `claude plugin install` reports a login error, run:\n"
                "  claude login"
            ),
        )

    # Tier-2 install (best effort).
    if config.auto_install_plugins:
        for _lang, name, marketplace in tier2_specs:
            if not _plugin_exists(root, name):
                _install_plugin(name, marketplace)  # errors recorded in WARN below

    missing_tier2 = [
        (lang, n) for lang, n, _m in tier2_specs if not _plugin_exists(root, n)
    ]

    all_plugin_names = [n for n, _ in tier1_specs] + [n for _, n, _ in tier2_specs]
    skills = discover_plugin_skills(all_plugin_names, cache_root=root)
    if not skills:
        return CheckResult(
            "plugins",
            CheckStatus.FAIL,
            f"Plugin allowlist yielded 0 skills under {root}",
        )

    if missing_tier2:
        formatted = ", ".join(f"{n} (for {lang})" for lang, n in missing_tier2)
        return CheckResult(
            "plugins",
            CheckStatus.WARN,
            f"Language-conditional plugins missing: {formatted}",
        )

    return CheckResult(
        "plugins",
        CheckStatus.PASS,
        f"{len(skills)} plugin skills discovered",
    )


def _plugin_exists(cache_root: Path, plugin: str) -> bool:
    """Return True if ``plugin`` directory exists under any marketplace in ``cache_root``."""
    if not cache_root.is_dir():
        return False
    for marketplace_dir in cache_root.iterdir():
        if (marketplace_dir / plugin).is_dir():
            return True
    return False
