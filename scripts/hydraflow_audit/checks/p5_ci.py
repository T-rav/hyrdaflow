"""P5 — CI, branch protection, hooks (ADR-0044)."""

from __future__ import annotations

import os
import re
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
def _branch_protection_cultural(ctx: CheckContext) -> Finding:  # noqa: PLR0911 — each fast-path WARN has a distinct reason
    """Probe the remote for branch protection when `gh` is available.

    If `gh api` reports protection on main (with required status checks or
    required reviews) we upgrade the finding to PASS. Offline or
    unauthenticated environments fall back to the original WARN, keeping
    the CULTURAL spirit of the check intact.
    """
    if not (ctx.root / ".git").exists():
        return _branch_protection_warn(
            "not a git repo — cannot query remote protection"
        )
    main_branch = _detect_main_branch(ctx.root)
    if main_branch is None:
        return _branch_protection_warn("no main/master branch detected locally")
    remote_slug = _detect_github_slug(ctx.root)
    if remote_slug is None:
        return _branch_protection_warn("no github.com remote — cannot query protection")
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{remote_slug}/branches/{main_branch}/protection"],
            check=False,
            cwd=ctx.root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return _branch_protection_warn(
            "`gh api` unavailable — confirm via GitHub repo settings"
        )
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        # A 404 on the classic endpoint just means no classic rule is set;
        # GitHub's newer Rulesets system lives at a different path. Query it
        # before concluding the branch is unprotected. Anything else (auth,
        # rate-limit, network) is an audit-infrastructure issue we can't
        # diagnose, so fall through to WARN.
        if "HTTP 404" in detail or "Branch not protected" in detail:
            return _branch_protection_from_rulesets(ctx.root, remote_slug, main_branch)
        last = detail.splitlines()[-1:] or ["unknown error"]
        return _branch_protection_warn(
            f"`gh api` could not verify protection ({last[0]}) — confirm in GitHub settings"
        )
    body = result.stdout.lower()
    if '"required_status_checks"' in body or '"required_pull_request_reviews"' in body:
        return finding(
            "P5.5", Status.PASS, f"classic branch protection active on {main_branch}"
        )
    return _branch_protection_warn(
        f"`gh api` returned a protection object for {main_branch} without required checks/reviews"
    )


_RULESET_MEANINGFUL_TYPES = {
    "pull_request",
    "required_status_checks",
    "non_fast_forward",
    "deletion",
    "required_signatures",
    "code_scanning",
    "code_quality",
    "required_linear_history",
    "required_deployments",
}


def _branch_protection_from_rulesets(
    root: Path, remote_slug: str, main_branch: str
) -> Finding:
    """Fall back to the GitHub Rulesets endpoint when classic protection is absent.

    Rulesets are the modern replacement for branch protection rules and do
    not surface through ``/branches/<b>/protection``. The
    ``/repos/<owner>/<repo>/rules/branches/<branch>`` endpoint lists the
    *effective* rules on a branch regardless of which system declared them.
    """
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{remote_slug}/rules/branches/{main_branch}"],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return _branch_protection_warn(
            f"`main` branch on {remote_slug} has no classic protection and rulesets "
            "endpoint did not respond — confirm in GitHub Settings → Rules → Rulesets"
        )
    if result.returncode != 0:
        return _branch_protection_warn(
            f"`main` branch on {remote_slug} is NOT protected (no classic rule and "
            "rulesets query failed) — enable in GitHub Settings → Rules"
        )
    present = _extract_ruleset_types(result.stdout)
    meaningful = present & _RULESET_MEANINGFUL_TYPES
    if not meaningful:
        return _branch_protection_warn(
            f"`main` branch on {remote_slug} is NOT protected (no classic rule and "
            "no meaningful ruleset entries) — enable in GitHub Settings → Rules"
        )
    summary = ", ".join(sorted(meaningful))
    return finding(
        "P5.5",
        Status.PASS,
        f"ruleset protection active on {main_branch}: {summary}",
    )


def _extract_ruleset_types(body: str) -> set[str]:
    """Parse the ``rules/branches/<b>`` JSON payload without importing json.

    The response shape is a list of ``{"type": "...", "ruleset_id": N, ...}``
    objects. A regex scan is safer than full JSON parsing here because the
    endpoint returns extra per-rule metadata we do not need to interpret.
    """
    return {match.group(1) for match in re.finditer(r'"type"\s*:\s*"([^"]+)"', body)}


def _branch_protection_warn(message: str) -> Finding:
    return finding("P5.5", Status.WARN, message)


def _detect_main_branch(root: Path) -> str | None:
    """Return the repo's default branch name, not the worktree's current HEAD.

    Order of preference:
      1. ``git remote show origin | HEAD branch`` — authoritative when online.
      2. A local ref to ``main`` or ``master`` (works in the primary checkout).
      3. The symbolic ref of ``origin/HEAD`` (a locally cached remote HEAD).
    """
    remote_default = _default_branch_from_remote(root)
    if remote_default:
        return remote_default
    for candidate in ("main", "master"):
        # Primary checkouts keep ``refs/heads/<name>`` on disk; worktrees
        # do not, so fall through to the packed-refs / origin/HEAD lookup.
        if (root / ".git" / "refs" / "heads" / candidate).exists():
            return candidate
    origin_head = _resolve_origin_head(root)
    if origin_head:
        return origin_head
    return None


def _default_branch_from_remote(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    # ``origin/main`` → ``main``.
    value = result.stdout.strip()
    return value.split("/", 1)[1] if value.startswith("origin/") else None


def _resolve_origin_head(root: Path) -> str | None:
    head_file = root / ".git" / "refs" / "remotes" / "origin" / "HEAD"
    if not head_file.exists():
        return None
    try:
        content = head_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    # Format: ``ref: refs/remotes/origin/<branch>``.
    if content.startswith("ref:"):
        target = content.split()[-1]
        return target.rsplit("/", 1)[-1] or None
    return None


def _detect_github_slug(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+)(?:\.git)?/?$", url)
    if not match:
        return None
    return match.group(1)


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
