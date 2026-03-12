"""Administrative task helpers for HydraFlow server."""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.admin_tasks")

_PREP_COVERAGE_MIN_REQUIRED = 20.0
_PREP_COVERAGE_TARGET = 70.0
_PREP_COVERAGE_STATE_PATH = Path("prep/coverage-floor.json")


@dataclass(slots=True)
class TaskResult:
    """Structured result returned by admin task helpers."""

    success: bool
    log: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "log": self.log,
            "warnings": self.warnings,
        }


def _prep_stage_line(stage: str, detail: str, status: str) -> str:
    """Format a concise prep stage status line (without ANSI color)."""
    glyphs = {
        "start": "\u25b6",
        "ok": "\u2713",
        "warn": "!",
        "fail": "\u2717",
    }
    glyph = glyphs.get(status, ">")
    return f"[prep:{stage}] {glyph} {detail}"


def _seed_context_assets(config: HydraFlowConfig) -> list[str]:
    """Ensure manifest and metrics cache exist after prep."""
    from manifest import ProjectManifestManager  # noqa: PLC0415
    from metrics_manager import get_metrics_cache_dir  # noqa: PLC0415

    log_lines: list[str] = []

    if config.dry_run:
        log_lines.append("- Context seed skipped: dry-run mode")
        return log_lines

    manifest_manager = ProjectManifestManager(config)
    manifest_result = manifest_manager.refresh()
    manifest_rel = config.format_path_for_display(manifest_manager.manifest_path)
    log_lines.append(
        f"- Manifest seed: {manifest_rel} "
        f"(hash={manifest_result.digest_hash}, chars={len(manifest_result.content)})"
    )
    cache_dir = get_metrics_cache_dir(config)
    snapshots_file = cache_dir / "snapshots.jsonl"
    cache_dir.mkdir(parents=True, exist_ok=True)
    snapshots_rel = config.format_path_for_display(snapshots_file)
    if snapshots_file.exists():
        log_lines.append(f"- Metrics cache already existed: {snapshots_rel}")
    else:
        snapshots_file.touch()
        log_lines.append(f"- Metrics cache initialized: {snapshots_rel}")

    return log_lines


def _makefile_has_target(repo_root: Path, target: str) -> bool:
    makefile = repo_root / "Makefile"
    if not makefile.is_file():
        return False
    try:
        content = makefile.read_text()
    except OSError:
        return False
    return any(line.startswith(f"{target}:") for line in content.splitlines())


def _project_has_test_signal(project_root: Path) -> bool:
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


def _extract_coverage_percent(repo_root: Path) -> tuple[float | None, str]:
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
                r"\bline-rate=['\"]([0-9]*\.?[0-9]+)['\"]",
                content,
            )
            if line_rate_match:
                return (
                    float(line_rate_match.group(1)) * 100.0,
                    str(path.relative_to(repo_root)),
                )

            missed = 0
            covered = 0
            for counter in re.finditer(
                r"<counter\b[^>]*\btype=['\"]LINE['\"][^>]*>",
                content,
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


def _evaluate_coverage_validation_projects(
    repo_root: Path,
    project_roots: list[Path],
    *,
    min_required: float = 70.0,
    target: float = 70.0,
    allow_missing_artifact: bool = False,
) -> tuple[bool, bool, str]:
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
    return bool(re.search(r"\d+(?:\.\d+)?% from ", detail))


def _load_prep_coverage_floor(data_root: Path) -> float:
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
    value = float(
        max(_PREP_COVERAGE_MIN_REQUIRED, min(_PREP_COVERAGE_TARGET, min_required))
    )
    state_path = data_root / _PREP_COVERAGE_STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"min_required": value}, indent=2) + "\n", encoding="utf-8"
    )


def _detect_available_prep_tools() -> list[str]:
    tools: list[str] = []
    if shutil.which("claude"):
        tools.append("claude")
    if shutil.which("codex"):
        tools.append("codex")
    if shutil.which("pi"):
        tools.append("pi")
    return tools


