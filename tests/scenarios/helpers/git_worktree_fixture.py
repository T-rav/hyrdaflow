"""Git worktree fixture for scenario tests using ``script_run_with_commits``.

Real production ``_verify_result`` inspects commits in the worktree. Since
the B1 plan keeps git real (GitPort refactor deferred to B2), scenarios
must init a real git repo in ``tmp_path`` before FakeDocker's commit hook
writes into it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def init_test_worktree(
    path: Path,
    *,
    branch: str = "agent/issue-1",
    origin: Path | None = None,
) -> None:
    """Prepare *path* as a git repo suitable for scenario testing.

    Sets up:
    - A bare origin directory used as the remote.  Defaults to
      ``path.parent / "origin.git"`` if *origin* is not supplied.
      Pass an explicit *origin* when multiple worktrees share the same
      parent directory and would otherwise collide on the default name.
    - An initial commit on ``main`` (so ``origin/main`` is reachable).
    - The working branch *branch* checked out and pushed to origin.

    After this function returns, ``git rev-list --count origin/main..{branch}``
    will return ``"0"`` until a new commit is added on *branch*.
    """
    path.mkdir(parents=True, exist_ok=True)
    if origin is None:
        origin = path.parent / "origin.git"
    origin.mkdir(parents=True, exist_ok=True)

    run = lambda *args, cwd=path: subprocess.run(  # noqa: E731
        list(args), cwd=cwd, check=True, capture_output=True
    )

    # Bare origin
    subprocess.run(
        ["git", "init", "--bare", str(origin)],
        check=True,
        capture_output=True,
    )

    # Worktree
    run("git", "init", "-b", "main")
    run("git", "config", "user.email", "test@test")
    run("git", "config", "user.name", "test")
    run("git", "commit", "--allow-empty", "-m", "init")
    run("git", "remote", "add", "origin", str(origin))
    run("git", "push", "-u", "origin", "main")

    # Create and push the feature branch
    run("git", "checkout", "-b", branch)
    run("git", "push", "-u", "origin", branch)
