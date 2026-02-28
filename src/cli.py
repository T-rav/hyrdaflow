"""CLI entry point for HydraFlow."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import signal
import sys
from pathlib import Path
from typing import Any

from config import HydraFlowConfig, load_config_file
from file_util import atomic_write
from log import setup_logging
from orchestrator import HydraFlowOrchestrator

_PREP_COVERAGE_MIN_REQUIRED = 20.0
_PREP_COVERAGE_TARGET = 70.0
_SEEDED_DIGEST_PLACEHOLDER = (
    "## Accumulated Learnings\n"
    "*Seeded during prep; no learnings yet.*\n\n"
    "HydraFlow will update this digest after the first memory sync.\n"
)
_PREP_COVERAGE_STATE_PATH = Path("prep/coverage-floor.json")


def _default_data_root_path() -> Path:
    """Return the default data root based on HYDRAFLOW_HOME or local .hydraflow."""
    env_home = os.environ.get("HYDRAFLOW_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser()
    return Path(".hydraflow")


def _default_config_file() -> str:
    """Return the default config file path under the data root."""
    return str(_default_data_root_path() / "config.json")


def _default_log_file() -> str:
    """Return the default structured log file path under the data root."""
    return str(_default_data_root_path() / "logs" / "hydraflow.log")


_DEFAULT_CONFIG_PATH = _default_config_file()
_DEFAULT_LOG_FILE = _default_log_file()


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


def _seed_context_assets(config: HydraFlowConfig) -> list[str]:
    """Ensure manifest, memory digest, and metrics cache exist after prep."""
    from manifest import ProjectManifestManager  # noqa: PLC0415
    from metrics_manager import get_metrics_cache_dir  # noqa: PLC0415

    log_lines: list[str] = []

    if config.dry_run:
        print("Context seed: skipped (dry-run)")  # noqa: T201
        log_lines.append("- Context seed skipped: dry-run mode")
        return log_lines

    manifest_manager = ProjectManifestManager(config)
    manifest_result = manifest_manager.refresh()
    manifest_rel = config.format_path_for_display(manifest_manager.manifest_path)
    print(  # noqa: T201
        f"Manifest seed: wrote {manifest_rel} "
        f"(hash={manifest_result.digest_hash}, chars={len(manifest_result.content)})"
    )
    log_lines.append(
        f"- Manifest seed: {manifest_rel} "
        f"(hash={manifest_result.digest_hash}, chars={len(manifest_result.content)})"
    )
    legacy_manifest_path = config.data_path("memory", "manifest.md")
    if not legacy_manifest_path.exists():
        atomic_write(legacy_manifest_path, manifest_result.content)

    digest_path = config.data_path("memory", "digest.md")
    digest_rel = config.format_path_for_display(digest_path)
    if digest_path.exists():
        print(f"Memory digest already exists: {digest_rel}")  # noqa: T201
        log_lines.append(f"- Memory digest already existed: {digest_rel}")
    else:
        atomic_write(digest_path, _SEEDED_DIGEST_PLACEHOLDER)
        print(f"Memory digest seeded: {digest_rel}")  # noqa: T201
        log_lines.append(f"- Memory digest seeded: {digest_rel}")

    cache_dir = get_metrics_cache_dir(config)
    snapshots_file = cache_dir / "snapshots.jsonl"
    cache_dir.mkdir(parents=True, exist_ok=True)
    snapshots_rel = config.format_path_for_display(snapshots_file)
    if snapshots_file.exists():
        print(f"Metrics cache already exists: {snapshots_rel}")  # noqa: T201
        log_lines.append(f"- Metrics cache already existed: {snapshots_rel}")
    else:
        snapshots_file.touch()
        print(f"Metrics cache initialized: {snapshots_rel}")  # noqa: T201
        log_lines.append(f"- Metrics cache initialized: {snapshots_rel}")

    return log_lines


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
        help="Max concurrent implementation agents (default: 2)",
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
        help="Max concurrent review agents (default: 2)",
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
        "--system-tool",
        default=None,
        choices=["inherit", "claude", "codex", "pi"],
        help="Global default tool for system agents; per-agent explicit settings still win (default: inherit)",
    )
    parser.add_argument(
        "--system-model",
        default=None,
        help="Global default model for system agents; per-agent explicit settings still win",
    )
    parser.add_argument(
        "--background-tool",
        default=None,
        choices=["inherit", "claude", "codex", "pi"],
        help="Global default tool for background workers; per-worker explicit settings still win (default: inherit)",
    )
    parser.add_argument(
        "--background-model",
        default=None,
        help="Global default model for background workers; per-worker explicit settings still win",
    )
    parser.add_argument(
        "--implementation-tool",
        default=None,
        choices=["claude", "codex", "pi"],
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
        choices=["claude", "codex", "pi"],
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
        "--transcript-label",
        default=None,
        help="Labels for transcript-summary issues queued for memory sync, comma-separated (default: hydraflow-transcript)",
    )
    parser.add_argument(
        "--manifest-label",
        default=None,
        help="Labels for manifest persistence issues, comma-separated (default: hydraflow-manifest)",
    )
    parser.add_argument(
        "--memory-sync-interval",
        type=int,
        default=None,
        help="Seconds between memory sync polls (default: 3600)",
    )
    parser.add_argument(
        "--memory-compaction-tool",
        default=None,
        choices=["claude", "codex", "pi"],
        help="CLI backend for memory digest compaction (default: claude)",
    )
    parser.add_argument(
        "--memory-compaction-model",
        default=None,
        help="Model for memory digest compaction (default: haiku)",
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
        "--epic-child-label",
        default=None,
        help="Labels for epic child issues, comma-separated (default: hydraflow-epic-child)",
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
        choices=["claude", "codex", "pi"],
        help="CLI backend for planning agents (default: claude)",
    )
    parser.add_argument(
        "--triage-tool",
        default=None,
        choices=["claude", "codex", "pi"],
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
        choices=["claude", "codex", "pi"],
        help="CLI backend for acceptance criteria generation (default: claude)",
    )
    parser.add_argument(
        "--verification-judge-tool",
        default=None,
        choices=["claude", "codex", "pi"],
        help="CLI backend for verification judge (default: claude)",
    )
    parser.add_argument(
        "--transcript-summary-tool",
        default=None,
        choices=["claude", "codex", "pi"],
        help="CLI backend for transcript summarization (default: claude)",
    )
    parser.add_argument(
        "--transcript-summary-model",
        default=None,
        help="Model for transcript summarization (default: haiku)",
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
        help=f"Path to JSON config file for persisting runtime changes (default: {_DEFAULT_CONFIG_PATH})",
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
        default=_DEFAULT_LOG_FILE,
        help=f"Path to log file for structured JSON logging (default: {_DEFAULT_LOG_FILE})",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove all worktrees and state, then exit",
    )
    parser.add_argument(
        "--prep",
        action="store_true",
        help="Run quick prep/scaffold (CI + baseline tests + coverage guidance), then exit",
    )
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help="Alias for --prep (quick prep/scaffold), then exit",
    )
    parser.add_argument(
        "--ensure-labels",
        action="store_true",
        help="Create HydraFlow lifecycle labels on the target repo, then exit",
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

    config_file_path = getattr(args, "config_file", None) or _DEFAULT_CONFIG_PATH
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
        "system_tool",
        "system_model",
        "background_tool",
        "background_model",
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
        "memory_compaction_tool",
        "memory_compaction_model",
        "metrics_sync_interval",
        "transcript_summary_tool",
        "transcript_summary_model",
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
        "transcript_label",
        "manifest_label",
        "metrics_label",
        "epic_label",
        "epic_child_label",
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
    """Sync HydraFlow lifecycle labels and run the repo audit.

    Returns ``True`` if label sync had no failures,
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


