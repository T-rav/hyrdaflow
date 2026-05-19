"""Verifies the session-autouse git-identity fixture in conftest.py.

Without the fixture, `git commit` in a fresh repo without a global `git config`
fails with `Author identity unknown` on GitHub Actions runners. The fixture
exports `GIT_AUTHOR_*` and `GIT_COMMITTER_*` env vars at session scope so
all subprocess `git` invocations inherit a default identity.

See feedback memory `feedback_ci_no_global_git_config.md` (PR #8354) and
`docs/superpowers/specs/2026-05-07-tier2-enforcement-batch-design.md` §5.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_git_commit_succeeds_in_fresh_repo_with_no_config(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("hi")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
    result = subprocess.run(
        ["git", "commit", "-q", "-m", "msg"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_git_identity_env_vars_are_set() -> None:
    assert os.environ.get("GIT_AUTHOR_NAME") == "HydraFlow Test"
    assert os.environ.get("GIT_AUTHOR_EMAIL") == "test@hydraflow.local"
    assert os.environ.get("GIT_COMMITTER_NAME") == "HydraFlow Test"
    assert os.environ.get("GIT_COMMITTER_EMAIL") == "test@hydraflow.local"