def _best_model_for_tool(tool: str) -> str:
    if tool == "claude":
        return "opus"
    if tool == "pi":
        return "gpt-5.3-codex"
    return "gpt-5-codex"


def _choose_prep_tool(configured: str) -> tuple[str | None, str]:
    available = _detect_available_prep_tools()
    if not available:
        return None, "none"
    if len(available) == 1:
        return available[0], "single"

    selected = available[0]
    mode = "fallback"

    if sys.stdin.isatty():  # pragma: no cover - interactive prompt
        default_idx = available.index(configured) if configured in available else 0
        print(f"Prep tools available: {', '.join(available)}")
        options = "  ".join(f"[{i + 1}] {name}" for i, name in enumerate(available))
        choice = input(
            f"Choose prep driver: {options}\nSelection (default {default_idx + 1}): "
        ).strip()
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


def _format_multiline_block(prefix: str, body: str) -> list[str]:
    lines = [line.rstrip() for line in body.splitlines() if line.strip()]
    if not lines:
        return []
    return [f"{prefix}{line}" for line in lines]


async def run_prep(config: HydraFlowConfig) -> TaskResult:
    """Sync HydraFlow lifecycle labels, run repo audit, and seed context assets."""
    from prep import RepoAuditor, ensure_labels  # noqa: PLC0415

    log: list[str] = []
    warnings: list[str] = []

    log.append(_prep_stage_line("labels", "syncing lifecycle labels", "start"))
    result = await ensure_labels(config)
    summary = result.summary()
    log.append(f"[dry-run] {summary}" if config.dry_run else summary)
    if result.failed:
        warnings.append("Label sync completed with failures.")
        log.append(
            _prep_stage_line("labels", "label sync completed with failures", "fail")
        )
    else:
        log.append(_prep_stage_line("labels", "label sync complete", "ok"))

    log.append(_prep_stage_line("audit", "running repository prep audit", "start"))
    audit = await RepoAuditor(config).run_audit()
    log.extend(_format_multiline_block("    ", audit.format_report(color=False)))
    if audit.missing_checks:
        warnings.append("Prep audit detected gaps.")
        log.append(_prep_stage_line("audit", "gaps detected", "warn"))
    else:
        log.append(_prep_stage_line("audit", "all checks passing", "ok"))

    log.append(_prep_stage_line("context", "seeding manifest/memory assets", "start"))
    log.extend(_seed_context_assets(config))

    return TaskResult(success=not result.failed, log=log, warnings=warnings)


