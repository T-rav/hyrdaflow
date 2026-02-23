"""CLI entry point for HydraFlow."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import shutil
import signal
import sys
from pathlib import Path
from typing import Any

from config import HydraFlowConfig, load_config_file
from log import setup_logging
from orchestrator import HydraFlowOrchestrator


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="hydraflow",
        description="HydraFlow — Intent in. Software out.",
    )

    parser.add_argument(
        "--ready-label",
        default=None,
        help="GitHub issue labels to filter by, comma-separated (default: hydraflow-ready)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Number of issues per batch (default: 15)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Max concurrent implementation agents (default: 3)",
    )
    parser.add_argument(
        "--max-planners",
        type=int,
        default=None,
        help="Max concurrent planning agents (default: 1)",
    )
    parser.add_argument(
        "--max-reviewers",
        type=int,
        default=None,
        help="Max concurrent review agents (default: 5)",
    )
    parser.add_argument(
        "--max-hitl-workers",
        type=int,
        default=None,
        help="Max concurrent HITL correction agents (default: 1)",
    )
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=None,
        help="USD budget cap per implementation agent (0 = unlimited, default: 0)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model for implementation agents (default: opus)",
    )
    parser.add_argument(
        "--implementation-tool",
        default=None,
        choices=["claude", "codex"],
        help="CLI backend for implementation agents (default: claude)",
    )
    parser.add_argument(
        "--review-model",
        default=None,
        help="Model for review agents (default: sonnet)",
    )
    parser.add_argument(
        "--review-tool",
        default=None,
        choices=["claude", "codex"],
        help="CLI backend for review agents (default: claude)",
    )
    parser.add_argument(
        "--review-budget-usd",
        type=float,
        default=None,
        help="USD budget cap per review agent (0 = unlimited, default: 0)",
    )
    parser.add_argument(
        "--ci-check-timeout",
        type=int,
        default=None,
        help="Seconds to wait for CI checks (default: 600)",
    )
    parser.add_argument(
        "--ci-poll-interval",
        type=int,
        default=None,
        help="Seconds between CI status polls (default: 30)",
    )
    parser.add_argument(
        "--max-ci-fix-attempts",
        type=int,
        default=None,
        help="Max CI fix-and-retry cycles; 0 disables CI wait (default: 2)",
    )
    parser.add_argument(
        "--max-pre-quality-review-attempts",
        type=int,
        default=None,
        help="Max pre-quality review/correction passes before make quality (default: 1)",
    )
    parser.add_argument(
        "--max-review-fix-attempts",
        type=int,
        default=None,
        help="Max review fix-and-retry cycles before HITL escalation (default: 2)",
    )
    parser.add_argument(
        "--min-review-findings",
        type=int,
        default=None,
        help="Minimum review findings threshold for adversarial review (default: 3)",
    )
    parser.add_argument(
        "--max-merge-conflict-fix-attempts",
        type=int,
        default=None,
        help="Max merge conflict resolution retry cycles (default: 3)",
    )
    parser.add_argument(
        "--max-issue-attempts",
        type=int,
        default=None,
        help="Max total implementation attempts per issue (default: 3)",
    )
    parser.add_argument(
        "--review-label",
        default=None,
        help="Labels for issues/PRs under review, comma-separated (default: hydraflow-review)",
    )
    parser.add_argument(
        "--hitl-label",
        default=None,
        help="Labels for human-in-the-loop escalation, comma-separated (default: hydraflow-hitl)",
    )
    parser.add_argument(
        "--hitl-active-label",
        default=None,
        help="Labels for HITL items being actively processed, comma-separated (default: hydraflow-hitl-active)",
    )
    parser.add_argument(
        "--fixed-label",
        default=None,
        help="Labels applied after PR is merged, comma-separated (default: hydraflow-fixed)",
    )
    parser.add_argument(
        "--find-label",
        default=None,
        help="Labels for new issues to discover, comma-separated (default: hydraflow-find)",
    )
    parser.add_argument(
        "--planner-label",
        default=None,
        help="Labels for issues needing plans, comma-separated (default: hydraflow-plan)",
    )
    parser.add_argument(
        "--improve-label",
        default=None,
        help="Labels for self-improvement proposals, comma-separated (default: hydraflow-improve)",
    )
    parser.add_argument(
        "--memory-label",
        default=None,
        help="Labels for accepted agent learnings, comma-separated (default: hydraflow-memory)",
    )
    parser.add_argument(
        "--memory-sync-interval",
        type=int,
        default=None,
        help="Seconds between memory sync polls (default: 3600)",
    )
    parser.add_argument(
        "--metrics-label",
        default=None,
        help="Labels for the metrics persistence issue, comma-separated (default: hydraflow-metrics)",
    )
    parser.add_argument(
        "--epic-label",
        default=None,
        help="Labels for epic tracking issues, comma-separated (default: hydraflow-epic)",
    )
    parser.add_argument(
        "--metrics-sync-interval",
        type=int,
        default=None,
        help="Seconds between metrics snapshot syncs (default: 7200)",
    )
    parser.add_argument(
        "--planner-model",
        default=None,
        help="Model for planning agents (default: opus)",
    )
    parser.add_argument(
        "--planner-tool",
        default=None,
        choices=["claude", "codex"],
        help="CLI backend for planning agents (default: claude)",
    )
    parser.add_argument(
        "--triage-tool",
        default=None,
        choices=["claude", "codex"],
        help="CLI backend for triage agents (default: claude)",
    )
    parser.add_argument(
        "--planner-budget-usd",
        type=float,
        default=None,
        help="USD budget cap per planning agent (0 = unlimited, default: 0)",
    )
    parser.add_argument(
        "--min-plan-words",
        type=int,
        default=None,
        help="Minimum word count for a valid plan (default: 200)",
    )
    parser.add_argument(
        "--lite-plan-labels",
        default=None,
        help="Comma-separated labels that trigger lite plans (default: bug,typo,docs)",
    )
    parser.add_argument(
        "--test-command",
        default=None,
        help="Test command used in agent prompts (default: make test)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo owner/name (auto-detected from git remote if omitted)",
    )
    parser.add_argument(
        "--main-branch",
        default=None,
        help="Base branch name (default: main)",
    )
    parser.add_argument(
        "--ac-tool",
        default=None,
        choices=["claude", "codex"],
        help="CLI backend for acceptance criteria generation (default: claude)",
    )
    parser.add_argument(
        "--verification-judge-tool",
        default=None,
        choices=["claude", "codex"],
        help="CLI backend for verification judge (default: claude)",
    )
    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=None,
        help="Dashboard web UI port (default: 5555)",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Disable the live web dashboard",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions without executing (no agents, no git, no PRs)",
    )

    # Docker isolation
    exec_group = parser.add_mutually_exclusive_group()
    exec_group.add_argument(
        "--docker",
        action="store_const",
        const="docker",
        dest="execution_mode",
        help="Run agents in Docker containers",
    )
    exec_group.add_argument(
        "--host",
        action="store_const",
        const="host",
        dest="execution_mode",
        help="Run agents on the host (default)",
    )
    parser.add_argument(
        "--docker-image",
        default=None,
        help="Docker image for agent containers (default: ghcr.io/t-rav/hydraflow-agent:latest)",
    )
    parser.add_argument(
        "--docker-cpu-limit",
        type=float,
        default=None,
        help="CPU cores per container (default: 2.0)",
    )
    parser.add_argument(
        "--docker-memory-limit",
        default=None,
        help="Memory limit per container (default: 4g)",
    )
    parser.add_argument(
        "--docker-network-mode",
        default=None,
        choices=["bridge", "none", "host"],
        help="Docker network mode (default: bridge)",
    )
    parser.add_argument(
        "--docker-spawn-delay",
        type=float,
        default=None,
        help="Seconds between container starts (default: 2.0)",
    )
    parser.add_argument(
        "--docker-read-only-root",
        action="store_true",
        default=None,
        help="Read-only root filesystem in containers",
    )
    parser.add_argument(
        "--docker-no-new-privileges",
        action="store_true",
        default=None,
        help="Prevent privilege escalation in containers",
    )
    parser.add_argument(
        "--gh-token",
        default=None,
        help="GitHub token for gh CLI auth (overrides HYDRAFLOW_GH_TOKEN and shell GH_TOKEN)",
    )
    parser.add_argument(
        "--git-user-name",
        default=None,
        help="Git user.name for worktree commits; uses global git config if unset",
    )
    parser.add_argument(
        "--git-user-email",
        default=None,
        help="Git user.email for worktree commits; uses global git config if unset",
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help="Path to JSON config file for persisting runtime changes (default: .hydraflow/config.json)",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Scan the repo and report infrastructure gaps",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    parser.add_argument(
        "--log-file",
        default=".hydraflow/logs/hydraflow.log",
        help="Path to log file for structured JSON logging (default: .hydraflow/logs/hydraflow.log)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove all worktrees and state, then exit",
    )
    parser.add_argument(
        "--prep",
        action="store_true",
        help="Create HydraFlow lifecycle labels on the target repo, then exit",
    )
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help="Scan and scaffold GitHub CI + test infrastructure, then exit",
    )
    parser.add_argument(
        "--replay",
        type=int,
        metavar="ISSUE",
        default=None,
        help="Replay a recorded run for the given issue number, then exit",
    )
    parser.add_argument(
        "--replay-latest",
        action="store_true",
        help="When used with --replay, show only the most recent run",
    )

    return parser.parse_args(argv)


def _parse_label_arg(value: str) -> list[str]:
    """Split a comma-separated label string into a list."""
    return [part.strip() for part in value.split(",") if part.strip()]


def build_config(args: argparse.Namespace) -> HydraFlowConfig:
    """Convert parsed CLI args into a :class:`HydraFlowConfig`.

    Merge priority: defaults → config file → env vars → CLI args.
    Only explicitly-provided CLI values are passed through;
    HydraFlowConfig supplies all defaults.
    """
    # 0) Load config file values (lowest priority after defaults)
    from pathlib import Path  # noqa: PLC0415

    config_file_path = getattr(args, "config_file", None) or ".hydraflow/config.json"
    file_kwargs = load_config_file(Path(config_file_path))

    kwargs: dict[str, Any] = {}

    # Start from config file values, then overlay CLI args
    # Filter config file values to known HydraFlowConfig fields
    _known_fields = set(HydraFlowConfig.model_fields.keys())
    for key, val in file_kwargs.items():
        if key in _known_fields:
            kwargs[key] = val

    # Store config_file path
    kwargs["config_file"] = Path(config_file_path)

    # 1) Simple 1:1 fields (CLI attr name == HydraFlowConfig field name)
    # CLI args override config file values
    for field in (
        "batch_size",
        "max_workers",
        "max_planners",
        "max_reviewers",
        "max_hitl_workers",
        "max_budget_usd",
        "model",
        "implementation_tool",
        "review_model",
        "review_tool",
        "review_budget_usd",
        "ci_check_timeout",
        "ci_poll_interval",
        "max_ci_fix_attempts",
        "max_pre_quality_review_attempts",
        "max_review_fix_attempts",
        "min_review_findings",
        "max_merge_conflict_fix_attempts",
        "max_issue_attempts",
        "triage_tool",
        "planner_model",
        "planner_tool",
        "planner_budget_usd",
        "min_plan_words",
        "test_command",
        "repo",
        "main_branch",
        "ac_tool",
        "verification_judge_tool",
        "dashboard_port",
        "gh_token",
        "git_user_name",
        "git_user_email",
        "memory_sync_interval",
        "metrics_sync_interval",
        "execution_mode",
        "docker_image",
        "docker_cpu_limit",
        "docker_memory_limit",
        "docker_network_mode",
        "docker_spawn_delay",
    ):
        val = getattr(args, field)
        if val is not None:
            kwargs[field] = val

    # 2) Label fields: CLI string → list[str]
    for field in (
        "ready_label",
        "review_label",
        "hitl_label",
        "hitl_active_label",
        "fixed_label",
        "find_label",
        "planner_label",
        "improve_label",
        "memory_label",
        "metrics_label",
        "epic_label",
        "lite_plan_labels",
    ):
        val = getattr(args, field)
        if val is not None:
            kwargs[field] = _parse_label_arg(val)

    # 3) Boolean flags (only pass when explicitly set)
    if args.no_dashboard:
        kwargs["dashboard_enabled"] = False
    if args.dry_run:
        kwargs["dry_run"] = True
    if args.docker_read_only_root is True:
        kwargs["docker_read_only_root"] = True
    if args.docker_no_new_privileges is True:
        kwargs["docker_no_new_privileges"] = True

    return HydraFlowConfig(**kwargs)


async def _run_prep(config: HydraFlowConfig) -> bool:
    """Create HydraFlow lifecycle labels on the target repo.

    Returns ``True`` if all labels were created/updated successfully,
    ``False`` if any labels failed.
    """
    from prep import ensure_labels  # noqa: PLC0415

    result = await ensure_labels(config)
    summary = result.summary()
    print(f"[dry-run] {summary}" if config.dry_run else summary)  # noqa: T201
    return not result.failed


async def _run_audit(config: HydraFlowConfig) -> bool:
    """Run a repo audit and print the report. Returns True if critical gaps found."""
    from prep import RepoAuditor  # noqa: PLC0415

    auditor = RepoAuditor(config)
    result = await auditor.run_audit()
    print(result.format_report())  # noqa: T201
    return result.has_critical_gaps


def _makefile_has_target(repo_root: Path, target: str) -> bool:
    """Return True when ``Makefile`` contains the given target."""
    makefile = repo_root / "Makefile"
    if not makefile.is_file():
        return False
    try:
        content = makefile.read_text()
    except OSError:
        return False
    return any(line.startswith(f"{target}:") for line in content.splitlines())


async def _run_hardening_step(
    step: str, cmd: list[str], cwd: Path
) -> tuple[bool, str | None]:
    """Run one prep hardening command and print a concise status line."""
    from subprocess_util import run_subprocess  # noqa: PLC0415

    try:
        await run_subprocess(*cmd, cwd=cwd, timeout=900.0)
        print(f"{step}: ok ({' '.join(cmd)})")  # noqa: T201
        return True, None
    except RuntimeError as exc:
        print(f"{step}: failed ({' '.join(cmd)}): {exc}")  # noqa: T201
        return False, str(exc)


def _slugify_issue_name(step_name: str) -> str:
    """Convert a step name to a safe `.pre` issue slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", step_name.lower()).strip("-")
    return slug or "prep-step"