def _prep_coverage_has_measurement(detail: str) -> bool:
    """Return True when coverage detail includes at least one measured percentage."""
    return bool(re.search(r"\d+(?:\.\d+)?% from ", detail))


def _load_prep_coverage_floor(data_root: Path) -> float:
    """Load persisted prep coverage minimum floor for ratcheting."""
    state_path = data_root / _PREP_COVERAGE_STATE_PATH
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


def _save_prep_coverage_floor(data_root: Path, min_required: float) -> None:
    """Persist prep coverage minimum floor for future runs."""
    value = float(
        max(_PREP_COVERAGE_MIN_REQUIRED, min(_PREP_COVERAGE_TARGET, min_required))
    )
    state_path = data_root / _PREP_COVERAGE_STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"min_required": value}, indent=2) + "\n", encoding="utf-8"
    )


def _detect_available_prep_tools() -> list[str]:
    """Detect available local prep agent CLIs."""
    tools: list[str] = []
    if shutil.which("claude"):
        tools.append("claude")
    if shutil.which("codex"):
        tools.append("codex")
    if shutil.which("pi"):
        tools.append("pi")
    return tools


def _best_model_for_tool(tool: str) -> str:
    """Return best default model for the selected tool."""
    if tool == "claude":
        return "opus"
    if tool == "pi":
        return "gpt-5.3-codex"
    return "gpt-5-codex"