async def run_scaffold(config: HydraFlowConfig) -> TaskResult:
    """Quick prep/scaffold of CI/tests plus coverage posture summary."""
    from ci_scaffold import scaffold_ci  # noqa: PLC0415
    from polyglot_prep import (  # noqa: PLC0415
        detect_prep_stack,
        scaffold_tests_polyglot,
    )

    log: list[str] = []
    warnings: list[str] = []

    repo_root = config.repo_root
    stack = detect_prep_stack(repo_root)
    log.append(_prep_stage_line("prep", f"quick prep for stack '{stack}'", "start"))
    selected_tool, selection_mode = _choose_prep_tool(config.implementation_tool)
    if selected_tool:
        selected_model = _best_model_for_tool(selected_tool)
        log.append(
            _prep_stage_line(
                "prep",
                (
                    f"prep driver selected: {selected_tool} "
                    f"({selected_model}; mode={selection_mode})"
                ),
                "ok",
            )
        )
    else:
        log.append(
            _prep_stage_line(
                "prep",
                "no prep driver detected (claude/codex/pi not found in PATH)",
                "warn",
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
        log.append(
            _prep_stage_line(
                "prep",
                (
                    "Well done: CI and baseline tests already exist, and "
                    f"coverage is {coverage_pct:.1f}% ({coverage_source})"
                ),
                "ok",
            )
        )
        return TaskResult(success=True, log=log, warnings=warnings)

    action = "would create" if config.dry_run else "created"
    ci_result = scaffold_ci(repo_root, dry_run=config.dry_run)
    tests_result = scaffold_tests_polyglot(repo_root, dry_run=config.dry_run)

    if ci_result.skipped:
        log.append(f"CI scaffold: skipped ({ci_result.skip_reason})")
    else:
        log.append(
            f"CI scaffold: {action} {ci_result.workflow_path} ({ci_result.language})"
        )

    if tests_result.skipped:
        log.append(f"Test scaffold: skipped ({tests_result.skip_reason})")
        if tests_result.progress:
            log.append(f"Test scaffold progress: {tests_result.progress}")
    else:
        created_dirs = ", ".join(tests_result.created_dirs) or "-"
        created_files = ", ".join(tests_result.created_files) or "-"
        modified_files = ", ".join(tests_result.modified_files) or "-"
        log.append(
            "Test scaffold: "
            f"{action} dirs [{created_dirs}] files [{created_files}] "
            f"modified [{modified_files}] ({tests_result.language})"
        )
        if tests_result.progress:
            log.append(f"Test scaffold progress: {tests_result.progress}")

    coverage_pct, coverage_source = _extract_coverage_percent(repo_root)
    log.append("Prep summary:")
    log.append(f"- Stack: {stack}")
    log.append(f"- CI scaffold: {'skipped' if ci_result.skipped else action}")
    log.append(f"- Test scaffold: {'skipped' if tests_result.skipped else action}")
    if coverage_pct is None:
        log.append(
            _prep_stage_line(
                "scaffold", "Coverage: no report artifact found yet.", "warn"
            )
        )
        log.append(
            _prep_stage_line(
                "scaffold",
                "Next: run `make cover` (70% unit coverage) and `make smoke`.",
                "warn",
            )
        )
        warnings.append("Coverage artifact missing.")
    elif coverage_pct < _PREP_COVERAGE_TARGET:
        log.append(
            _prep_stage_line(
                "scaffold",
                f"Coverage: {coverage_pct:.1f}% from {coverage_source} (below 70%).",
                "warn",
            )
        )
        log.append(
            _prep_stage_line(
                "scaffold",
                "Next: run `make cover` (70% unit coverage) and `make smoke`.",
                "warn",
            )
        )
        warnings.append("Coverage below target threshold.")
    else:
        log.append(
            _prep_stage_line(
                "scaffold",
                f"Coverage: {coverage_pct:.1f}% from {coverage_source} (>= 70%).",
                "ok",
            )
        )
        log.append(
            _prep_stage_line(
                "scaffold",
                "Well done: coverage is already healthy.",
                "ok",
            )
        )

    return TaskResult(success=True, log=log, warnings=warnings)


async def run_ensure_labels(config: HydraFlowConfig) -> TaskResult:
    """Sync HydraFlow lifecycle labels only (no repo audit or context seeding)."""
    from prep import ensure_labels  # noqa: PLC0415

    log: list[str] = []
    warnings: list[str] = []

    log.append(_prep_stage_line("labels", "syncing lifecycle labels", "start"))
    result = await ensure_labels(config)
    summary = result.summary()
    log.append(f"[dry-run] {summary}" if config.dry_run else summary)
    if result.failed:
        warnings.append("Label sync completed with failures.")
        log.append(
            _prep_stage_line("labels", "label sync completed with failures", "fail")
        )
    else:
        log.append(_prep_stage_line("labels", "label sync complete", "ok"))

    return TaskResult(success=not result.failed, log=log, warnings=warnings)


async def run_clean(config: HydraFlowConfig) -> TaskResult:
    """Remove all worktrees and reset state."""
    from state import StateTracker  # noqa: PLC0415
    from workspace import WorkspaceManager  # noqa: PLC0415

    log = ["Cleaning up all HydraFlow worktrees and state..."]

    wt_mgr = WorkspaceManager(config)
    await wt_mgr.destroy_all()

    state = StateTracker(config.state_file)
    state.reset()

    log.append("Cleanup complete")
    return TaskResult(success=True, log=log)


__all__ = [
    "TaskResult",
    "run_clean",
    "run_ensure_labels",
    "run_prep",
    "run_scaffold",
]