def _detect_available_prep_tools() -> list[str]:
    """Detect available local prep agent CLIs."""
    tools: list[str] = []
    if shutil.which("claude"):
        tools.append("claude")
    if shutil.which("codex"):
        tools.append("codex")
    return tools


def _best_model_for_tool(tool: str) -> str:
    """Return best default model for the selected tool."""
    if tool == "claude":
        return "opus"
    return "gpt-5.3"


def _choose_prep_tool(configured: str) -> tuple[str | None, str]:
    """Choose prep tool from local availability, prompting when both exist."""
    available = _detect_available_prep_tools()
    if not available:
        return None, "none"
    if len(available) == 1:
        return available[0], "single"

    # Both tools installed.
    if sys.stdin.isatty():
        print("Both Claude and Codex are installed for prep.")  # noqa: T201
        print("Choose prep driver: [1] claude  [2] codex")  # noqa: T201
        choice = input("Selection (default 1): ").strip()  # noqa: T201
        if choice == "2":
            return "codex", "prompt"
        return "claude", "prompt"

    # Non-interactive fallback.
    if configured in ("claude", "codex"):
        return configured, "configured"
    return "claude", "fallback"


def _build_prep_agent_prompt(
    *,
    stack: str,
    failures: list[tuple[str, list[str], str]],
    issue_filenames: list[str],
) -> str:
    """Build correction prompt for prep-agent runs."""
    failure_lines = "\n".join(
        [
            f"- {step}: `{' '.join(cmd)}`\n  Error: {err[:500]}"
            for step, cmd, err in failures
        ]
    )
    issues = "\n".join([f"- .pre/{name}" for name in issue_filenames]) or "- (none)"
    return (
        "You are the HydraFlow prep correction agent.\n"
        f"Stack: {stack}\n\n"
        "Your task:\n"
        "1) Read the local prep issue files listed below.\n"
        "2) Apply code/config fixes in this repo to resolve the failures.\n"
        "3) Keep changes minimal and safe.\n"
        "4) Do not edit files outside this repository.\n\n"
        "Local prep issue files:\n"
        f"{issues}\n\n"
        "Observed failed steps:\n"
        f"{failure_lines}\n\n"
        "Output a concise summary of fixes applied.\n"
    )


