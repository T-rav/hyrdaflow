"""Realistic-agent scenarios — drive real AgentRunner via FakeSubprocessRunner.

FakeWorkspace creates worktrees at ``tmp_path / "worktrees" / "issue-{N}"``.
Each test initialises that directory as a real git repository (with an
``origin/main`` ref) so that AgentRunner._count_commits sees actual commits
written by FakeDocker.script_run_with_commits.

FakeSubprocessRunner.run_simple dispatches ``git`` commands to the real host;
other commands (agent CLI, ``make``) go through FakeDocker so tests can script
their outcomes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario


def _init_test_worktree(path: Path, *, branch: str = "agent/issue-1") -> None:
    """Prepare *path* as a git repo suitable for scenario testing.

    Sets up:
    - A bare ``origin.git`` sibling directory used as the remote.
    - An initial commit on ``main`` (so ``origin/main`` is reachable).
    - The working branch *branch* checked out and pushed to origin.

    After this function returns, ``git rev-list --count origin/main..{branch}``
    will return ``"0"`` until a new commit is added on *branch*.
    """
    path.mkdir(parents=True, exist_ok=True)
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


async def test_A0_happy_path_realistic_agent(tmp_path) -> None:
    """A0: Single issue flows through real AgentRunner and gets merged.

    The FakeDocker script commits a file into the worktree so that
    AgentRunner._count_commits sees 1 commit ahead of origin/main, which
    lets _verify_result pass the commit-check gate.  All other quality checks
    (make quality, skills, pre-quality review) use FakeDocker defaults which
    return success with an empty transcript, causing skill parsers to default
    to passed=True.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    # FakeWorkspace creates the dir at tmp_path / "worktrees" / "issue-1".
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    _init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "changed")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert outcome.merged, (
        f"expected merged=True; got outcome={outcome!r}; "
        f"worker_result={outcome.worker_result!r}; "
        f"docker_invocations={len(world.docker.invocations)}"
    )
    assert len(world.docker.invocations) >= 1


async def test_A1_docker_timeout_fails_issue_no_retry(tmp_path) -> None:
    """A1: Timeout on first run — documents production timeout behaviour.

    Production does NOT retry on timeout; the issue fails.  This test asserts
    the observable outcome: at least 1 Docker invocation and a non-merged
    (failed) outcome for the issue, matching real production behaviour.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    _init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.fail_next(kind="timeout")

    result = await world.run_pipeline()

    # Production does not retry after a timeout — issue fails at implement.
    assert len(world.docker.invocations) >= 1
    # Worker result records the failure
    wr = result.issue(1).worker_result
    assert wr is not None
    assert wr.success is False


async def test_A2_oom_fails_issue(tmp_path) -> None:
    """A2: OOM (exit_code=137) causes the agent to fail.

    FakeDocker returns exit_code=137 which stream_claude_process converts
    to a completed transcript.  AgentRunner._count_commits then returns 0
    (no commits were made) causing _verify_result to fail with
    "No commits found on branch".
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    _init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.fail_next(kind="oom")

    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert not outcome.merged
    wr = outcome.worker_result
    assert wr is not None
    assert wr.success is False


