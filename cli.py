"""CLI entry point for HydraFlow."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import sys
import time
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from config import HydraFlowConfig, load_config_file
from log import setup_logging
from orchestrator import HydraFlowOrchestrator

_T = TypeVar("_T")

_PREP_COVERAGE_MIN_REQUIRED = 20.0
_PREP_COVERAGE_TARGET = 70.0
_PREP_COVERAGE_ALLOW_MISSING = True
_PREP_COVERAGE_STEP = 10.0
_PREP_COVERAGE_STATE_PATH = ".hydraflow/prep/coverage-floor.json"


def _supports_color_output() -> bool:
    """Return True when ANSI color output should be emitted."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty() and os.environ.get("TERM", "").lower() != "dumb"


def _prep_stage_line(stage: str, detail: str, status: str, color: bool) -> str:
    """Format a concise prep stage status line."""
    colors = {
        "start": "\033[36m",
        "ok": "\033[32m",
        "warn": "\033[33m",
        "fail": "\033[31m",
    }
    glyphs = {
        "start": "\u25b6",
        "ok": "\u2713",
        "warn": "!",
        "fail": "\u2717",
    }
    reset = "\033[0m" if color else ""
    tint = colors.get(status, "") if color else ""
    glyph = glyphs.get(status, ">")
    return f"{tint}[prep:{stage}] {glyph} {detail}{reset}"


async def _await_with_prep_heartbeat(
    awaitable: Coroutine[Any, Any, _T],
    *,
    stage: str,
    detail: str,
    color: bool,
    interval_seconds: float = 20.0,
    tail_provider: Callable[[], list[str]] | None = None,
) -> _T:
    """Await long-running prep work while emitting periodic heartbeat lines."""
    task = asyncio.create_task(awaitable)
    start = asyncio.get_running_loop().time()
    while True:
        try:
            return await asyncio.wait_for(
                asyncio.shield(task), timeout=interval_seconds
            )
        except TimeoutError:
            elapsed = int(asyncio.get_running_loop().time() - start)
            if tail_provider is not None:
                tail = [line for line in tail_provider() if line.strip()]
                if tail:
                    # Live tail already has meaningful output; avoid extra heartbeat noise.
                    continue
            print(  # noqa: T201
                _prep_stage_line(
                    stage,
                    f"{detail} (still running, {elapsed}s elapsed)",
                    "start",
                    color,
                )
            )


def _make_prep_output_tracker(
    *,
    repo_root: Path,
    task_slug: str,
    stream_label: str,
    color: bool,
    min_emit_interval_seconds: float = 1.5,
) -> tuple[Callable[[str], bool], Callable[[], list[str]], Path]:
    """Return (on_output callback, tail getter) for rolling prep task output."""
    from pre_issue_tracker import ensure_pre_dirs  # noqa: PLC0415

    _pre_dir, runs_dir = ensure_pre_dirs(repo_root)
    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    safe_slug = re.sub(r"[^a-z0-9]+", "-", task_slug.lower()).strip("-") or "task"
    live_log_path = runs_dir / f"{ts}-{safe_slug}-live.log"

    state: dict[str, Any] = {
        "tail": [],
        "last_emitted_tail": "",
        "last_emit_at": 0.0,
        "rendered_lines": 0,
        "header_printed": False,
        "start_time": time.monotonic(),
        "written_line_count": 0,
    }
    force_in_place = os.environ.get("HYDRAFLOW_PREP_INPLACE")
    use_in_place = (
        force_in_place != "0"
        and (force_in_place == "1" or sys.stdout.isatty())
        and os.environ.get("TERM", "").lower() != "dumb"
    )

    def on_output(accumulated_text: str) -> bool:
        all_lines = [ln for ln in accumulated_text.splitlines() if ln.strip()]
        if len(all_lines) > state["written_line_count"]:
            new_lines = all_lines[state["written_line_count"] :]
            with live_log_path.open("a", encoding="utf-8") as fh:
                for line in new_lines:
                    fh.write(f"{line}\n")
            state["written_line_count"] = len(all_lines)

        display_lines = [
            ln
            for ln in all_lines
            if not ln.startswith('{"type":"system"')
            and '"type":"rate_limit_event"' not in ln
        ]
        tail = display_lines[-3:]
        state["tail"] = tail
        if not tail:
            return False

        tail_text = "\n".join(tail)
        now = time.monotonic()
        if (
            tail_text != state["last_emitted_tail"]
            and now - state["last_emit_at"] >= min_emit_interval_seconds
        ):
            elapsed = int(now - state["start_time"])
            lines_to_render = [
                _prep_stage_line(
                    "hardening",
                    f"{stream_label}: live output (rolling 3 lines, {elapsed}s)",
                    "start",
                    color,
                ),
                *[f"  {line}" for line in tail],
            ]
            if use_in_place:
                rendered_lines = state["rendered_lines"]
                if rendered_lines:
                    # Move cursor to the start of the previously rendered block.
                    sys.stdout.write(f"\x1b[{rendered_lines}A")
                clear_count = max(rendered_lines, len(lines_to_render))
                for i in range(clear_count):
                    sys.stdout.write("\x1b[2K\r")
                    if i < len(lines_to_render):
                        sys.stdout.write(lines_to_render[i])
                    sys.stdout.write("\n")
                sys.stdout.flush()
                state["rendered_lines"] = len(lines_to_render)
            else:
                if not state["header_printed"]:
                    print(lines_to_render[0])  # noqa: T201
                    state["header_printed"] = True
                for line in lines_to_render[1:]:
                    print(line)  # noqa: T201
            state["last_emitted_tail"] = tail_text
            state["last_emit_at"] = now
        return False

    def get_tail() -> list[str]:
        return list(state["tail"])

    return on_output, get_tail, live_log_path