async def _run_prep_agent_correction(
    *,
    config: HydraFlowConfig,
    tool: str,
    model: str,
    repo_root: Path,
    stack: str,
    failures: list[tuple[str, list[str], str]],
    issue_filenames: list[str],
) -> bool:
    """Run Claude/Codex as a prep correction agent for one attempt."""
    from agent_cli import build_agent_command  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from runner_utils import stream_claude_process  # noqa: PLC0415

    logger = logging.getLogger("hydraflow.prep")
    prompt = _build_prep_agent_prompt(
        stack=stack, failures=failures, issue_filenames=issue_filenames
    )
    cmd = build_agent_command(
        tool=tool,  # type: ignore[arg-type]
        model=model,
        max_turns=6,
    )
    try:
        transcript = await stream_claude_process(
            cmd=cmd,
            prompt=prompt,
            cwd=repo_root,
            active_procs=set(),
            event_bus=EventBus(),
            event_data={"source": "prep-agent"},
            logger=logger,
            timeout=900.0,
        )
    except RuntimeError as exc:
        print(f"Prep agent correction failed: {exc}")  # noqa: T201
        return False
    if not transcript.strip():
        print("Prep agent correction produced no transcript output")  # noqa: T201
        return False
    print(  # noqa: T201
        f"Prep agent correction completed via {tool} ({model})"
    )
    return True


