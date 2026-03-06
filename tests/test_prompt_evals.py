"""Prompt evals for planner/implementer/reviewer/triage.

These tests act as a baseline harness for prompt quality and size:
- normal cases (expected structure present)
- error/oversize cases (payload compaction active)
- edge cases (empty/minimal/malformed inputs handled safely)
"""

from __future__ import annotations

from pathlib import Path

from agent import AgentRunner
from events import EventBus
from planner import PlannerRunner
from reviewer import ReviewRunner
from tests.conftest import PRInfoFactory, TaskFactory
from tests.helpers import ConfigFactory
from triage import TriageRunner


def _cfg(tmp_path: Path, **overrides: object):
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        worktree_base=tmp_path / "wt",
        state_file=tmp_path / "state.json",
        **overrides,
    )


def test_planner_prompt_eval_normal(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, max_issue_body_chars=4000)
    runner = PlannerRunner(cfg, EventBus())
    task = TaskFactory.create(
        title="Fix login race",
        body="Investigate auth race condition and patch session locking.",
        comments=["Please include regression tests."],
        tags=["bug"],
    )

    prompt = runner._build_prompt(task, scale="full")

    assert "PLAN_START" in prompt
    assert "PLAN_END" in prompt
    assert "SUMMARY:" in prompt
    assert "REQUIRED SCHEMA" in prompt
    assert "ALREADY_SATISFIED_START" in prompt


def test_planner_prompt_eval_error_oversized_input(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, max_issue_body_chars=4000)
    runner = PlannerRunner(cfg, EventBus())
    task = TaskFactory.create(
        title="Large issue body",
        body="X" * 30000,
        comments=["C" * 8000 for _ in range(10)],
    )

    prompt = runner._build_prompt(task, scale="full")

    assert "…(truncated)" in prompt
    assert "more comments omitted" in prompt
    assert len(prompt) < 30000