def _write_prep_task_transcript(
    *,
    repo_root: Path,
    task_slug: str,
    transcript: str,
) -> Path | None:
    """Persist a prep task transcript under ``.hydraflow/prep/runs/<run-id>``."""
    from pre_issue_tracker import ensure_pre_dirs  # noqa: PLC0415

    if not transcript.strip():
        return None
    _pre_dir, runs_dir = ensure_pre_dirs(repo_root)
    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    safe_slug = re.sub(r"[^a-z0-9]+", "-", task_slug.lower()).strip("-") or "task"
    path = runs_dir / f"{ts}-{safe_slug}.log"
    path.write_text(transcript, encoding="utf-8")
    return path


def _append_full_run_log_line(repo_root: Path, line: str) -> Path:
    """Append one line to `.hydraflow/prep/runs/<run-id>/full-run.log` and return its path."""
    from pre_issue_tracker import ensure_pre_dirs  # noqa: PLC0415

    _pre_dir, runs_dir = ensure_pre_dirs(repo_root)
    path = runs_dir / "full-run.log"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{line}\n")
    return path


def _build_prep_failure_error_message(transcript: str, transcript_ref: str) -> str:
    """Build a concrete failure message for local `.hydraflow/prep` issues."""
    if re.search(r"PREP_RESULT_JSON\s*:\s*\{", transcript, re.IGNORECASE):
        reason = "Agent returned PREP_RESULT_JSON with non-success status."
    elif re.search(r"PREP_STATUS\s*:\s*FAILED", transcript, re.IGNORECASE):
        reason = "Agent returned PREP_STATUS: FAILED."
    elif re.search(r"File has not been read yet", transcript, re.IGNORECASE):
        reason = (
            "Agent hit tool precondition failure: attempted Edit before Read "
            '("File has not been read yet").'
        )
    elif re.search(
        r"(max[\s_-]*turns?|turn limit|conversation limit)", transcript, re.IGNORECASE
    ):
        reason = "Agent hit conversation turn limit before finishing prep."
    elif not transcript.strip():
        reason = "Agent produced an empty transcript."
    else:
        reason = "Agent did not return PREP_RESULT_JSON with prep_status SUCCESS."

    lines = [ln for ln in transcript.splitlines() if ln.strip()]
    tail = "\n".join(lines[-30:])
    tail = tail[-3000:] if tail else "(no output)"
    return f"{reason}\nTranscript path: {transcript_ref}\n\nLast output tail:\n{tail}"


def _parse_prep_result(transcript: str) -> tuple[bool, str]:
    """Parse structured prep result from transcript.

    Returns ``(success, mode)`` where mode is ``json`` or ``legacy``.
    """
    json_match = re.search(
        r"PREP_RESULT_JSON\s*:\s*(\{.*\})", transcript, re.IGNORECASE
    )
    if json_match:
        try:
            payload = json.loads(json_match.group(1))
            status = str(payload.get("prep_status", "")).strip().upper()
            if status == "SUCCESS":
                return True, "json"
            if status == "FAILED":
                return False, "json"
        except json.JSONDecodeError:
            pass

    return bool(
        re.search(r"PREP_STATUS\s*:\s*SUCCESS", transcript, re.IGNORECASE)
    ), "legacy"


def _prep_failure_signature(error_message: str) -> str:
    """Return a short stable signature for a prep failure payload."""
    digest = hashlib.sha256(error_message.encode("utf-8")).hexdigest()
    return digest[:10]


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
        "model",
        "implementation_tool",
        "review_model",
        "review_tool",
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
    from prep import RepoAuditor, ensure_labels  # noqa: PLC0415

    use_color = _supports_color_output()
    print(_prep_stage_line("labels", "syncing lifecycle labels", "start", use_color))  # noqa: T201
    result = await ensure_labels(config)
    summary = result.summary()
    print(f"[dry-run] {summary}" if config.dry_run else summary)  # noqa: T201
    if result.failed:
        print(
            _prep_stage_line(
                "labels", "label sync completed with failures", "fail", use_color
            )
        )  # noqa: T201
    else:
        print(_prep_stage_line("labels", "label sync complete", "ok", use_color))  # noqa: T201

    print(
        _prep_stage_line("audit", "running repository prep audit", "start", use_color)
    )  # noqa: T201
    audit = await RepoAuditor(config).run_audit()
    print(audit.format_report(color=use_color))  # noqa: T201
    if audit.missing_checks:
        print(_prep_stage_line("audit", "gaps detected", "warn", use_color))  # noqa: T201
    else:
        print(_prep_stage_line("audit", "all checks passing", "ok", use_color))  # noqa: T201
    return not result.failed


async def _run_audit(config: HydraFlowConfig) -> bool:
    """Run a repo audit and print the report. Returns True if critical gaps found."""
    from prep import RepoAuditor  # noqa: PLC0415

    auditor = RepoAuditor(config)
    result = await auditor.run_audit()
    print(result.format_report(color=_supports_color_output()))  # noqa: T201
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