async def _run_prep_agent_workflow(
    *,
    tool: str,
    model: str,
    config: HydraFlowConfig,
    stack: str,
    local_issue_names: list[str],
) -> tuple[bool, str]:
    """Run an end-to-end prep workflow via Claude/Codex."""
    from agent_cli import build_agent_command  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from runner_utils import stream_claude_process  # noqa: PLC0415

    logger = logging.getLogger("hydraflow.prep")
    issue_list = "\n".join([f"- .pre/{name}" for name in local_issue_names]) or "- none"
    prompt = (
        "You are the HydraFlow prep operator agent.\n"
        f"Driver: {tool}\n"
        f"Stack: {stack}\n\n"
        "Goal: perform complete repository prep autonomously.\n"
        "Requirements:\n"
        "1) Ensure root Makefile has lint/lint-check/typecheck/test/quality targets.\n"
        "2) Ensure GitHub CI quality workflow exists for this stack.\n"
        "3) Ensure test scaffold exists for this stack.\n"
        "4) Run and fix quality/test/build failures iteratively.\n"
        "5) Use local `.pre/*.md` files as issue tracker; update and mark done when fixed.\n"
        "6) Keep changes minimal and safe.\n"
        "7) End response with: PREP_STATUS: SUCCESS or PREP_STATUS: FAILED.\n\n"
        "Current local prep issues:\n"
        f"{issue_list}\n"
    )
    cmd = build_agent_command(
        tool=tool,  # type: ignore[arg-type]
        model=model,
        max_turns=10,
    )
    transcript = await stream_claude_process(
        cmd=cmd,
        prompt=prompt,
        cwd=config.repo_root,
        active_procs=set(),
        event_bus=EventBus(),
        event_data={"source": "prep-workflow-agent"},
        logger=logger,
        timeout=1800.0,
    )
    success = "PREP_STATUS: SUCCESS" in transcript
    return success, transcript


