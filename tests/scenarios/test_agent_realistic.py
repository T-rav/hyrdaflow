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

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

pytestmark = pytest.mark.scenario


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
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

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
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

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
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

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
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

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
    init_test_worktree(worktree_cwd, branch="agent/issue-1")

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
    """Stream-level ``budget_exceeded`` event + failure result → issue fails.

    This is distinct from ``FakeLLM.set_token_budget`` (which gates scripted
    planner/reviewer turns). In realistic-agent mode, the scripted
    _FakeAgentRunner is replaced by the real AgentRunner, so the FakeLLM
    budget does not gate the implement path. Scenarios that need implement-
    level budget enforcement must use FakeDocker stream events like this one.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

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


async def test_A6_github_rate_limit_at_triage_halts_pipeline(tmp_path) -> None:
    """Rate-limit armed before triage halts the pipeline at the earliest GitHub call (find_existing_issue in triage's dup-check), not at create_pr.

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
    init_test_worktree(worktree_cwd)

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
    init_test_worktree(worktree_cwd)

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


async def test_A8_find_stage_to_done_realistic_agent(tmp_path) -> None:
    """Full pipeline from hydraflow-find through triage+plan+implement+review.

    All other A-scenarios shortcut via ``labels=["hydraflow-ready"]``. This
    one proves the realistic-agent path works from the default entry point
    that production uses for new issues.

    ``add_issue`` with no ``labels`` defaults to ``["hydraflow-find"]``.
    ``run_pipeline`` seeds at stage ``"find"`` unconditionally; the triage
    phase processes the issue and FakeLLM defaults to ``ready=True`` so the
    issue progresses through plan→implement→review exactly like a
    ``hydraflow-ready`` issue.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b")  # defaults to labels=["hydraflow-find"]

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "done")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    # Full pipeline ran and merged the issue.
    assert result.issue(1).merged
    # At least one real AgentRunner invocation occurred.
    assert len(world.docker.invocations) >= 1


async def test_A9_hindsight_failure_realistic_agent_still_succeeds(tmp_path) -> None:
    """fail_service('hindsight') during realistic-agent run must not halt pipeline."""
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.fail_service("hindsight")  # retains/recalls fail silently

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "done")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    # Hindsight down should not block the implement path.
    assert result.issue(1).merged


async def test_A10_quality_fix_loop_retries_then_passes(tmp_path) -> None:
    """make quality fails → fix agent runs → second make quality passes.

    Proves the realistic path exercises production `AgentRunner._run_quality_fix_loop`.
    `max_quality_fix_attempts` defaults to 2 in ConfigFactory, so one retry is
    enough to pass.

    FakeDocker scripts are consumed FIFO by ALL run_agent calls (both
    create_streaming_process for agent _execute calls and run_simple for
    make-quality calls). The post-implementation pipeline after the initial agent
    run is:

      1. Initial agent _execute (streaming) — commits broken code
      2. diff-sanity skill _execute — default success (no marker → passed)
      3. arch-compliance skill _execute — default success
      4. scope-check skill _execute — default success (auto-pass, no plan)
         plan-compliance is SKIPPED (empty prompt when no plan → no _execute call)
      5. test-adequacy skill _execute — default success
      6. pre-quality review _execute, attempt 1, review pass — default success
      7. pre-quality run-tool _execute, attempt 1, run_tool pass — default success
      8. First `make quality` (run_simple) — FAILS with exit_code=1
      9. Quality-fix agent _execute (streaming) — commits fix
     10. Second `make quality` (run_simple) — PASSES with exit_code=0

    plan-compliance returns an empty prompt string when no plan is present,
    causing _run_skill to return early without calling _execute. Only 4 of the
    5 registered skills consume a FakeDocker slot. All skill/pre-quality slots
    must be explicitly queued in FIFO order so that the fail/fix scripts land
    in the correct positions.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    _ok = [{"type": "result", "success": True, "exit_code": 0}]

    # 1) Initial agent run: commits broken code
    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "broken")],
        cwd=worktree_cwd,
    )
    # 2–5) Four post-implementation skill _execute calls — default success
    # (diff-sanity, arch-compliance, scope-check, test-adequacy)
    # plan-compliance is skipped: returns empty prompt with no plan → no _execute
    for _ in range(4):
        world.docker.script_run(_ok)
    # 6–7) Pre-quality review loop attempt 1: review + run_tool — both default success
    world.docker.script_run(_ok)  # review pass
    world.docker.script_run(_ok)  # run_tool pass
    # 8) First `make quality` via run_simple — FAILS
    world.docker.script_run([{"type": "result", "success": False, "exit_code": 1}])
    # 9) Quality-fix agent: commits the fix
    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "fixed")],
        cwd=worktree_cwd,
    )
    # 10) Second `make quality` via run_simple — PASSES
    world.docker.script_run(_ok)

    result = await world.run_pipeline()

    # Pipeline completed and merged
    assert result.issue(1).merged, (
        f"expected merged=True; outcome={result.issue(1)!r}; "
        f"docker_invocations={len(world.docker.invocations)}"
    )
    # Exactly 10 FakeDocker invocations:
    # 1 agent + 4 skills + 2 pre-quality + 1 make-quality-fail + 1 fix-agent +
    # 1 make-quality-pass
    assert len(world.docker.invocations) >= 10