def _extract_coverage_percent(repo_root: Path) -> tuple[float | None, str]:
    """Extract coverage percentage from common report artifacts."""
    json_reports = [
        repo_root / "coverage" / "coverage-summary.json",
        repo_root / "coverage-summary.json",
    ]
    for path in json_reports:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
            pct = data.get("total", {}).get("lines", {}).get("pct")
            if isinstance(pct, int | float):
                return float(pct), str(path.relative_to(repo_root))
        except (OSError, json.JSONDecodeError):
            continue

    xml_reports = [
        repo_root / "coverage.xml",
        repo_root / "cobertura.xml",
        repo_root / "jacoco.xml",
    ]
    for path in xml_reports:
        if not path.is_file():
            continue
        try:
            content = path.read_text()
            line_rate_match = re.search(
                r"\bline-rate=['\"]([0-9]*\.?[0-9]+)['\"]", content
            )
            if line_rate_match:
                return (
                    float(line_rate_match.group(1)) * 100.0,
                    str(path.relative_to(repo_root)),
                )

            missed = 0
            covered = 0
            for counter in re.finditer(
                r"<counter\b[^>]*\btype=['\"]LINE['\"][^>]*>", content
            ):
                tag = counter.group(0)
                missed_match = re.search(r"\bmissed=['\"](\d+)['\"]", tag)
                covered_match = re.search(r"\bcovered=['\"](\d+)['\"]", tag)
                if missed_match and covered_match:
                    missed += int(missed_match.group(1))
                    covered += int(covered_match.group(1))
            total = missed + covered
            if total > 0:
                return (covered / total) * 100.0, str(path.relative_to(repo_root))
        except (OSError, ValueError):
            continue

    lcov_reports = [repo_root / "coverage" / "lcov.info", repo_root / "lcov.info"]
    for path in lcov_reports:
        if not path.is_file():
            continue
        try:
            lf_total = 0
            lh_total = 0
            for line in path.read_text().splitlines():
                if line.startswith("LF:"):
                    lf_total += int(line[3:])
                elif line.startswith("LH:"):
                    lh_total += int(line[3:])
            if lf_total > 0:
                return (lh_total / lf_total) * 100.0, str(path.relative_to(repo_root))
        except (OSError, ValueError):
            continue

    go_cover = repo_root / "coverage.out"
    if go_cover.is_file():
        try:
            total_stmts = 0
            covered_stmts = 0
            for line in go_cover.read_text().splitlines():
                if line.startswith("mode:"):
                    continue
                parts = line.split()
                if len(parts) != 3:
                    continue
                stmt_count = int(parts[1])
                hit_count = int(parts[2])
                total_stmts += stmt_count
                if hit_count > 0:
                    covered_stmts += stmt_count
            if total_stmts > 0:
                return (
                    (covered_stmts / total_stmts) * 100.0,
                    str(go_cover.relative_to(repo_root)),
                )
        except (OSError, ValueError):
            pass

    return None, "no coverage artifact found"


def _evaluate_coverage_validation(
    repo_root: Path,
    *,
    min_required: float = 70.0,
    target: float = 70.0,
    allow_missing_artifact: bool = False,
) -> tuple[bool, bool, str]:
    """Evaluate coverage result.

    Returns ``(passes_loop, warning_only, detail)``.
    """
    pct, source = _extract_coverage_percent(repo_root)
    if pct is None:
        if allow_missing_artifact:
            return (
                True,
                True,
                "Coverage warning: no coverage report artifact found; "
                f"allowing prep fallback floor {min_required:.0f}% "
                f"(CI target remains {target:.0f}%+).",
            )
        return (
            False,
            False,
            "Coverage validation failed: no coverage report artifact found. "
            "Generate one (coverage.xml, coverage-summary.json, lcov.info, or coverage.out).",
        )
    if pct < min_required:
        return (
            False,
            False,
            f"Coverage validation failed: {pct:.1f}% from {source} is below minimum {min_required:.0f}%.",
        )
    if pct < target:
        return (
            True,
            True,
            f"Coverage warning: {pct:.1f}% from {source}; minimum met, target is {target:.0f}%+.",
        )
    return (
        True,
        False,
        f"Coverage validation passed: {pct:.1f}% from {source} (target {target:.0f}%+).",
    )


def _project_has_test_signal(project_root: Path) -> bool:
    """Return True if a project appears to have runnable tests."""
    tests_dir = project_root / "tests"
    has_python_tests = tests_dir.is_dir() and (
        list(tests_dir.glob("test_*.py")) or list(tests_dir.glob("*_test.py"))
    )

    js_tests_dir = project_root / "__tests__"
    has_js_tests = js_tests_dir.is_dir() and (
        list(js_tests_dir.glob("*.test.*")) or list(js_tests_dir.glob("*.spec.*"))
    )

    has_pytest_config = (project_root / "pytest.ini").is_file()
    has_js_test_config = any(
        (project_root / name).is_file()
        for name in (
            "vitest.config.js",
            "vitest.config.ts",
            "jest.config.js",
            "jest.config.ts",
            "jest.config.json",
        )
    )

    has_test_script = False
    package_json = project_root / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text())
            scripts = data.get("scripts", {})
            has_test_script = isinstance(scripts, dict) and "test" in scripts
        except (OSError, json.JSONDecodeError):
            has_test_script = False

    return any(
        (
            _makefile_has_target(project_root, "test"),
            has_python_tests,
            has_js_tests,
            has_pytest_config,
            has_js_test_config,
            has_test_script,
        )
    )