async def _run_scaffold(config: HydraFlowConfig) -> bool:
    """Scan and scaffold core repo essentials (CI + test infrastructure)."""
    from ci_scaffold import scaffold_ci  # noqa: PLC0415
    from makefile_scaffold import scaffold_makefile  # noqa: PLC0415
    from polyglot_prep import (  # noqa: PLC0415
        detect_prep_stack,
        scaffold_tests_polyglot,
    )
    from pre_issue_tracker import (  # noqa: PLC0415
        ensure_pre_dirs,
        load_open_issues,
        mark_done,
        upsert_issue,
        write_run_log,
    )
    from prep import RepoAuditor  # noqa: PLC0415

    ensure_pre_dirs(config.repo_root)
    local_issues = load_open_issues(config.repo_root)
    selected_tool, selection_mode = _choose_prep_tool(config.subskill_tool)
    if selected_tool is None:
        print("Prep aborted: neither Claude nor Codex is installed.")  # noqa: T201
        return False
    selected_model = _best_model_for_tool(selected_tool)

    run_log_lines: list[str] = []
    run_log_lines.append(f"- Repo: `{config.repo}`")
    run_log_lines.append(f"- Dry run: `{config.dry_run}`")
    run_log_lines.append(
        f"- Prep driver: `{selected_tool}` (`{selected_model}` via {selection_mode})"
    )
    run_log_lines.append(f"- Local issue count: `{len(local_issues)}`")
    if local_issues:
        run_log_lines.append("- Local issues:")
        for issue in local_issues:
            run_log_lines.append(f"  - `{issue.path.name}`: {issue.title}")

    audit = await RepoAuditor(config).run_audit()
    print(audit.format_report())  # noqa: T201
    run_log_lines.append("- Audit completed")

    makefile_result = scaffold_makefile(config.repo_root, dry_run=config.dry_run)
    ci_result = scaffold_ci(config.repo_root, dry_run=config.dry_run)
    tests_result = scaffold_tests_polyglot(config.repo_root, dry_run=config.dry_run)
    stack = detect_prep_stack(config.repo_root)
    run_log_lines.append(f"- Detected prep stack: `{stack}`")

    action = "Would create" if config.dry_run else "Created"
    makefile_action = "would add" if config.dry_run else "added"
    if makefile_result.targets_added:
        targets = ", ".join(makefile_result.targets_added)
        print(f"Makefile scaffold: {makefile_action} targets [{targets}]")  # noqa: T201
        run_log_lines.append(
            f"- Makefile scaffold {makefile_action}: targets [{targets}]"
        )
    else:
        print("Makefile scaffold: skipped (targets already present)")  # noqa: T201
        run_log_lines.append("- Makefile scaffold skipped: targets already present")

    if makefile_result.warnings:
        for warning in makefile_result.warnings:
            print(f"Makefile scaffold warning: {warning}")  # noqa: T201
            run_log_lines.append(f"- Makefile scaffold warning: {warning}")

    if ci_result.skipped:
        print(f"CI scaffold: skipped ({ci_result.skip_reason})")  # noqa: T201
        run_log_lines.append(f"- CI scaffold skipped: {ci_result.skip_reason}")
    else:
        print(  # noqa: T201
            f"CI scaffold: {action} {ci_result.workflow_path} ({ci_result.language})"
        )
        run_log_lines.append(
            f"- CI scaffold {action.lower()}: {ci_result.workflow_path} ({ci_result.language})"
        )

    if tests_result.skipped:
        print(f"Test scaffold: skipped ({tests_result.skip_reason})")  # noqa: T201
        run_log_lines.append(f"- Test scaffold skipped: {tests_result.skip_reason}")
    else:
        created_dirs = ", ".join(tests_result.created_dirs) or "-"
        created_files = ", ".join(tests_result.created_files) or "-"
        modified_files = ", ".join(tests_result.modified_files) or "-"
        print(  # noqa: T201
            "Test scaffold: "
            f"{action.lower()} dirs [{created_dirs}] files [{created_files}] "
            f"modified [{modified_files}] ({tests_result.language})"
        )
        run_log_lines.append(
            f"- Test scaffold {action.lower()}: dirs [{created_dirs}] "
            f"files [{created_files}] modified [{modified_files}]"
        )

    if config.dry_run:
        print("Hardening pass: skipped in dry-run mode")  # noqa: T201
        run_log_lines.append("- Hardening skipped in dry-run mode")
        print("Prep summary:")  # noqa: T201
        print(f"- Stack: {stack}")  # noqa: T201
        print("- Hardening: skipped (dry-run)")  # noqa: T201
        print(f"- Local issues open: {len(local_issues)}")  # noqa: T201
        run_log = write_run_log(
            config.repo_root,
            title="Prep Workflow Run",
            lines=run_log_lines,
        )
        print(f"Prep run log: {run_log.relative_to(config.repo_root)}")  # noqa: T201
        return True

    hardening_ok = True
    repo_root = config.repo_root

    max_attempts = 3
    attempts_used = 0
    auto_issues: list[Any] = []
    failure_count = 0
    agent_runs = 0
    agent_successes = 0
    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        attempt_failures: list[tuple[str, list[str], str]] = []
        run_log_lines.append(f"- Hardening attempt {attempt}/{max_attempts}")
        print(f"Hardening attempt {attempt}/{max_attempts}")  # noqa: T201

        issue_names = [issue.path.name for issue in load_open_issues(repo_root)]
        agent_runs += 1
        agent_ok, transcript = await _run_prep_agent_workflow(
            tool=selected_tool,
            model=selected_model,
            config=config,
            stack=stack,
            local_issue_names=issue_names,
        )
        if agent_ok:
            agent_successes += 1
            hardening_ok = True
            run_log_lines.append("- Prep workflow agent: success")
            break
        hardening_ok = False
        failure_count += 1
        attempt_failures.append(
            (
                "prep-workflow-agent",
                [selected_tool, selected_model],
                "Agent reported failure or missing PREP_STATUS: SUCCESS",
            )
        )
        run_log_lines.append("- Prep workflow agent: failed")
        run_log_lines.append(f"- Agent transcript size: {len(transcript)} chars")

        for step_name, cmd, error_msg in attempt_failures:
            slug = _slugify_issue_name(step_name)
            issue = upsert_issue(
                repo_root,
                filename=f"auto-fix-{slug}.md",
                title=f"[prep] Resolve {step_name} failure",
                body_lines=[
                    "## Failure",
                    f"- Step: `{step_name}`",
                    f"- Command: `{' '.join(cmd)}`",
                    "",
                    "## Last Error",
                    "```",
                    error_msg,
                    "```",
                    "",
                    "## Resolution Checklist",
                    "- [ ] identify root cause",
                    "- [ ] apply code/config fix",
                    "- [ ] rerun prep successfully",
                ],
            )
            auto_issues.append(issue)
            run_log_lines.append(f"- Opened/updated local issue: `{issue.path.name}`")

        if attempt < max_attempts:
            attempt_issue_names = [
                f"auto-fix-{_slugify_issue_name(step)}.md"
                for step, _cmd, _err in attempt_failures
            ]
            agent_ok = await _run_prep_agent_correction(
                config=config,
                tool=selected_tool,
                model=selected_model,
                repo_root=repo_root,
                stack=stack,
                failures=attempt_failures,
                issue_filenames=attempt_issue_names,
            )
            if agent_ok:
                agent_successes += 1
            run_log_lines.append(
                f"- Prep agent run {attempt}: {'ok' if agent_ok else 'failed'}"
            )
            run_log_lines.append(
                "- Correction loop: rerunning hardening with updated local issues"
            )

    issues_to_close = list(local_issues) + auto_issues
    if hardening_ok and issues_to_close:
        for issue in issues_to_close:
            mark_done(issue)
        run_log_lines.append(f"- Marked {len(issues_to_close)} local issue(s) done")
    elif issues_to_close:
        run_log_lines.append("- Local issues remain open due to hardening failures")

    print("Prep summary:")  # noqa: T201
    print(f"- Stack: {stack}")  # noqa: T201
    print(f"- Hardening success: {hardening_ok}")  # noqa: T201
    print(f"- Hardening attempts: {attempts_used}/{max_attempts}")  # noqa: T201
    print(f"- Hardening failures observed: {failure_count}")  # noqa: T201
    print(f"- Prep agent runs: {agent_runs} (successful: {agent_successes})")  # noqa: T201
    print(f"- Auto issues opened/updated: {len(auto_issues)}")  # noqa: T201
    print(f"- Local issues initially open: {len(local_issues)}")  # noqa: T201
    print(  # noqa: T201
        f"- Local issues closed this run: {len(issues_to_close) if hardening_ok else 0}"
    )
    run_log_lines.append("- Summary printed to console")

    run_log = write_run_log(
        config.repo_root,
        title="Prep Workflow Run",
        lines=run_log_lines,
    )
    print(f"Prep run log: {run_log.relative_to(config.repo_root)}")  # noqa: T201
    return hardening_ok