def _choose_prep_tool(configured: str) -> tuple[str | None, str]:
    """Choose prep tool from local availability, prompting when both exist."""
    available = _detect_available_prep_tools()
    if not available:
        return None, "none"
    if len(available) == 1:
        return available[0], "single"

    selected = available[0]
    mode = "fallback"

    # Multiple tools installed.
    if sys.stdin.isatty():
        default_idx = available.index(configured) if configured in available else 0
        print(f"Prep tools available: {', '.join(available)}")  # noqa: T201
        options = "  ".join(f"[{i + 1}] {name}" for i, name in enumerate(available))
        print(f"Choose prep driver: {options}")  # noqa: T201
        choice = input(f"Selection (default {default_idx + 1}): ").strip()  # noqa: T201
        selected = available[default_idx]
        mode = "prompt"
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(available):
                selected = available[idx]
    elif configured in available:
        selected = configured
        mode = "configured"
    return selected, mode


async def _run_scaffold(config: HydraFlowConfig) -> bool:
    """Fast prep: scaffold CI/tests only when missing, then report coverage posture."""
    from ci_scaffold import scaffold_ci  # noqa: PLC0415
    from polyglot_prep import (  # noqa: PLC0415
        detect_prep_stack,
        scaffold_tests_polyglot,
    )

    use_color = _supports_color_output()
    repo_root = config.repo_root
    stack = detect_prep_stack(repo_root)
    print(
        _prep_stage_line("prep", f"quick prep for stack '{stack}'", "start", use_color)
    )  # noqa: T201
    selected_tool, selection_mode = _choose_prep_tool(config.implementation_tool)
    if selected_tool:
        selected_model = _best_model_for_tool(selected_tool)
        print(  # noqa: T201
            _prep_stage_line(
                "prep",
                (
                    f"prep driver selected: {selected_tool} "
                    f"({selected_model}; mode={selection_mode})"
                ),
                "ok",
                use_color,
            )
        )
    else:
        print(  # noqa: T201
            _prep_stage_line(
                "prep",
                "no prep driver detected (claude/codex/pi not found in PATH)",
                "warn",
                use_color,
            )
        )

    ci_probe = scaffold_ci(repo_root, dry_run=True)
    tests_probe = scaffold_tests_polyglot(repo_root, dry_run=True)
    coverage_pct, coverage_source = _extract_coverage_percent(repo_root)

    if (
        ci_probe.skipped
        and tests_probe.skipped
        and coverage_pct is not None
        and coverage_pct >= _PREP_COVERAGE_TARGET
    ):
        print(  # noqa: T201
            _prep_stage_line(
                "prep",
                (
                    "Well done: CI and baseline tests already exist, and "
                    f"coverage is {coverage_pct:.1f}% ({coverage_source})"
                ),
                "ok",
                use_color,
            )
        )
        return True

    action = "would create" if config.dry_run else "created"
    ci_result = scaffold_ci(repo_root, dry_run=config.dry_run)
    tests_result = scaffold_tests_polyglot(repo_root, dry_run=config.dry_run)

    if ci_result.skipped:
        print(f"CI scaffold: skipped ({ci_result.skip_reason})")  # noqa: T201
    else:
        print(  # noqa: T201
            f"CI scaffold: {action} {ci_result.workflow_path} ({ci_result.language})"
        )

    if tests_result.skipped:
        print(f"Test scaffold: skipped ({tests_result.skip_reason})")  # noqa: T201
        if tests_result.progress:
            print(f"Test scaffold progress: {tests_result.progress}")  # noqa: T201
    else:
        created_dirs = ", ".join(tests_result.created_dirs) or "-"
        created_files = ", ".join(tests_result.created_files) or "-"
        modified_files = ", ".join(tests_result.modified_files) or "-"
        print(  # noqa: T201
            "Test scaffold: "
            f"{action} dirs [{created_dirs}] files [{created_files}] "
            f"modified [{modified_files}] ({tests_result.language})"
        )
        if tests_result.progress:
            print(f"Test scaffold progress: {tests_result.progress}")  # noqa: T201

    coverage_pct, coverage_source = _extract_coverage_percent(repo_root)
    print("Prep summary:")  # noqa: T201
    print(f"- Stack: {stack}")  # noqa: T201
    print(f"- CI scaffold: {'skipped' if ci_result.skipped else action}")  # noqa: T201
    print(f"- Test scaffold: {'skipped' if tests_result.skipped else action}")  # noqa: T201
    if coverage_pct is None:
        print(  # noqa: T201
            _prep_stage_line(
                "scaffold", "Coverage: no report artifact found yet.", "warn", use_color
            )
        )
        print(  # noqa: T201
            _prep_stage_line(
                "scaffold",
                "Next: run `make cover` (70% unit coverage) and `make smoke`.",
                "warn",
                use_color,
            )
        )
    elif coverage_pct < _PREP_COVERAGE_TARGET:
        print(  # noqa: T201
            _prep_stage_line(
                "scaffold",
                f"Coverage: {coverage_pct:.1f}% from {coverage_source} (below 70%).",
                "warn",
                use_color,
            )
        )
        print(  # noqa: T201
            _prep_stage_line(
                "scaffold",
                "Next: run `make cover` (70% unit coverage) and `make smoke`.",
                "warn",
                use_color,
            )
        )
    else:
        print(  # noqa: T201
            _prep_stage_line(
                "scaffold",
                f"Coverage: {coverage_pct:.1f}% from {coverage_source} (>= 70%).",
                "ok",
                use_color,
            )
        )
        print(  # noqa: T201
            _prep_stage_line(
                "scaffold",
                "Well done: coverage is already healthy.",
                "ok",
                use_color,
            )
        )

    return True


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

    if args.ensure_labels:
        success = asyncio.run(_run_prep(config))
        sys.exit(0 if success else 1)

    if args.prep or args.scaffold:
        success = asyncio.run(_run_scaffold(config))
        sys.exit(0 if success else 1)

    if args.audit:
        has_gaps = asyncio.run(_run_audit(config))
        sys.exit(1 if has_gaps else 0)

    if args.clean:
        asyncio.run(_run_clean(config))
        sys.exit(0)

    if args.replay is not None:
        _run_replay(config, args.replay, args.replay_latest)
        sys.exit(0)

    asyncio.run(_run_main(config))


if __name__ == "__main__":
    main()