def _coverage_validation_roots(repo_root: Path, project_paths: list[str]) -> list[Path]:
    """Return fan-out project roots that should be coverage-validated."""
    roots: list[Path] = []
    seen: set[Path] = set()
    candidates = [repo_root]
    for rel_path in project_paths:
        candidate = repo_root if rel_path in ("", ".") else repo_root / rel_path
        candidates.append(candidate)

    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _project_has_test_signal(candidate):
            roots.append(candidate)
    return roots


def _evaluate_coverage_validation_projects(
    repo_root: Path,
    project_roots: list[Path],
    *,
    min_required: float = 70.0,
    target: float = 70.0,
    allow_missing_artifact: bool = False,
) -> tuple[bool, bool, str]:
    """Evaluate coverage thresholds across all test-bearing project roots."""
    if not project_roots:
        return (
            True,
            True,
            "Coverage validation skipped: no fan-out project with tests detected.",
        )

    any_warn = False
    failed_details: list[str] = []
    ok_details: list[str] = []
    for project_root in project_roots:
        rel = (
            "."
            if project_root == repo_root
            else str(project_root.relative_to(repo_root))
        )
        ok, warn, detail = _evaluate_coverage_validation(
            project_root,
            min_required=min_required,
            target=target,
            allow_missing_artifact=allow_missing_artifact,
        )
        line = f"{rel}: {detail}"
        if ok:
            ok_details.append(line)
            any_warn = any_warn or warn
        else:
            failed_details.append(line)

    if failed_details:
        return False, False, " | ".join(failed_details)
    return True, any_warn, " | ".join(ok_details)


def _coverage_below_target_from_detail(detail: str, target: float) -> bool:
    """Return True if any rendered coverage percentage is below target."""
    for match in re.finditer(r"(\d+(?:\.\d+)?)% from ", detail):
        if float(match.group(1)) < target:
            return True
    return False


def _prep_coverage_has_measurement(detail: str) -> bool:
    """Return True when coverage detail includes at least one measured percentage."""
    return bool(re.search(r"\d+(?:\.\d+)?% from ", detail))


def _load_prep_coverage_floor(repo_root: Path) -> float:
    """Load persisted prep coverage minimum floor for ratcheting."""
    state_path = repo_root / _PREP_COVERAGE_STATE_PATH
    if not state_path.is_file():
        return _PREP_COVERAGE_MIN_REQUIRED
    try:
        payload = json.loads(state_path.read_text())
        raw = payload.get("min_required")
        if isinstance(raw, int | float):
            return float(
                max(_PREP_COVERAGE_MIN_REQUIRED, min(_PREP_COVERAGE_TARGET, raw))
            )
    except (OSError, json.JSONDecodeError):
        return _PREP_COVERAGE_MIN_REQUIRED
    return _PREP_COVERAGE_MIN_REQUIRED


def _save_prep_coverage_floor(repo_root: Path, min_required: float) -> None:
    """Persist prep coverage minimum floor for future runs."""
    value = float(
        max(_PREP_COVERAGE_MIN_REQUIRED, min(_PREP_COVERAGE_TARGET, min_required))
    )
    state_path = repo_root / _PREP_COVERAGE_STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"min_required": value}, indent=2) + "\n", encoding="utf-8"
    )