async def _run_clean(config: HydraFlowConfig) -> None:
    """Remove all worktrees and reset state."""
    from state import StateTracker
    from worktree import WorktreeManager

    logger = logging.getLogger("hydraflow")
    logger.info("Cleaning up all HydraFlow worktrees and state...")

    wt_mgr = WorktreeManager(config)
    await wt_mgr.destroy_all()

    state = StateTracker(config.state_file)
    state.reset()

    logger.info("Cleanup complete")


def _run_replay(config: HydraFlowConfig, issue_number: int, latest_only: bool) -> None:
    """Display recorded run artifacts for an issue."""
    from run_recorder import RunRecorder  # noqa: PLC0415

    recorder = RunRecorder(config)
    runs = recorder.list_runs(issue_number)

    if not runs:
        print(f"No recorded runs found for issue #{issue_number}")  # noqa: T201
        return

    if latest_only:
        runs = runs[-1:]

    for run in runs:
        print(f"\n{'=' * 60}")  # noqa: T201
        print(f"Issue #{run.issue_number}  |  Run: {run.timestamp}")  # noqa: T201
        print(f"Outcome: {run.outcome}  |  Duration: {run.duration_seconds}s")  # noqa: T201
        if run.error:
            print(f"Error: {run.error}")  # noqa: T201
        print(f"Artifacts: {', '.join(run.files)}")  # noqa: T201

        # Show transcript preview
        transcript = recorder.get_run_artifact(
            issue_number, run.timestamp, "transcript.log"
        )
        if transcript and transcript.strip():
            lines = transcript.strip().splitlines()
            preview = lines[:20]
            print(f"\n--- Transcript ({len(lines)} lines) ---")  # noqa: T201
            for line in preview:
                print(f"  {line}")  # noqa: T201
            if len(lines) > 20:
                print(f"  ... ({len(lines) - 20} more lines)")  # noqa: T201

    print(f"\n{'=' * 60}")  # noqa: T201