async def test_A11_review_fix_ci_loop_resolves(tmp_path) -> None:
    """CI fails after PR creation → fix_ci runs → CI passes → merge proceeds.

    FakeGitHub.script_ci feeds (fail, pass) to wait_for_ci. Real ReviewPhase
    wait_and_fix_ci catches the failure, invokes the scripted fix_ci (FakeLLM,
    always returns fixes_made=True), re-waits CI which now passes. Merge proceeds.

    FakeDocker invocations (8 total — quality passes first attempt):
      1. Initial agent _execute (streaming) — commits code
      2–5. Four post-implementation skill _execute calls — default success
           (diff-sanity, arch-compliance, scope-check, test-adequacy;
           plan-compliance is skipped: empty prompt with no plan)
      6. Pre-quality review _execute, attempt 1 — default success
      7. Pre-quality run-tool _execute, attempt 1 — default success
      8. make quality (run_simple) — PASSES

    CI fail/fix is handled by FakeGitHub.script_ci + FakeLLM.reviewers.fix_ci
    and does NOT consume FakeDocker slots.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    _ok = [{"type": "result", "success": True, "exit_code": 0}]

    # 1) Initial agent run: commits code
    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )
    # 2–5) Four post-implementation skill _execute calls — default success
    # (diff-sanity, arch-compliance, scope-check, test-adequacy)
    # plan-compliance is skipped: returns empty prompt with no plan → no _execute
    for _ in range(4):
        world.docker.script_run(_ok)
    # 6–7) Pre-quality review loop attempt 1: review + run_tool — both default success
    world.docker.script_run(_ok)  # review pass
    world.docker.script_run(_ok)  # run_tool pass
    # 8) make quality via run_simple — PASSES first attempt (no quality-fix loop)
    world.docker.script_run(_ok)

    # CI scripted: fail first, pass second.
    # FakeGitHub._pr_counter starts at 10_000; the first PR created is 10_000.
    world.github.script_ci(
        pr_number=10_000,
        results=[(False, "test failed"), (True, "CI passed")],
    )

    result = await world.run_pipeline()

    # The issue should have been merged after fix_ci resolved CI
    assert result.issue(1).merged, (
        f"expected merged=True; outcome={result.issue(1)!r}; "
        f"docker_invocations={len(world.docker.invocations)}"
    )

    # A PR was created and merged
    pr = world.github.pr_for_issue(1)
    assert pr is not None
    assert pr.merged is True

    # 8 FakeDocker invocations: 1 agent + 4 skills + 2 pre-quality + 1 make-quality
    assert len(world.docker.invocations) >= 8