async def test_A3_malformed_stream_recovers_to_failure(tmp_path) -> None:
    """A3: Malformed stream (garbage events + exit_code=1) causes failure.

    The garbage event type is ignored by StreamParser; the trailing
    result event signals failure.  No commits are made so _count_commits
    returns 0 and the issue fails.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    _init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.fail_next(kind="malformed_stream")

    result = await world.run_pipeline()

    outcome = result.issue(1)
    assert not outcome.merged
    wr = outcome.worker_result
    assert wr is not None
    assert wr.success is False


async def test_A4_unknown_event_type_ignored_stream_continues(tmp_path) -> None:
    """A4: Unknown event type (auth_retry_required) is ignored by StreamParser.

    Production StreamParser does not recognise ``auth_retry_required`` as a
    known event type, so it is silently skipped.  The subsequent
    ``{"type": "result", "success": True, "exit_code": 0}`` event completes
    the stream normally.  Because the commit hook runs before the events are
    yielded, a real commit exists and the issue can be merged.

    This test verifies that an unknown event type does NOT crash the pipeline
    and that subsequent events are processed correctly.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    _init_test_worktree(worktree_cwd, branch="agent/issue-1")

    world.docker.script_run_with_commits(
        events=[
            {"type": "auth_retry_required"},
            {"type": "result", "success": True, "exit_code": 0},
        ],
        commits=[("x.py", "done")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    outcome = result.issue(1)
    # Minimum assertion: at least one Docker invocation, pipeline did not crash
    assert len(world.docker.invocations) >= 1
    assert outcome.worker_result is not None
    # The unknown event is ignored; the trailing success result is processed
    # and the issue should be merged (same as A0 happy path).
    assert outcome.merged, (
        f"A4: expected merged=True after auth_retry_required + result:success; "
        f"worker_result={outcome.worker_result!r}"
    )


async def test_A5_token_budget_exceeded_halts_implement(tmp_path) -> None:
    """Budget-exceeded event + failure result → issue fails, does not merge.

    Production code does not recognize the ``budget_exceeded`` event type
    specifically; this scenario exercises the more general shape: a stream
    that ends with ``success=False`` (regardless of what preceded it) causes
    ``AgentRunner`` to return a failed ``WorkerResult`` and the pipeline to
    skip merge.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    _init_test_worktree(worktree_cwd)

    world.docker.script_run(
        [
            {"type": "budget_exceeded", "tokens_used": 200_000},
            {"type": "result", "success": False, "exit_code": 1},
        ]
    )

    result = await world.run_pipeline()

    assert not result.issue(1).merged
    wr = result.issue(1).worker_result
    assert wr is not None
    assert wr.success is False


async def test_A6_github_rate_limit_during_pr_creation_surfaces_error(tmp_path) -> None:
    """Rate-limit error is absorbed by run_refilling_pool; observable via no PR.

    `fail_service("github")` sets remaining=0.  The first GitHub call
    (find_existing_issue in the triage duplicate-check) raises RateLimitError.
    `phase_utils.run_refilling_pool` catches non-fatal exceptions and logs
    them as warnings — it does NOT re-raise RateLimitError because it is
    neither AuthenticationError, CreditExhaustedError, nor MemoryError.

    Observable behavior:
    - `run_pipeline` returns normally (no raise).
    - The issue never progresses past triage → no PR is created.
    - The rate-limit counter is consumed (remaining drops to 0).
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    _init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )
    world.fail_service("github")  # arms rate-limit (remaining=0)

    # run_pipeline returns normally — the pool absorbs the RateLimitError.
    result = await world.run_pipeline()

    # No PR was created; issue never merged.
    assert world.github.pr_for_issue(1) is None
    assert not result.issue(1).merged
    # Rate-limit was armed and triggered (remaining stays at 0, not None).
    assert world.github._rate_limit_remaining == 0


async def test_A7_github_secondary_rate_limit_surfaces(tmp_path) -> None:
    """Secondary (abuse-detection) rate-limit is also absorbed by run_refilling_pool.

    `set_rate_limit_mode(remaining=0, secondary=True)` arms the fake with the
    secondary flag set.  Like A6, run_refilling_pool absorbs the error — the
    distinction between primary and secondary rate-limits is carried in the
    RateLimitError instance (secondary=True) but the pool does not propagate
    either variant.

    Observable behavior:
    - `run_pipeline` returns normally (no raise).
    - The issue never progresses → no PR is created.
    - The rate-limit mode is still armed (remaining=0, secondary=True).
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    _init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )
    world.github.set_rate_limit_mode(remaining=0, secondary=True)

    # run_pipeline returns normally — the pool absorbs the RateLimitError.
    result = await world.run_pipeline()

    assert world.github.pr_for_issue(1) is None
    assert not result.issue(1).merged
    # Secondary flag is still set; confirms secondary mode was armed.
    assert world.github._rate_limit_secondary is True
    assert world.github._rate_limit_remaining == 0