async def _run_main(config: HydraFlowConfig) -> None:
    """Launch the orchestrator, optionally with the dashboard."""
    if config.dashboard_enabled:
        from dashboard import HydraFlowDashboard
        from events import EventBus, EventLog, EventType, HydraFlowEvent
        from models import Phase
        from state import StateTracker

        event_log = EventLog(config.event_log_path)
        bus = EventBus(event_log=event_log)
        await bus.rotate_log(
            config.event_log_max_size_mb * 1024 * 1024,
            config.event_log_retention_days,
        )
        await bus.load_history_from_disk()
        state = StateTracker(config.state_file)

        dashboard = HydraFlowDashboard(
            config=config,
            event_bus=bus,
            state=state,
        )
        await dashboard.start()

        # Publish idle phase so the UI shows the Start button
        await bus.publish(
            HydraFlowEvent(
                type=EventType.PHASE_CHANGE,
                data={"phase": Phase.IDLE.value},
            )
        )

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        try:
            await stop_event.wait()
        finally:
            if dashboard._orchestrator and dashboard._orchestrator.running:
                await dashboard._orchestrator.stop()
            await dashboard.stop()
    else:
        from events import EventBus, EventLog

        event_log = EventLog(config.event_log_path)
        bus = EventBus(event_log=event_log)
        await bus.rotate_log(
            config.event_log_max_size_mb * 1024 * 1024,
            config.event_log_retention_days,
        )
        await bus.load_history_from_disk()
        orchestrator = HydraFlowOrchestrator(config, event_bus=bus)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(orchestrator.stop())
            )

        await orchestrator.run()


def main(argv: list[str] | None = None) -> None:
    """Entry point."""
    args = parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=level, json_output=not args.verbose, log_file=args.log_file)

    config = build_config(args)

    if args.prep:
        success = asyncio.run(_run_prep(config))
        sys.exit(0 if success else 1)

    if args.audit:
        has_gaps = asyncio.run(_run_audit(config))
        sys.exit(1 if has_gaps else 0)

    if args.scaffold:
        success = asyncio.run(_run_scaffold(config))
        sys.exit(0 if success else 1)

    if args.clean:
        asyncio.run(_run_clean(config))
        sys.exit(0)

    if args.replay is not None:
        _run_replay(config, args.replay, args.replay_latest)
        sys.exit(0)

    asyncio.run(_run_main(config))


if __name__ == "__main__":
    main()
