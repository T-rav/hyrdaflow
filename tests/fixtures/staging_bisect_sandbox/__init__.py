"""Scripted fixture for ``StagingBisectLoop`` E2E tests (spec §4.3 Task 24).

Why a scripted init instead of a checked-in ``.git/``?

Git does not track nested ``.git`` directories well and pre-commit hooks
would fight with a checked-in one. The helper below initialises a small
three-commit micro-repo on-demand inside a caller-supplied directory
(typically ``tmp_path`` from pytest), which keeps the fixture hermetic
and idempotent across test invocations:

- commit A (green)    — ``probe.sh`` exits 0
- commit B (culprit)  — ``probe.sh`` flipped to ``exit 1``
- commit C (red HEAD) — unrelated follow-up commit that keeps the bug

The shape matches the test scaffold in
``docs/superpowers/plans/2026-04-22-staging-red-attribution-bisect.md``
(§4.3 Task 23, hoisted into Task 24 under this name).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def init_three_commit_repo(repo_root: Path) -> tuple[str, str, str]:
    """Create a git repo with three commits: good, culprit (bad), HEAD.

    The helper is idempotent: if ``repo_root`` already contains a ``.git``
    directory it is wiped first so re-invocation produces deterministic
    SHAs for the calling test. ``repo_root`` is created if missing.

    Args:
        repo_root: Directory to initialise. Will be created if absent.

    Returns:
        ``(good_sha, culprit_sha, head_sha)`` — the three commit SHAs in
        topological order (parent → child).
    """
    repo_root.mkdir(parents=True, exist_ok=True)

    # Idempotency: nuke any prior state so reruns produce a clean repo.
    dot_git = repo_root / ".git"
    if dot_git.exists():
        import shutil

        shutil.rmtree(dot_git)
    for stale in ("probe.sh", "unrelated.txt"):
        stale_path = repo_root / stale
        if stale_path.exists():
            stale_path.unlink()

    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo_root, check=True)

    def _rev_parse_head() -> str:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
        ).strip()

    _git("init", "-q", "-b", "main")
    # CI has no global git identity — set user.email/name explicitly per
    # feedback_ci_no_global_git_config: do not rely on -c overrides.
    _git("config", "user.email", "staging-bisect-fixture@example.com")
    _git("config", "user.name", "staging-bisect-fixture")
    _git("config", "commit.gpgsign", "false")

    # --- commit A (green) ---------------------------------------------------
    probe = repo_root / "probe.sh"
    probe.write_text("#!/bin/sh\nexit 0\n")
    probe.chmod(0o755)
    _git("add", "probe.sh")
    _git("commit", "-q", "-m", "good: passing baseline")
    good = _rev_parse_head()

    # --- commit B (culprit) -------------------------------------------------
    probe.write_text("#!/bin/sh\nexit 1\n")
    _git("add", "probe.sh")
    _git("commit", "-q", "-m", "culprit: flip probe.sh to exit 1")
    culprit = _rev_parse_head()

    # --- commit C (red HEAD) ------------------------------------------------
    (repo_root / "unrelated.txt").write_text("unrelated follow-up\n")
    _git("add", "unrelated.txt")
    _git("commit", "-q", "-m", "red: unrelated follow-up after culprit")
    head = _rev_parse_head()

    return good, culprit, head


__all__ = ["init_three_commit_repo"]