def _slugify_issue_name(step_name: str) -> str:
    """Convert a step name to a safe `.hydraflow/prep` issue slug."""
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
    return "gpt-5-codex"


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
    issues = (
        "\n".join([f"- .hydraflow/prep/{name}" for name in issue_filenames])
        or "- (none)"
    )
    return (
        "You are the HydraFlow prep correction agent.\n"
        f"Stack: {stack}\n\n"
        "Your task:\n"
        "1) Read the local prep issue files listed below.\n"
        "2) Apply code/config fixes in this repo to resolve the failures.\n"
        "3) Keep changes minimal and safe.\n"
        "4) Do not edit files outside this repository.\n"
        "5) Drive verification through Make targets when available "
        "(lint-fix, lint-check, typecheck, test, quality-lite, quality).\n"
        "6) Before each Edit, Read that file first. If a tool error says a file has not "
        "been read yet, immediately read it and retry the edit.\n"
        "7) For independent failures, fan out work to sub-agents in parallel when available "
        "(max 4 concurrent tracks).\n"
        "8) Within each track, apply edits one file at a time and verify before the next edit.\n"
        "9) Do not refactor unrelated application source to chase existing lint debt. "
        "If failures are outside prep-managed files, record/update `.hydraflow/prep` issues with "
        "concrete failing commands and file paths.\n\n"
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
    on_output: Callable[[str], bool] | None = None,
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
            on_output=on_output,
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
    project_paths: list[str],
    on_output: Callable[[str], bool] | None = None,
) -> tuple[bool, str]:
    """Run an end-to-end prep workflow via Claude/Codex."""
    from agent_cli import build_agent_command  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from runner_utils import stream_claude_process  # noqa: PLC0415

    logger = logging.getLogger("hydraflow.prep")
    issue_list = (
        "\n".join([f"- .hydraflow/prep/{name}" for name in local_issue_names])
        or "- none"
    )
    fanout_paths = "\n".join([f"- {path}" for path in project_paths]) or "- ."
    prompt = (
        "You are the HydraFlow prep operator agent.\n"
        f"Driver: {tool}\n"
        f"Stack: {stack}\n\n"
        "Goal: perform complete repository prep autonomously.\n"
        "Requirements:\n"
        "1) Ensure root Makefile has lint/lint-check/lint-fix/typecheck/security/"
        "test/quality-lite/quality targets.\n"
        "2) Ensure GitHub CI quality workflow exists for this stack.\n"
        "3) Ensure test scaffold exists for this stack.\n"
        "4) Run and fix quality/test/build failures iteratively.\n"
        "5) Use local `.hydraflow/prep/*.md` files as issue tracker; update and mark done when fixed.\n"
        "6) Keep changes minimal and safe.\n"
        "7) End response with EXACTLY one final line in JSON form:\n"
        'PREP_RESULT_JSON: {"prep_status":"SUCCESS|FAILED","summary":"...","coverage":{"status":"PASS|FAIL","notes":"..."}}\n\n'
        "8) Prefer Make targets for checks/fixes (lint-fix, lint-check, typecheck, test, "
        "quality-lite, quality) instead of ad-hoc commands.\n"
        "8a) If running Vitest directly, always exclude the hydraflow submodule path "
        "(`--exclude='hydraflow/**'`) unless vitest config already excludes it.\n"
        "9) Before each Edit, Read that file first. If a tool error says the file was not "
        "read yet, read it and retry the edit.\n"
        "10) Continue until `make quality` passes or you can provide a concrete failing "
        "command and file list, then emit the final PREP_RESULT_JSON line.\n"
        "11) Keep edits scoped to prep-managed files only (Makefile, .github/workflows/*, "
        "package manager files, lint/type config, test scaffold, hooks). Avoid refactoring "
        "existing app source files for pre-existing lint debt.\n"
        "12) Fan out independent work to sub-agents in parallel whenever possible "
        "(for example: one track per project path or quality gate; max 4 concurrent tracks).\n"
        "13) Within each track, keep edits serialized (one file at a time) and verify before "
        "moving to the next file.\n"
        "14) Coverage policy for all stacks: enforce at least 70% meaningful coverage; "
        "coverage should prioritize critical paths, not filler "
        "tests (for example, property-only inflation).\n"
        "15) If remaining failures are in existing app source, create/update `.hydraflow/prep` issues "
        "with command output + affected files, then end with PREP_RESULT_JSON prep_status FAILED.\n\n"
        "Fan-out project paths (parallelize across these when possible):\n"
        f"{fanout_paths}\n\n"
        "Current local prep issues:\n"
        f"{issue_list}\n"
    )
    cmd = build_agent_command(
        tool=tool,  # type: ignore[arg-type]
        model=model,
        max_turns=20,
    )
    transcript = await stream_claude_process(
        cmd=cmd,
        prompt=prompt,
        cwd=config.repo_root,
        active_procs=set(),
        event_bus=EventBus(),
        event_data={"source": "prep-workflow-agent"},
        logger=logger,
        on_output=on_output,
        timeout=1800.0,
    )
    success, _mode = _parse_prep_result(transcript)
    return success, transcript


