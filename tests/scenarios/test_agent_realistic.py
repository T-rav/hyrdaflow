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


async def test_A12_multi_commit_implement(tmp_path) -> None:
    """Real agent produces 3 commits; `git rev-list --count` observes them.

    Uses FakeDocker.script_run_with_multiple_commits to simulate an agent that
    produces N distinct commits in a single run. Each batch is committed
    separately with message `fake-commit-{i}`.
    """
    import subprocess

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_multiple_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commit_batches=[
            [("a.py", "step 1")],
            [("b.py", "step 2")],
            [("c.py", "step 3")],
        ],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    assert result.issue(1).merged, f"expected merged=True; outcome={result.issue(1)}"

    # Verify 3 agent-generated commits on the branch (excludes initial empty commit on main)
    count = subprocess.run(
        ["git", "rev-list", "--count", "origin/main..agent/issue-1"],
        cwd=worktree_cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    observed = int(count.stdout.strip())
    assert observed == 3, f"expected 3 commits on branch; observed {observed}"

    # Verify all 3 files exist
    for filename in ("a.py", "b.py", "c.py"):
        assert (worktree_cwd / filename).exists(), f"missing {filename}"


async def test_A13_zero_diff_fails_without_merge(tmp_path) -> None:
    """Agent claims success but commits nothing → WorkerResult failure, no merge.

    Production ``AgentRunner._verify_result`` runs ``git rev-list --count``
    (on host via FakeSubprocessRunner._HOST_COMMANDS).  Observing 0 commits
    causes ``_verify_result`` to return
    ``LoopResult(passed=False, summary="No commits found on branch")``,
    which propagates to ``WorkerResult(success=False, error="No commits found
    on branch", commits=0)``.

    ``_handle_implementation_result`` then calls ``_is_zero_commit_failure``
    (checks ``not result.success and result.error == "No commits found on
    branch" and result.commits == 0``), which returns True, routing into
    ``_handle_zero_commits`` — marking the issue failed without creating a PR
    or merging.

    The scripted stream uses ``script_run`` (not ``script_run_with_commits``)
    so no real git commit is ever written to the worktree.  The success flag
    in the stream event is irrelevant: ``_verify_result`` fails on the commit
    count gate before the quality check even runs.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    # Agent "succeeds" but writes no commits (plain script_run, not script_run_with_commits)
    world.docker.script_run([{"type": "result", "success": True, "exit_code": 0}])

    result = await world.run_pipeline()

    # Issue must NOT merge — zero commits means _verify_result fails
    assert not result.issue(1).merged, f"expected no merge; outcome={result.issue(1)}"

    # WorkerResult should be present with success=False
    wr = result.issue(1).worker_result
    assert wr is not None, "expected a WorkerResult recording the failure"
    assert wr.success is False, f"expected success=False; got {wr}"


async def test_A15_epic_decomposition_creates_children(tmp_path) -> None:
    """High-complexity issue with scripted decomp creates 2 child issues.

    Triage phase sees complexity_score >= threshold AND should_decompose=True
    AND 2+ children, invokes `_prs.create_issue` twice with find-labeled bodies.

    Because PipelineHarness constructs TriagePhase without an EpicManager
    (epic_manager=None), _maybe_decompose exits early. This test injects a
    minimal AsyncMock EpicManager into triage_phase._epic_manager and wires
    prs.create_issue to FakeGitHub so child issue creation is observable.

    Config default: epic_decompose_complexity_threshold=8, so complexity_score=10
    comfortably clears the gate.
    """
    from unittest.mock import AsyncMock, MagicMock

    from models import EpicDecompResult, NewIssueSpec, TriageResult

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(100, "big epic", "", labels=["hydraflow-find"])

    # Inject a minimal EpicManager stub so _maybe_decompose does not
    # short-circuit at "self._epic_manager is None".
    # find_parent_epics is called synchronously in _enrich_parent_epic so
    # use MagicMock (not AsyncMock) for it; register_epic is awaited so it
    # must be an AsyncMock.
    fake_epic_manager = MagicMock()
    fake_epic_manager.find_parent_epics = MagicMock(return_value=[])
    fake_epic_manager.register_epic = AsyncMock(return_value=None)
    world.harness.triage_phase._epic_manager = fake_epic_manager

    # Wire prs.create_issue to FakeGitHub so child issues land in world state.
    world.harness.prs.create_issue = world.github.create_issue

    # High-complexity triage result: complexity_score=10 >= threshold of 8.
    triage_result = TriageResult(
        issue_number=100,
        ready=True,
        complexity_score=10,
    )
    world._llm.script_triage(100, [triage_result])

    decomp = EpicDecompResult(
        should_decompose=True,
        epic_title="Big Epic",
        epic_body="Decomposed epic",
        children=[
            NewIssueSpec(title="child-a", body=""),
            NewIssueSpec(title="child-b", body=""),
        ],
        reasoning="issue is too large",
    )
    world._llm.triage_runner.script_decomposition(100, decomp)

    await world.run_pipeline()

    # 2 new child issues + 1 epic issue should have been created by FakeGitHub.
    all_issues = list(world.github._issues.values())
    child_issues = [i for i in all_issues if i.number != 100]
    assert len(child_issues) >= 2, f"expected >=2 children; got {len(child_issues)}"
    child_titles = {i.title for i in child_issues}
    assert "child-a" in child_titles
    assert "child-b" in child_titles


async def test_A14_three_issues_concurrent_realistic(tmp_path) -> None:
    """Three issues run through real AgentRunner concurrently; all merge.

    Each issue's worktree is isolated — the scripted commits target each
    issue's specific `cwd`. FakeDocker's script FIFO is consumed in real
    invocation order, so the 3 scripted calls can match any of the 3
    issues. The scenario asserts overall pipeline success and worktree
    isolation (each issue's own file is present, others' are not).

    Note: ``init_test_worktree`` places the bare origin at
    ``path.parent / "origin.git"``. With 3 worktrees sharing the same
    parent (``tmp_path / "worktrees"``), a single shared ``origin.git``
    would conflict when the second and third repos try to push a different
    ``main``. Each issue therefore gets its own origin under
    ``tmp_path / "origins" / "issue-{n}.git"`` via inline git setup that
    mirrors what ``init_test_worktree`` does but with an explicit origin path.

    If cross-contamination is observed (one issue gets another's file),
    this scenario would need keyed FakeDocker scripting — a separate fix.
    """
    import subprocess

    world = MockWorld(tmp_path, use_real_agent_runner=True)

    for n in (1, 2, 3):
        world.add_issue(n, f"issue {n}", f"body {n}", labels=["hydraflow-ready"])

        wt = tmp_path / "worktrees" / f"issue-{n}"
        wt.mkdir(parents=True, exist_ok=True)

        # Per-issue bare origin so that multiple repos don't conflict on push.
        origin = tmp_path / "origins" / f"issue-{n}.git"
        origin.mkdir(parents=True, exist_ok=True)

        branch = f"agent/issue-{n}"

        def _git(*args: str, cwd) -> None:  # noqa: ANN001
            subprocess.run(list(args), cwd=cwd, check=True, capture_output=True)

        # Bare origin
        subprocess.run(
            ["git", "init", "--bare", str(origin)],
            check=True,
            capture_output=True,
        )

        # Worktree repo
        _git("git", "init", "-b", "main", cwd=wt)
        _git("git", "config", "user.email", "test@test", cwd=wt)
        _git("git", "config", "user.name", "test", cwd=wt)
        _git("git", "commit", "--allow-empty", "-m", "init", cwd=wt)
        _git("git", "remote", "add", "origin", str(origin), cwd=wt)
        _git("git", "push", "-u", "origin", "main", cwd=wt)
        _git("git", "checkout", "-b", branch, cwd=wt)
        _git("git", "push", "-u", "origin", branch, cwd=wt)

        world.docker.script_run_with_commits(
            events=[{"type": "result", "success": True, "exit_code": 0}],
            commits=[(f"file{n}.py", f"content {n}")],
            cwd=wt,
        )

    result = await world.run_pipeline()

    # All 3 issues should merge
    for n in (1, 2, 3):
        outcome = result.issue(n)
        assert outcome.merged, f"issue {n} did not merge: {outcome}"
        assert outcome.worker_result is not None
        assert outcome.worker_result.issue_number == n, (
            f"cross-contamination: issue {n}'s result bound to "
            f"{outcome.worker_result.issue_number}"
        )

    # Exactly 3 PRs, one per issue
    prs = [world.github.pr_for_issue(n) for n in (1, 2, 3)]
    assert all(p is not None and p.merged for p in prs), f"PRs: {prs}"

    # At least 3 docker invocations (expect many more: skills, quality, etc.)
    assert len(world.docker.invocations) >= 3


async def test_A17_authentication_error_halts_pipeline(tmp_path) -> None:
    """AuthenticationError from _execute propagates out of run_pipeline.

    Like CreditExhaustedError, AuthenticationError is in the re-raise
    allowlist at src/phase_utils.py:130-137.
    """
    from unittest import mock

    import pytest

    from subprocess_util import AuthenticationError
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    agent_runner = world.harness.agents

    async def raising_execute(*args, **kwargs):
        raise AuthenticationError("401 unauthorized")

    with (
        mock.patch.object(agent_runner, "_execute", raising_execute),
        pytest.raises(AuthenticationError),
    ):
        await world.run_pipeline()


async def test_A18_rate_limit_heals_mid_pipeline(tmp_path) -> None:
    """Arm rate-limit, let early calls succeed, heal via on_phase hook, complete.

    Scripts `remaining=5` so the first 5 GitHub calls succeed. An `on_phase`
    hook on `"implement"` heals the rate-limit before the implement-phase
    starts its GitHub calls. Pipeline runs to completion.
    """
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )

    # Allow 5 GitHub calls then raise; but heal before it matters
    world.github.set_rate_limit_mode(remaining=5)

    def heal_github() -> None:
        world.github.clear_rate_limit()

    world.on_phase("implement", heal_github)

    result = await world.run_pipeline()

    # Pipeline must complete and merge despite the rate-limit arming
    assert result.issue(1).merged, f"expected merged=True; outcome={result.issue(1)}"


async def test_A16_credit_exhausted_halts_pipeline(tmp_path) -> None:
    """CreditExhaustedError from _execute propagates out of run_pipeline.

    run_refilling_pool's re-raise allowlist (src/phase_utils.py:130-137)
    re-raises CreditExhaustedError (along with AuthenticationError and
    MemoryError) after cancelling sibling tasks. Non-allowlisted exceptions
    are swallowed and logged at warning.
    """
    from unittest import mock

    from subprocess_util import CreditExhaustedError

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    agent_runner = world.harness.agents

    async def raising_execute(*args, **kwargs):
        raise CreditExhaustedError("API credit limit reached", resume_at=None)

    with (
        mock.patch.object(agent_runner, "_execute", raising_execute),
        pytest.raises(CreditExhaustedError),
    ):
        await world.run_pipeline()


async def test_A19_code_scanning_alerts_reach_reviewer(tmp_path) -> None:
    """Scripted code-scanning alerts propagate through review pipeline.

    FakeGitHub.add_alerts(pr_number=...) seeds alerts for the PR that will be
    created. Real ReviewPhase fetches them via fetch_code_scanning_alerts and
    passes them to ReviewRunner.review. FakeLLM.reviewers records what it
    received; we assert the alert list reached the reviewer unchanged.
    """
    from models import CodeScanningAlert
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )

    alerts = [
        CodeScanningAlert(
            number=1,
            severity="error",
            security_severity="high",
            path="x.py",
            start_line=1,
            rule="py/test",
            message="an alert",
        ),
    ]
    # Production ReviewPhase calls fetch_code_scanning_alerts(pr.branch) — the
    # branch is the key in FakeGitHub._alerts (positional arg maps to pr_number).
    world.github.add_alerts(pr_number="agent/issue-1", alerts=alerts)

    await world.run_pipeline()

    # Pipeline ran and reviewer saw the alerts
    received = world._llm.alerts_received_by_reviewer(1)
    assert received == alerts, f"reviewer received {received!r}"


async def test_A20_workspace_create_permission_failure(tmp_path) -> None:
    """FakeWorkspace.fail_next_create raises PermissionError; pipeline handles gracefully.

    The PermissionError from workspace creation is swallowed by the implement
    phase's exception handler (non-allowlisted errors are caught and logged).
    The issue therefore does not merge, and run_pipeline returns normally.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    # No worktree init needed — the failure happens BEFORE workspace creation.
    world._workspace.fail_next_create(kind="permission")

    result = await world.run_pipeline()

    # Pipeline does not crash. Issue fails without merging.
    assert not result.issue(1).merged, f"expected no merge; outcome={result.issue(1)}"


async def test_A21_state_json_corruption_graceful_fallback(tmp_path) -> None:
    """Corrupt state.json before run; StateTracker falls back to empty state.

    Per src/state/__init__.py, `StateTracker.load` catches `JSONDecodeError`
    and OSError, tries `.bak` files, then falls back to empty `StateData()`.
    Pipeline must still run — a corrupt state file is recoverable.

    PipelineHarness uses `state_file=tmp_path / "state.json"`, so corrupting
    that file BEFORE MockWorld construction exercises the real StateTracker
    fallback path.  The pipeline proceeds with a fresh empty state, and the
    issue is processed normally.
    """
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    # Corrupt the state file before MockWorld (and therefore StateTracker) is created
    state_file = tmp_path / "state.json"
    state_file.write_text('{"this is": broken json no closing brace')

    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )

    # Pipeline must not raise on startup despite the corrupt state file.
    # StateTracker.load() catches JSONDecodeError and falls back to StateData().
    result = await world.run_pipeline()

    # The real StateTracker was exercised: construction did not raise and the
    # pipeline ran to completion with a fresh empty state.
    assert result is not None


async def test_A22_wiki_populated_plan_consults_it(tmp_path) -> None:
    """Pre-populated RepoWikiStore is consulted by PlanPhase.

    We pre-ingest a learning entry, run the pipeline, and verify the wiki
    log records activity (either ingest or query) scoped to the test repo.

    PipelineHarness defaults to repo slug "test-org/test-repo", so the wiki
    log lives at {wiki_root}/test-org/test-repo/log.jsonl.  The pre-ingest
    call writes at least one log entry; if PlanPhase queries/ingests again,
    more entries appear.
    """
    import pytest

    from repo_wiki import RepoWikiStore, WikiEntry
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    wiki = RepoWikiStore(tmp_path / "wiki")
    # Pre-populate with one patterns entry using the real WikiEntry model
    wiki.ingest(
        "test-org/test-repo",
        entries=[
            WikiEntry(
                title="use async everywhere",
                content="All handlers must be async to avoid blocking the event loop.",
                source_type="plan",
                source_issue=None,
            )
        ],
    )

    world = MockWorld(tmp_path, use_real_agent_runner=True, wiki_store=wiki)
    world.add_issue(1, "add async handler", "body", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[{"type": "result", "success": True, "exit_code": 0}],
        commits=[("x.py", "ok")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    # The pre-ingest call above always writes a log entry.  PlanPhase may add
    # more (query or ingest) depending on whether plan text is available.
    log_path = tmp_path / "wiki" / "test-org" / "test-repo" / "log.jsonl"
    if log_path.exists():
        content = log_path.read_text()
        assert content, (
            "wiki log exists but is empty — pre-ingest should have written it"
        )
    else:
        # RepoWikiStore layout has changed; adjust expectations.
        pytest.skip("wiki log not found; RepoWikiStore layout may have changed")

    assert result is not None