def test_planner_prompt_eval_edge_empty_inputs(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    runner = PlannerRunner(cfg, EventBus())
    task = TaskFactory.create(body="", comments=[], tags=[])

    prompt = runner._build_prompt(task, scale="lite")

    assert "LITE" in prompt
    assert "PLAN_START" in prompt
    assert "Discussion" not in prompt


def test_implementer_prompt_eval_normal(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, max_issue_body_chars=4000)
    runner = AgentRunner(cfg, EventBus())
    task = TaskFactory.create(
        body="Implement endpoint and include tests.",
        comments=["## Implementation Plan\n\n1. Add handler\n2. Add tests\n"],
    )

    prompt = runner._build_prompt(task)

    assert "## Implementation Plan" in prompt
    assert "Follow this plan closely" in prompt
    assert "## Instructions" in prompt
    assert "make quality" in prompt


def test_implementer_prompt_eval_error_oversized_sections(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, max_issue_body_chars=4000)
    runner = AgentRunner(cfg, EventBus())
    long_plan = "## Implementation Plan\n\n" + ("step\n" * 8000)
    task = TaskFactory.create(
        body="B" * 20000,
        comments=[long_plan] + [f"comment {i}" for i in range(20)],
    )
    review_feedback = "feedback\n" * 5000

    prompt = runner._build_prompt(task, review_feedback=review_feedback)

    assert "summarized from" in prompt
    assert "more comments omitted" in prompt
    assert len(prompt) < 35000


def test_implementer_prompt_eval_edge_no_plan(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    runner = AgentRunner(cfg, EventBus())
    task = TaskFactory.create(body="Short body", comments=[])

    prompt = runner._build_prompt(task)

    assert "Follow this plan closely" not in prompt
    assert "## Rules" in prompt


def test_reviewer_prompt_eval_normal(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, max_review_diff_chars=7000)
    runner = ReviewRunner(cfg, EventBus())
    issue = TaskFactory.create(body="Fix API response shape.")
    pr = PRInfoFactory.create()
    diff = "diff --git a/foo.py b/foo.py\n+added line\n"

    prompt = runner._build_review_prompt(pr, issue, diff)

    assert "## PR Diff" in prompt
    assert diff in prompt
    assert "VERDICT: APPROVE" in prompt


def test_reviewer_prompt_eval_error_large_payload(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, max_issue_body_chars=4000, max_review_diff_chars=7000)
    runner = ReviewRunner(cfg, EventBus())
    issue = TaskFactory.create(body="I" * 25000)
    pr = PRInfoFactory.create()
    diff = "diff --git a/a.py b/a.py\n" + ("+x\n-y\n" * 12000)

    prompt = runner._build_review_prompt(pr, issue, diff)

    assert "Issue body summarized for token efficiency" in prompt
    assert "### Diff Summary" in prompt
    assert "### Diff Excerpts" in prompt
    assert len(prompt) < 25000


def test_reviewer_prompt_eval_edge_malformed_diff(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, max_review_diff_chars=5000)
    runner = ReviewRunner(cfg, EventBus())
    issue = TaskFactory.create(body="Check malformed diff handling.")
    pr = PRInfoFactory.create()
    diff = "x" * 10000  # no diff headers

    prompt = runner._build_review_prompt(pr, issue, diff)

    assert "### Diff Summary" in prompt
    assert "(could not detect files)" in prompt
    assert "Diff truncated" in prompt


def test_triage_prompt_eval_normal(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    runner = TriageRunner(cfg, EventBus())
    task = TaskFactory.create(body="Need to fix login bug with repro steps.")

    prompt = runner._build_prompt(task, max_body=2000)

    assert '"ready": true' in prompt
    assert "Evaluation Criteria" in prompt


def test_triage_prompt_eval_error_oversized_issue_body(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, max_issue_body_chars=4000)
    runner = TriageRunner(cfg, EventBus())
    task = TaskFactory.create(body="T" * 12000)

    prompt = runner._build_prompt(task, max_body=1500)

    assert "T" * 1500 in prompt
    assert "T" * 1600 not in prompt


def test_triage_prompt_eval_edge_empty_body(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    runner = TriageRunner(cfg, EventBus())
    task = TaskFactory.create(body="")

    prompt = runner._build_prompt(task, max_body=1200)

    assert f"## Issue #{task.id}" in prompt
    assert "**Body:**" in prompt


def test_planner_retry_prompt_eval_normal(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    runner = PlannerRunner(cfg, EventBus())
    task = TaskFactory.create(title="Retry planner prompt")
    failed_plan = "## Files to Modify\n- a.py"
    errors = ["Missing required section: ## Testing Strategy"]

    prompt, _stats = runner._build_retry_prompt(task, failed_plan, errors, scale="full")

    assert "PLAN_START" in prompt
    assert "PLAN_END" in prompt
    assert "SUMMARY:" in prompt
    assert "Missing required section" in prompt


def test_planner_prompt_eval_edge_full_vs_lite_schema(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    runner = PlannerRunner(cfg, EventBus())
    task = TaskFactory.create(tags=["bug"])

    full_prompt = runner._build_prompt(task, scale="full")
    lite_prompt = runner._build_prompt(task, scale="lite")

    assert "REQUIRED SCHEMA" in full_prompt
    assert "LITE SCHEMA" in lite_prompt
    assert "## Acceptance Criteria" in full_prompt
    assert "## Acceptance Criteria" not in lite_prompt


def test_implementer_quality_fix_prompt_eval_error_truncation(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, error_output_max_chars=1200)
    runner = AgentRunner(cfg, EventBus())
    task = TaskFactory.create()
    long_error = "E" * 5000

    prompt = runner._build_quality_fix_prompt(task, long_error, attempt=2)

    assert "Fix Attempt 2" in prompt
    assert "E" * 1200 in prompt
    assert "E" * 1500 not in prompt


def test_implementer_pre_quality_review_prompt_eval_contract(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    runner = AgentRunner(cfg, EventBus())
    task = TaskFactory.create(title="Contract check")

    prompt = runner._build_pre_quality_review_prompt(task, attempt=1)

    assert "PRE_QUALITY_REVIEW_RESULT: OK" in prompt
    assert "PRE_QUALITY_REVIEW_RESULT: RETRY" in prompt
    assert "SUMMARY:" in prompt


def test_implementer_run_tool_prompt_eval_contract(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, test_command="pytest -q")
    runner = AgentRunner(cfg, EventBus())
    task = TaskFactory.create(title="Run-tool contract")

    prompt = runner._build_pre_quality_run_tool_prompt(task, attempt=3)

    assert "RUN_TOOL_RESULT: OK" in prompt
    assert "RUN_TOOL_RESULT: RETRY" in prompt
    assert "`pytest -q`" in prompt


def test_reviewer_ci_fix_prompt_eval_normal(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, test_command="pytest -q")
    runner = ReviewRunner(cfg, EventBus())
    issue = TaskFactory.create(title="CI fix")
    pr = PRInfoFactory.create()

    prompt, _stats = runner._build_ci_fix_prompt(
        pr, issue, "Typecheck failed on core/service.py", attempt=2
    )

    assert f"PR #{pr.number}" in prompt
    assert "Fix Attempt 2" in prompt
    assert "`pytest -q`" in prompt
    assert "VERDICT: APPROVE" in prompt


def test_reviewer_ci_fix_prompt_eval_edge_with_logs(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    runner = ReviewRunner(cfg, EventBus())
    issue = TaskFactory.create()
    pr = PRInfoFactory.create()
    ci_logs = "Traceback:\n" + ("line\n" * 100)

    prompt, _stats = runner._build_ci_fix_prompt(
        pr, issue, "Integration tests failed", attempt=1, ci_logs=ci_logs
    )

    assert "## Full CI Failure Logs" in prompt
    assert "Traceback:" in prompt
    assert "Integration tests failed" in prompt


def test_triage_prompt_eval_edge_json_contract_markers(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    runner = TriageRunner(cfg, EventBus())
    task = TaskFactory.create()

    prompt = runner._build_prompt(task, max_body=1000)

    assert '"ready": true' in prompt
    assert '"enrichment"' in prompt
    assert '"ready": false' in prompt
    assert '"reasons"' in prompt
