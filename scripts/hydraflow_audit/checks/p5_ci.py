"""P5 — CI, branch protection, hooks (ADR-0044)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import finding
from .p3_testing import _load_pyproject


@register("P5.1")
def _workflows_exist(ctx: CheckContext) -> Finding:
    wf_dir = ctx.root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return finding("P5.1", Status.FAIL, ".github/workflows/ missing")
    workflows = list(wf_dir.rglob("*.y*ml"))
    if workflows:
        return finding("P5.1", Status.PASS, f"{len(workflows)} workflow(s)")
    return finding("P5.1", Status.FAIL, ".github/workflows/ has no .yml files")


def _grep_workflows(ctx: CheckContext, needle: str) -> bool:
    wf_dir = ctx.root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return False
    for yml in wf_dir.rglob("*.y*ml"):
        if needle in yml.read_text(encoding="utf-8", errors="replace"):
            return True
    return False


@register("P5.2")
def _workflow_runs_quality_lite(ctx: CheckContext) -> Finding:
    if _grep_workflows(ctx, "quality-lite") or _grep_workflows(ctx, "quality_lite"):
        return finding("P5.2", Status.PASS)
    return finding(
        "P5.2",
        Status.FAIL,
        "no workflow references `quality-lite` (or `quality_lite`)",
    )


@register("P5.3")
def _workflow_runs_coverage_gate(ctx: CheckContext) -> Finding:
    if _grep_workflows(ctx, "cov-fail-under") or _grep_workflows(ctx, "cov_fail_under"):
        return finding("P5.3", Status.PASS)
    return finding(
        "P5.3",
        Status.FAIL,
        "no workflow enforces `--cov-fail-under` on the test job",
    )


@register("P5.4")
def _pre_commit_hook(ctx: CheckContext) -> Finding:
    hook = ctx.root / ".githooks" / "pre-commit"
    if not hook.exists():
        return finding("P5.4", Status.FAIL, ".githooks/pre-commit missing")
    if not os.access(hook, os.X_OK):
        return finding("P5.4", Status.FAIL, ".githooks/pre-commit is not executable")
    return finding("P5.4", Status.PASS)


@register("P5.5")
def _branch_protection_cultural(_: CheckContext) -> Finding:
    return finding(
        "P5.5",
        Status.WARN,
        "branch protection cannot be verified offline — confirm via GitHub repo settings",
    )


@register("P5.6")
def _no_direct_pushes_to_main(ctx: CheckContext) -> Finding:
    """Warn when recent main-branch history has commits not reached via merge."""
    if not (ctx.root / ".git").exists():
        return finding("P5.6", Status.NA, "not a git repo — cannot inspect history")
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--no-merges",
                "--first-parent",
                "main",
                "-n",
                "100",
                "--format=%H %s",
            ],
            check=False,
            cwd=ctx.root,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return finding("P5.6", Status.NA, "git log timed out — skipping")
    if result.returncode != 0:
        return finding("P5.6", Status.NA, "git log failed — skipping (no main branch?)")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    # Squash-merge workflows leave non-merge commits on main, but each one
    # still went through a PR — GitHub appends `(#NNN)` to the subject.
    # Commits without that marker are the real signal of direct pushes.
    unattributed = [line for line in lines if not _has_pr_attribution(line)]
    if len(unattributed) < 10:
        return finding(
            "P5.6",
            Status.PASS,
            f"{len(unattributed)} commits without PR attribution in last {len(lines)}",
        )
    return finding(
        "P5.6",
        Status.WARN,
        f"{len(unattributed)} of last {len(lines)} main commits lack PR attribution — "
        "check branch protection on the remote",
    )


def _has_pr_attribution(log_line: str) -> bool:
    """True when the commit subject ends with `(#NNN)` — a GitHub PR marker."""
    import re

    return bool(re.search(r"\(#\d+\)\s*$", log_line))


@register("P5.7")
def _warnings_as_errors(ctx: CheckContext) -> Finding:
    data = _load_pyproject(ctx.root)
    if data is None:
        return finding("P5.7", Status.FAIL, "pyproject.toml missing")
    pytest_cfg = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    filterwarnings = pytest_cfg.get("filterwarnings", [])
    if isinstance(filterwarnings, str):
        filterwarnings = [filterwarnings]
    runtime = any("error::RuntimeWarning" in f for f in filterwarnings)
    unraisable = any("PytestUnraisableExceptionWarning" in f for f in filterwarnings)
    if runtime and unraisable:
        return finding("P5.7", Status.PASS)
    missing: list[str] = []
    if not runtime:
        missing.append("error::RuntimeWarning")
    if not unraisable:
        missing.append("error::pytest.PytestUnraisableExceptionWarning")
    return finding(
        "P5.7",
        Status.FAIL,
        f"pytest filterwarnings missing: {', '.join(missing)}",
    )


@register("P5.8")
def _pre_push_hook(ctx: CheckContext) -> Finding:
    hook = ctx.root / ".githooks" / "pre-push"
    if not hook.exists():
        return finding("P5.8", Status.FAIL, ".githooks/pre-push missing")
    text = hook.read_text(encoding="utf-8", errors="replace")
    if "quality-lite" not in text and "quality_lite" not in text:
        return finding(
            "P5.8",
            Status.WARN,
            ".githooks/pre-push present but does not reference `quality-lite`",
        )
    return finding("P5.8", Status.PASS)


@register("P5.9")
def _self_repair_in_pre_commit(ctx: CheckContext) -> Finding:
    hook = ctx.root / ".githooks" / "pre-commit"
    if not hook.exists():
        return finding("P5.9", Status.FAIL, ".githooks/pre-commit missing")
    text = hook.read_text(encoding="utf-8", errors="replace")
    if "lint-fix" in text or "lint_fix" in text:
        return finding("P5.9", Status.PASS)
    return finding(
        "P5.9",
        Status.FAIL,
        "pre-commit hook does not invoke `lint-fix` — self-repair pattern missing",
    )


@register("P5.10")
def _claude_md_guard(ctx: CheckContext) -> Finding:
    hook = ctx.root / ".githooks" / "pre-commit"
    if not hook.exists():
        return finding("P5.10", Status.FAIL, ".githooks/pre-commit missing")
    text = hook.read_text(encoding="utf-8", errors="replace")
    if "CLAUDE.md" in text:
        return finding("P5.10", Status.PASS)
    return finding(
        "P5.10",
        Status.FAIL,
        "pre-commit hook does not mention CLAUDE.md — deletion/removal guard missing",
    )


_ = Path  # keep type used via runtime checks