async def _run_scaffold(config: HydraFlowConfig) -> bool:
    """Scan and scaffold core repo essentials (CI + test infrastructure)."""
    from ci_scaffold import scaffold_ci  # noqa: PLC0415
    from makefile_scaffold import scaffold_makefiles  # noqa: PLC0415
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

    use_color = _supports_color_output()
    run_id = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S-%f")
    os.environ["HYDRAFLOW_PREP_RUN_ID"] = run_id
    ensure_pre_dirs(config.repo_root)
    local_issues = load_open_issues(config.repo_root)
    selected_tool, selection_mode = _choose_prep_tool(config.subskill_tool)
    if selected_tool is None:
        print("Prep aborted: neither Claude nor Codex is installed.")  # noqa: T201
        return False
    selected_model = _best_model_for_tool(selected_tool)
    full_run_log_path = _append_full_run_log_line(
        config.repo_root,
        f"=== prep run start ({datetime.now(tz=UTC).isoformat()}) ===",
    )

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
    print(audit.format_report(color=_supports_color_output()))  # noqa: T201
    run_log_lines.append("- Audit completed")

    makefile_results = scaffold_makefiles(config.repo_root, dry_run=config.dry_run)
    ci_result = scaffold_ci(config.repo_root, dry_run=config.dry_run)
    tests_result = scaffold_tests_polyglot(config.repo_root, dry_run=config.dry_run)
    stack = detect_prep_stack(config.repo_root)
    run_log_lines.append(f"- Detected prep stack: `{stack}`")

    action = "Would create" if config.dry_run else "Created"
    makefile_action = "would add" if config.dry_run else "added"
    if makefile_results.results:
        total_added = 0
        for rel_path, makefile_result in sorted(makefile_results.results.items()):
            if makefile_result.targets_added:
                targets = ", ".join(makefile_result.targets_added)
                print(  # noqa: T201
                    f"Makefile scaffold [{rel_path}]: {makefile_action} targets [{targets}]"
                )
                run_log_lines.append(
                    f"- Makefile scaffold [{rel_path}] {makefile_action}: targets [{targets}]"
                )
                total_added += len(makefile_result.targets_added)
            else:
                print(  # noqa: T201
                    f"Makefile scaffold [{rel_path}]: skipped (targets already present)"
                )
                run_log_lines.append(
                    f"- Makefile scaffold [{rel_path}] skipped: targets already present"
                )
            if makefile_result.warnings:
                for warning in makefile_result.warnings:
                    print(  # noqa: T201
                        f"Makefile scaffold warning [{rel_path}]: {warning}"
                    )
                    run_log_lines.append(
                        f"- Makefile scaffold warning [{rel_path}]: {warning}"
                    )
        run_log_lines.append(
            f"- Makefile scaffold project count: {len(makefile_results.results)}"
        )
        run_log_lines.append(f"- Makefile scaffold total targets added: {total_added}")
    else:
        print("Makefile scaffold: no supported project paths discovered")  # noqa: T201
        run_log_lines.append("- Makefile scaffold skipped: no supported project paths")

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
        if getattr(tests_result, "progress", ""):
            print(f"Test scaffold progress: {tests_result.progress}")  # noqa: T201
            run_log_lines.append(f"- Test scaffold progress: {tests_result.progress}")
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
        if getattr(tests_result, "progress", ""):
            print(f"Test scaffold progress: {tests_result.progress}")  # noqa: T201
            run_log_lines.append(f"- Test scaffold progress: {tests_result.progress}")

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
    workflow_project_paths = sorted(makefile_results.results.keys()) or ["."]
    coverage_roots = _coverage_validation_roots(
        repo_root, list(makefile_results.results.keys())
    )
    coverage_min_required = _load_prep_coverage_floor(repo_root)
    coverage_scope = (
        ", ".join(
            "." if p == repo_root else str(p.relative_to(repo_root))
            for p in coverage_roots
        )
        or "none"
    )
    run_log_lines.append(f"- Coverage validation scope: {coverage_scope}")
    run_log_lines.append(
        f"- Coverage validation minimum floor: {coverage_min_required:.0f}% "
        f"(ratchets +{_PREP_COVERAGE_STEP:.0f} to max {_PREP_COVERAGE_TARGET:.0f}%)"
    )

    max_attempts = 3
    attempts_used = 0
    auto_issues: list[Any] = []
    failure_count = 0
    agent_runs = 0
    agent_successes = 0
    coverage_below_target = False
    stage_line = _prep_stage_line(
        "hardening",
        f"starting hardening loop ({max_attempts} max attempts)",
        "start",
        use_color,
    )
    print(stage_line)  # noqa: T201
    _append_full_run_log_line(config.repo_root, stage_line)
    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        attempt_failures: list[tuple[str, list[str], str]] = []
        run_log_lines.append(f"- Hardening attempt {attempt}/{max_attempts}")
        plain_line = f"Hardening attempt {attempt}/{max_attempts}"
        print(plain_line)  # noqa: T201
        _append_full_run_log_line(config.repo_root, plain_line)
        stage_line = _prep_stage_line(
            "hardening",
            f"attempt {attempt}/{max_attempts}: collecting open .hydraflow/prep issues",
            "start",
            use_color,
        )
        print(stage_line)  # noqa: T201
        _append_full_run_log_line(config.repo_root, stage_line)

        issue_names = [issue.path.name for issue in load_open_issues(repo_root)]
        issue_preview = ", ".join(issue_names[:3]) if issue_names else "none"
        if len(issue_names) > 3:
            issue_preview = f"{issue_preview}, +{len(issue_names) - 3} more"
        stage_line = _prep_stage_line(
            "hardening",
            f"attempt {attempt}/{max_attempts}: active issues [{issue_preview}]",
            "start",
            use_color,
        )
        print(stage_line)  # noqa: T201
        _append_full_run_log_line(config.repo_root, stage_line)
        agent_runs += 1
        stage_line = _prep_stage_line(
            "hardening",
            (
                f"attempt {attempt}/{max_attempts}: running prep workflow agent "
                f"via {selected_tool} ({selected_model}) with {len(issue_names)} issue(s)"
            ),
            "start",
            use_color,
        )
        print(stage_line)  # noqa: T201
        _append_full_run_log_line(config.repo_root, stage_line)
        workflow_on_output, workflow_tail, workflow_live_log = (
            _make_prep_output_tracker(
                repo_root=repo_root,
                task_slug=f"attempt-{attempt}-prep-workflow-agent",
                stream_label=f"attempt {attempt}/{max_attempts}: prep workflow agent",
                color=use_color,
            )
        )
        workflow_live_log_ref = workflow_live_log.relative_to(repo_root)
        stage_line = _prep_stage_line(
            "hardening",
            f"attempt {attempt}/{max_attempts}: live log {workflow_live_log_ref}",
            "start",
            use_color,
        )
        print(stage_line)  # noqa: T201
        _append_full_run_log_line(config.repo_root, stage_line)
        run_log_lines.append(f"- Workflow live log: `{workflow_live_log_ref}`")
        agent_ok, transcript = await _await_with_prep_heartbeat(
            _run_prep_agent_workflow(
                tool=selected_tool,
                model=selected_model,
                config=config,
                stack=stack,
                local_issue_names=issue_names,
                project_paths=workflow_project_paths,
                on_output=workflow_on_output,
            ),
            stage="hardening",
            detail=f"attempt {attempt}/{max_attempts}: prep workflow agent",
            color=use_color,
            tail_provider=workflow_tail,
        )
        if agent_ok:
            agent_successes += 1
            run_log_lines.append("- Prep workflow agent: success")
            coverage_ok, coverage_warn, coverage_detail = (
                _evaluate_coverage_validation_projects(
                    repo_root,
                    coverage_roots,
                    min_required=coverage_min_required,
                    target=_PREP_COVERAGE_TARGET,
                    allow_missing_artifact=_PREP_COVERAGE_ALLOW_MISSING,
                )
            )
            if _coverage_below_target_from_detail(
                coverage_detail, _PREP_COVERAGE_TARGET
            ):
                coverage_below_target = True
            coverage_lines = [
                line.strip() for line in coverage_detail.split(" | ") if line.strip()
            ]
            if coverage_lines:
                run_log_lines.append("- Coverage validation details:")
                for line in coverage_lines:
                    run_log_lines.append(f"  - {line}")
            else:
                run_log_lines.append(f"- {coverage_detail}")
            if coverage_ok:
                hardening_ok = True
                for line in coverage_lines:
                    stage_line = _prep_stage_line(
                        "coverage",
                        f"attempt {attempt}/{max_attempts}: {line}",
                        "warn" if coverage_warn else "ok",
                        use_color,
                    )
                    print(stage_line)  # noqa: T201
                    _append_full_run_log_line(config.repo_root, stage_line)
                stage_line = _prep_stage_line(
                    "hardening",
                    (
                        f"attempt {attempt}/{max_attempts}: prep workflow agent "
                        f"reported success ({coverage_detail})"
                    ),
                    "warn" if coverage_warn else "ok",
                    use_color,
                )
                print(stage_line)  # noqa: T201
                _append_full_run_log_line(config.repo_root, stage_line)
                if (
                    _prep_coverage_has_measurement(coverage_detail)
                    and coverage_min_required < _PREP_COVERAGE_TARGET
                ):
                    bumped_floor = min(
                        _PREP_COVERAGE_TARGET,
                        coverage_min_required + _PREP_COVERAGE_STEP,
                    )
                    if bumped_floor > coverage_min_required:
                        _save_prep_coverage_floor(repo_root, bumped_floor)
                        run_log_lines.append(
                            f"- Coverage minimum floor ratcheted: "
                            f"{coverage_min_required:.0f}% -> {bumped_floor:.0f}%"
                        )
                        stage_line = _prep_stage_line(
                            "coverage",
                            (
                                "ratcheted prep coverage floor to "
                                f"{bumped_floor:.0f}% "
                                f"(max {_PREP_COVERAGE_TARGET:.0f}%)"
                            ),
                            "ok",
                            use_color,
                        )
                        print(stage_line)  # noqa: T201
                        _append_full_run_log_line(config.repo_root, stage_line)
                        coverage_min_required = bumped_floor
                break

            hardening_ok = False
            failure_count += 1
            attempt_failures.append(
                ("coverage-validation", ["coverage-analyzer"], coverage_detail)
            )
            for line in coverage_lines:
                stage_line = _prep_stage_line(
                    "coverage",
                    f"attempt {attempt}/{max_attempts}: {line}",
                    "warn",
                    use_color,
                )
                print(stage_line)  # noqa: T201
                _append_full_run_log_line(config.repo_root, stage_line)
            stage_line = _prep_stage_line(
                "hardening",
                (
                    f"attempt {attempt}/{max_attempts}: coverage validation failed "
                    f"after workflow success ({coverage_detail})"
                ),
                "warn",
                use_color,
            )
            print(stage_line)  # noqa: T201
            _append_full_run_log_line(config.repo_root, stage_line)
        else:
            hardening_ok = False
            failure_count += 1
            transcript_path = _write_prep_task_transcript(
                repo_root=repo_root,
                task_slug=f"attempt-{attempt}-prep-workflow-agent",
                transcript=transcript,
            )
            transcript_ref = (
                str(transcript_path.relative_to(repo_root))
                if transcript_path is not None
                else "unavailable"
            )
            error_message = _build_prep_failure_error_message(
                transcript, transcript_ref
            )
            attempt_failures.append(
                (
                    "prep-workflow-agent",
                    [selected_tool, selected_model],
                    error_message,
                )
            )
            run_log_lines.append("- Prep workflow agent: failed")
            run_log_lines.append(f"- Agent transcript size: {len(transcript)} chars")
            run_log_lines.append(f"- Agent transcript path: `{transcript_ref}`")
            stage_line = _prep_stage_line(
                "hardening",
                (
                    f"attempt {attempt}/{max_attempts}: prep workflow agent failed "
                    f"(transcript {len(transcript)} chars, path {transcript_ref})"
                ),
                "warn",
                use_color,
            )
            print(stage_line)  # noqa: T201
            _append_full_run_log_line(config.repo_root, stage_line)

        attempt_issue_names: list[str] = []
        for step_name, cmd, error_msg in attempt_failures:
            slug = _slugify_issue_name(step_name)
            sig = _prep_failure_signature(error_msg)
            issue = upsert_issue(
                repo_root,
                filename=f"auto-fix-{slug}-{sig}.md",
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
            attempt_issue_names.append(issue.path.name)
            run_log_lines.append(f"- Opened/updated local issue: `{issue.path.name}`")
            stage_line = _prep_stage_line(
                "hardening",
                f"attempt {attempt}/{max_attempts}: opened/updated {issue.path.name}",
                "warn",
                use_color,
            )
            print(stage_line)  # noqa: T201
            _append_full_run_log_line(config.repo_root, stage_line)

        if attempt < max_attempts:
            stage_line = _prep_stage_line(
                "hardening",
                f"attempt {attempt}/{max_attempts}: running correction agent",
                "start",
                use_color,
            )
            print(stage_line)  # noqa: T201
            _append_full_run_log_line(config.repo_root, stage_line)
            correction_on_output, correction_tail, correction_live_log = (
                _make_prep_output_tracker(
                    repo_root=repo_root,
                    task_slug=f"attempt-{attempt}-correction-agent",
                    stream_label=f"attempt {attempt}/{max_attempts}: correction agent",
                    color=use_color,
                )
            )
            correction_live_log_ref = correction_live_log.relative_to(repo_root)
            stage_line = _prep_stage_line(
                "hardening",
                f"attempt {attempt}/{max_attempts}: correction live log {correction_live_log_ref}",
                "start",
                use_color,
            )
            print(stage_line)  # noqa: T201
            _append_full_run_log_line(config.repo_root, stage_line)
            run_log_lines.append(f"- Correction live log: `{correction_live_log_ref}`")
            agent_ok = await _await_with_prep_heartbeat(
                _run_prep_agent_correction(
                    config=config,
                    tool=selected_tool,
                    model=selected_model,
                    repo_root=repo_root,
                    stack=stack,
                    failures=attempt_failures,
                    issue_filenames=attempt_issue_names,
                    on_output=correction_on_output,
                ),
                stage="hardening",
                detail=f"attempt {attempt}/{max_attempts}: correction agent",
                color=use_color,
                tail_provider=correction_tail,
            )
            if agent_ok:
                agent_successes += 1
                stage_line = _prep_stage_line(
                    "hardening",
                    f"attempt {attempt}/{max_attempts}: correction agent completed",
                    "ok",
                    use_color,
                )
                print(stage_line)  # noqa: T201
                _append_full_run_log_line(config.repo_root, stage_line)
            else:
                stage_line = _prep_stage_line(
                    "hardening",
                    f"attempt {attempt}/{max_attempts}: correction agent failed",
                    "warn",
                    use_color,
                )
                print(stage_line)  # noqa: T201
                _append_full_run_log_line(config.repo_root, stage_line)
            run_log_lines.append(
                f"- Prep agent run {attempt}: {'ok' if agent_ok else 'failed'}"
            )
            run_log_lines.append(
                "- Correction loop: rerunning hardening with updated local issues"
            )
            stage_line = _prep_stage_line(
                "hardening",
                f"attempt {attempt}/{max_attempts}: retrying hardening after correction",
                "start",
                use_color,
            )
            print(stage_line)  # noqa: T201
            _append_full_run_log_line(config.repo_root, stage_line)

    issues_to_close = list(local_issues) + auto_issues
    if hardening_ok and issues_to_close:
        for issue in issues_to_close:
            mark_done(issue)
        run_log_lines.append(f"- Marked {len(issues_to_close)} local issue(s) done")
        stage_line = _prep_stage_line(
            "hardening",
            f"marked {len(issues_to_close)} local issue(s) done",
            "ok",
            use_color,
        )
        print(stage_line)  # noqa: T201
        _append_full_run_log_line(config.repo_root, stage_line)
    elif issues_to_close:
        run_log_lines.append("- Local issues remain open due to hardening failures")
        stage_line = _prep_stage_line(
            "hardening",
            f"{len(issues_to_close)} local issue(s) remain open",
            "warn",
            use_color,
        )
        print(stage_line)  # noqa: T201
        _append_full_run_log_line(config.repo_root, stage_line)

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
    if coverage_below_target:
        print(  # noqa: T201
            "- Coverage is below 70% for one or more projects. "
            "Run `make cover` (or `make cover 70`) to increase and verify coverage."
        )
        run_log_lines.append(
            "- Coverage follow-up: below 70%; run `make cover` or `make cover 70` to improve coverage."
        )
    stage_line = _prep_stage_line(
        "hardening",
        "hardening loop complete" if hardening_ok else "hardening loop failed",
        "ok" if hardening_ok else "fail",
        use_color,
    )
    print(stage_line)  # noqa: T201
    _append_full_run_log_line(config.repo_root, stage_line)
    _append_full_run_log_line(
        config.repo_root, f"=== prep run end ({datetime.now(tz=UTC).isoformat()}) ==="
    )
    run_log_lines.append("- Summary printed to console")

    run_log = write_run_log(
        config.repo_root,
        title="Prep Workflow Run",
        lines=run_log_lines,
    )
    print(f"Prep run log: {run_log.relative_to(config.repo_root)}")  # noqa: T201
    print(f"Prep full-run log: {full_run_log_path.relative_to(config.repo_root)}")  # noqa: T201
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
