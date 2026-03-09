"""Repository preparation — create HydraFlow lifecycle labels and audit repo."""

from __future__ import annotations

import json
import logging
import re
import tomllib
from dataclasses import dataclass, field

from config import HydraFlowConfig
from models import AuditCheck, AuditCheckStatus, AuditResult
from subprocess_util import run_subprocess, run_subprocess_with_retry

logger = logging.getLogger("hydraflow.prep")

# Authoritative HydraFlow lifecycle label table: (config_field, color, description)
HYDRAFLOW_LABELS: tuple[tuple[str, str, str], ...] = (
    ("find_label", "e4e669", "New issue for HydraFlow to discover and triage"),
    ("planner_label", "c5def5", "Issue needs planning before implementation"),
    ("ready_label", "0e8a16", "Issue ready for implementation"),
    ("review_label", "fbca04", "Issue/PR under review"),
    ("hitl_label", "d93f0b", "Escalated to human-in-the-loop"),
    ("hitl_active_label", "e99695", "Being processed by HITL correction agent"),
    ("fixed_label", "0075ca", "PR merged — issue completed"),
    ("improve_label", "7057ff", "Review insight improvement proposal"),
    ("memory_label", "1d76db", "Approved memory suggestion for sync"),
    ("transcript_label", "bfd4f2", "Transcript summary issue for memory ingestion"),
    ("metrics_label", "006b75", "Metrics persistence issue"),
    ("manifest_label", "1185fe", "Manifest persistence issue"),
    ("dup_label", "cfd3d7", "Issue already satisfied — no changes needed"),
    ("epic_label", "5319e7", "Epic tracking issue with linked sub-issues"),
    ("epic_child_label", "9b59b6", "Child issue linked to a HydraFlow epic"),
)


@dataclass
class PrepResult:
    """Outcome of a label-preparation run."""

    created: list[str] = field(default_factory=list)
    existed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary line."""
        n_created = len(self.created)
        n_existed = len(self.existed)
        label_word = "label" if n_created == 1 else "labels"
        parts = [f"Created {n_created} {label_word}, {n_existed} already existed"]
        if self.failed:
            parts.append(f", {len(self.failed)} failed")
        return "".join(parts)


async def _list_existing_labels(config: HydraFlowConfig) -> set[str]:
    """Query the repo for existing label names."""
    try:
        raw = await run_subprocess_with_retry(
            "gh",
            "label",
            "list",
            "--repo",
            config.repo,
            "--json",
            "name",
            "--limit",
            "1000",  # well above any realistic HydraFlow-managed label count
            cwd=config.repo_root,
            gh_token=config.gh_token,
            max_retries=config.gh_max_retries,
        )
        return {entry["name"] for entry in json.loads(raw)}
    except (RuntimeError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("Could not list existing labels: %s", exc)
        return set()


async def ensure_labels(config: HydraFlowConfig) -> PrepResult:
    """Create all HydraFlow lifecycle labels on the target repo.

    Uses ``gh label create --force`` which creates or updates each label.
    Returns a :class:`PrepResult` with created/existed/failed lists.
    """
    result = PrepResult()

    if config.dry_run:
        for cfg_field, _color, _desc in HYDRAFLOW_LABELS:
            for name in getattr(config, cfg_field):
                result.created.append(name)
        logger.info("[dry-run] Would create labels: %s", result.created)
        return result

    existing = await _list_existing_labels(config)

    for cfg_field, color, description in HYDRAFLOW_LABELS:
        label_names: list[str] = getattr(config, cfg_field)
        for label_name in label_names:
            try:
                await run_subprocess_with_retry(
                    "gh",
                    "label",
                    "create",
                    label_name,
                    "--repo",
                    config.repo,
                    "--color",
                    color,
                    "--description",
                    description,
                    "--force",
                    cwd=config.repo_root,
                    gh_token=config.gh_token,
                    max_retries=config.gh_max_retries,
                )
                if label_name in existing:
                    result.existed.append(label_name)
                    logger.debug("Label %r already existed (updated)", label_name)
                else:
                    result.created.append(label_name)
                    logger.info("Created label %r", label_name)
            except RuntimeError as exc:
                result.failed.append(label_name)
                logger.warning("Could not create label %r: %s", label_name, exc)

    return result


# ---------------------------------------------------------------------------
# Repo audit logic
# ---------------------------------------------------------------------------

# Makefile targets HydraFlow requires
_REQUIRED_MAKE_TARGETS = (
    "lint",
    "lint-check",
    "lint-fix",
    "typecheck",
    "security",
    "test",
    "coverage-check",
    "quality-lite",
    "quality",
)

_COVERAGE_MIN_THRESHOLD = 70.0
_COVERAGE_TARGET_THRESHOLD = 70.0

# Lock files mapped to package manager names
_LOCK_FILES: tuple[tuple[str, str], ...] = (
    ("uv.lock", "uv"),
    ("pnpm-lock.yaml", "pnpm"),
    ("package-lock.json", "npm"),
    ("yarn.lock", "yarn"),
    ("poetry.lock", "poetry"),
)

# Config label fields on HydraFlowConfig that map to HydraFlow lifecycle labels
_LABEL_FIELDS: tuple[str, ...] = (
    "find_label",
    "planner_label",
    "ready_label",
    "review_label",
    "hitl_label",
    "hitl_active_label",
    "fixed_label",
    "improve_label",
    "memory_label",
    "transcript_label",
    "metrics_label",
    "dup_label",
    "epic_label",
    "epic_child_label",
)


class RepoAuditor:
    """Scans a repository for infrastructure HydraFlow depends on."""

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._root = config.repo_root

    async def run_audit(self) -> AuditResult:
        """Run all audit checks and return the result."""
        checks = [
            self._check_language(),
            self._check_makefile(),
            self._check_ci(),
            self._check_git_hooks(),
            self._check_linting(),
            self._check_type_checking(),
            self._check_test_framework(),
            self._check_coverage_policy(),
            self._check_package_manager(),
            self._check_agents_md(),
            await self._check_gh_cli(),
            await self._check_labels(),
        ]
        return AuditResult(repo=self._config.repo, checks=checks)

    # -- Sync checks ----------------------------------------------------------

    def _check_language(self) -> AuditCheck:
        """Detect Python and/or JS/TS markers."""
        python_markers = ("pyproject.toml", "setup.py", "requirements.txt")
        js_markers = ("package.json", "tsconfig.json")

        found_python = False
        python_detail = ""
        for marker in python_markers:
            if (self._root / marker).is_file():
                found_python = True
                python_detail = f"Python ({marker})"
                if marker == "pyproject.toml":
                    version = self._extract_python_version()
                    if version:
                        python_detail = f"Python {version} ({marker})"
                break

        found_js = False
        js_detail = ""
        for marker in js_markers:
            if (self._root / marker).is_file():
                found_js = True
                js_detail = f"JS/TS ({marker})"
                break

        if found_python and found_js:
            return AuditCheck(
                name="Language",
                status=AuditCheckStatus.PRESENT,
                detail=f"{python_detail} + {js_detail}",
            )
        if found_python:
            return AuditCheck(
                name="Language",
                status=AuditCheckStatus.PRESENT,
                detail=python_detail,
            )
        if found_js:
            return AuditCheck(
                name="Language",
                status=AuditCheckStatus.PRESENT,
                detail=js_detail,
            )
        return AuditCheck(
            name="Language",
            status=AuditCheckStatus.MISSING,
            detail="no language markers found",
        )

    def _extract_python_version(self) -> str:
        """Extract requires-python version from pyproject.toml."""
        try:
            data = tomllib.loads((self._root / "pyproject.toml").read_text())
            version_str = data.get("project", {}).get("requires-python", "")
            if version_str:
                # Extract version number from specifier like ">=3.11"
                match = re.search(r"(\d+\.\d+)", version_str)
                if match:
                    return match.group(1)
        except (OSError, tomllib.TOMLDecodeError, KeyError):
            pass
        return ""

    def _check_makefile(self) -> AuditCheck:
        """Check for Makefile and required targets."""
        makefile = self._root / "Makefile"
        if not makefile.is_file():
            return AuditCheck(
                name="Makefile",
                status=AuditCheckStatus.MISSING,
                detail="no Makefile",
                critical=True,
            )

        try:
            content = makefile.read_text()
        except OSError:
            return AuditCheck(
                name="Makefile",
                status=AuditCheckStatus.MISSING,
                detail="could not read Makefile",
                critical=True,
            )

        missing: list[str] = []
        for target in _REQUIRED_MAKE_TARGETS:
            if not re.search(rf"^{target}\s*:", content, re.MULTILINE):
                missing.append(target)

        if not missing:
            return AuditCheck(
                name="Makefile",
                status=AuditCheckStatus.PRESENT,
                detail="all targets",
                critical=True,
            )
        return AuditCheck(
            name="Makefile",
            status=AuditCheckStatus.PARTIAL,
            detail=f"missing: {', '.join(missing)}",
            critical=True,
        )

    def _check_ci(self) -> AuditCheck:
        """Check for GitHub Actions CI workflows."""
        wf_dir = self._root / ".github" / "workflows"
        if not wf_dir.is_dir():
            return AuditCheck(
                name="CI",
                status=AuditCheckStatus.MISSING,
                detail="no .github/workflows/",
                critical=True,
            )

        wf_files = list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))
        if not wf_files:
            return AuditCheck(
                name="CI",
                status=AuditCheckStatus.MISSING,
                detail="no workflow files",
                critical=True,
            )

        # Check if any workflow triggers on push or pull_request.
        # Match "push:" or "pull_request:" as YAML keys to avoid false positives
        # from step names like "Push Docker image" or run commands like "git push".
        _trigger_re = re.compile(r"\bpush\s*:|pull_request\s*:")
        for wf_file in wf_files:
            try:
                content = wf_file.read_text()
                if _trigger_re.search(content):
                    return AuditCheck(
                        name="CI",
                        status=AuditCheckStatus.PRESENT,
                        detail=f"{len(wf_files)} workflow(s)",
                        critical=True,
                    )
            except OSError:
                continue

        return AuditCheck(
            name="CI",
            status=AuditCheckStatus.PARTIAL,
            detail="workflows exist but no push/PR trigger",
            critical=True,
        )

    def _check_git_hooks(self) -> AuditCheck:
        """Check for git hooks (pre-commit)."""
        hook_dirs = [".githooks", ".husky"]
        for hook_dir_name in hook_dirs:
            hook_dir = self._root / hook_dir_name
            if hook_dir.is_dir() and (hook_dir / "pre-commit").is_file():
                return AuditCheck(
                    name="Git hooks",
                    status=AuditCheckStatus.PRESENT,
                    detail=f"{hook_dir_name}/pre-commit",
                )

        git_hook = self._root / ".git" / "hooks" / "pre-commit"
        if git_hook.is_file():
            return AuditCheck(
                name="Git hooks",
                status=AuditCheckStatus.PRESENT,
                detail=".git/hooks/pre-commit",
            )

        return AuditCheck(
            name="Git hooks",
            status=AuditCheckStatus.MISSING,
            detail="no pre-commit hook",
        )

    def _check_linting(self) -> AuditCheck:
        """Check for linting configuration."""
        tools: list[str] = []

        # Capability-based checks first (language-agnostic entry points).
        makefile = self._root / "Makefile"
        if makefile.is_file():
            try:
                content = makefile.read_text()
                if re.search(r"^lint(-check)?\s*:", content, re.MULTILINE):
                    tools.append("make lint target")
            except OSError:
                pass

        package_json = self._root / "package.json"
        if package_json.is_file():
            try:
                data = json.loads(package_json.read_text())
                scripts = data.get("scripts", {})
                if isinstance(scripts, dict) and any(
                    key in scripts for key in ("lint", "lint:check")
                ):
                    tools.append("npm lint script")
            except (OSError, json.JSONDecodeError):
                pass

        if (self._root / "ruff.toml").is_file():
            tools.append("ruff")
        elif (self._root / "pyproject.toml").is_file():
            try:
                data = tomllib.loads((self._root / "pyproject.toml").read_text())
                if "ruff" in data.get("tool", {}):
                    tools.append("ruff")
            except (OSError, tomllib.TOMLDecodeError):
                pass

        # Check for JS/TS linters
        for name in (".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.yml"):
            if (self._root / name).is_file():
                tools.append("eslint")
                break
        if "eslint" not in tools:
            for name in ("eslint.config.js", "eslint.config.cjs", "eslint.config.mjs"):
                if (self._root / name).is_file():
                    tools.append("eslint")
                    break

        if (self._root / "biome.json").is_file():
            tools.append("biome")

        if tools:
            tools = list(dict.fromkeys(tools))
            return AuditCheck(
                name="Linting",
                status=AuditCheckStatus.PRESENT,
                detail=", ".join(tools),
            )
        return AuditCheck(
            name="Linting",
            status=AuditCheckStatus.MISSING,
            detail="no linting config",
        )

    def _check_type_checking(self) -> AuditCheck:
        """Check for type checking configuration."""
        tools: list[str] = []

        if (self._root / "pyrightconfig.json").is_file():
            tools.append("pyright")
        elif (self._root / "pyproject.toml").is_file():
            try:
                data = tomllib.loads((self._root / "pyproject.toml").read_text())
                if "pyright" in data.get("tool", {}):
                    tools.append("pyright")
            except (OSError, tomllib.TOMLDecodeError):
                pass

        if (self._root / "tsconfig.json").is_file():
            tools.append("tsconfig")

        if tools:
            return AuditCheck(
                name="Type check",
                status=AuditCheckStatus.PRESENT,
                detail=", ".join(tools),
            )
        return AuditCheck(
            name="Type check",
            status=AuditCheckStatus.MISSING,
            detail="no type checking config",
        )

    def _check_test_framework(self) -> AuditCheck:
        """Check for test framework configuration and test files."""
        tools: list[str] = []
        test_count = 0

        # Python test dirs
        tests_dir = self._root / "tests"
        if tests_dir.is_dir():
            test_files = list(tests_dir.rglob("test_*.py"))
            test_count += len(test_files)
            if (
                (self._root / "conftest.py").is_file()
                or (tests_dir / "conftest.py").is_file()
                or test_files
            ):
                tools.append("pytest")

        # Check for pytest.ini or pyproject.toml [tool.pytest]
        if not tools:
            if (self._root / "pytest.ini").is_file():
                tools.append("pytest")
            elif (self._root / "pyproject.toml").is_file():
                try:
                    data = tomllib.loads((self._root / "pyproject.toml").read_text())
                    if "pytest" in data.get("tool", {}):
                        tools.append("pytest")
                except (OSError, tomllib.TOMLDecodeError):
                    pass

        # JS/TS test dirs
        js_tests_dir = self._root / "__tests__"
        if js_tests_dir.is_dir():
            js_test_files = list(js_tests_dir.rglob("*.test.*"))
            test_count += len(js_test_files)
            if not any(t in tools for t in ("vitest", "jest")):
                tools.append("jest")

        # Check for vitest/jest config files
        for name in ("vitest.config.ts", "vitest.config.js", "vitest.config.mts"):
            if (self._root / name).is_file():
                if "jest" in tools:
                    tools.remove("jest")
                tools.append("vitest")
                break

        for name in ("jest.config.ts", "jest.config.js", "jest.config.json"):
            if (self._root / name).is_file():
                if "jest" not in tools:
                    tools.append("jest")
                break

        if tools:
            detail = ", ".join(tools)
            if test_count > 0:
                detail += f" ({test_count} test file{'s' if test_count != 1 else ''})"
            return AuditCheck(
                name="Tests",
                status=AuditCheckStatus.PRESENT,
                detail=detail,
            )
        return AuditCheck(
            name="Tests",
            status=AuditCheckStatus.MISSING,
            detail="no test framework detected",
        )

    def _check_package_manager(self) -> AuditCheck:
        """Check for package manager lock files."""
        for filename, manager_name in _LOCK_FILES:
            if (self._root / filename).is_file():
                return AuditCheck(
                    name="Pkg manager",
                    status=AuditCheckStatus.PRESENT,
                    detail=manager_name,
                )
        return AuditCheck(
            name="Pkg manager",
            status=AuditCheckStatus.MISSING,
            detail="no lock file",
        )

    def _check_coverage_policy(self) -> AuditCheck:
        """Check whether an enforceable coverage threshold policy is configured."""
        thresholds: list[tuple[str, float]] = []
        policy_targets: list[tuple[str, float]] = []

        pyproject = self._root / "pyproject.toml"
        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text())
                fail_under = (
                    data.get("tool", {})
                    .get("coverage", {})
                    .get("report", {})
                    .get("fail_under")
                )
                if isinstance(fail_under, (int, float)):
                    thresholds.append(
                        ("pyproject:coverage.fail_under", float(fail_under))
                    )
            except (OSError, tomllib.TOMLDecodeError):
                pass

        coveragerc = self._root / ".coveragerc"
        if coveragerc.is_file():
            try:
                content = coveragerc.read_text()
                match = re.search(
                    r"^\s*fail_under\s*=\s*(\d+(?:\.\d+)?)\s*$",
                    content,
                    re.MULTILINE,
                )
                if match:
                    thresholds.append((".coveragerc:fail_under", float(match.group(1))))
            except OSError:
                pass

        for filename in ("Makefile", "makefile", "GNUmakefile"):
            path = self._root / filename
            if not path.is_file():
                continue
            try:
                content = path.read_text()
                for val in re.findall(
                    r"^\s*COVERAGE_MIN\s*\??=\s*(\d+(?:\.\d+)?)\s*$",
                    content,
                    re.MULTILINE,
                ):
                    thresholds.append((f"{filename}:COVERAGE_MIN", float(val)))
                for val in re.findall(
                    r"^\s*COVERAGE_TARGET\s*\??=\s*(\d+(?:\.\d+)?)\s*$",
                    content,
                    re.MULTILINE,
                ):
                    policy_targets.append((f"{filename}:COVERAGE_TARGET", float(val)))
                for val in re.findall(
                    r"--cov-fail-under(?:=|\s+)(\d+(?:\.\d+)?)",
                    content,
                ):
                    thresholds.append((f"{filename}:--cov-fail-under", float(val)))
            except OSError:
                continue

        package_json = self._root / "package.json"
        if package_json.is_file():
            try:
                data = json.loads(package_json.read_text())
                threshold = (
                    data.get("jest", {})
                    .get("coverageThreshold", {})
                    .get("global", {})
                    .get("lines")
                )
                if isinstance(threshold, (int, float)):
                    thresholds.append(
                        ("package.json:jest.global.lines", float(threshold))
                    )
            except (OSError, json.JSONDecodeError):
                pass

        if not thresholds:
            return AuditCheck(
                name="Coverage",
                status=AuditCheckStatus.PARTIAL,
                detail=(
                    "no enforced coverage threshold detected; "
                    "set minimum 70% and target 70%+"
                ),
            )

        min_source, min_threshold = min(thresholds, key=lambda item: item[1])
        if min_threshold < _COVERAGE_MIN_THRESHOLD:
            return AuditCheck(
                name="Coverage",
                status=AuditCheckStatus.PARTIAL,
                detail=(
                    f"{min_source}={min_threshold:g}% below minimum 70%; "
                    "increase threshold to >=70%"
                ),
            )

        target_suffix = ""
        if policy_targets:
            _target_source, target_threshold = min(
                policy_targets, key=lambda item: item[1]
            )
            if target_threshold < _COVERAGE_TARGET_THRESHOLD:
                target_suffix = f"; warning: target is {target_threshold:g}% (<70%)"

        if min_threshold < _COVERAGE_TARGET_THRESHOLD:
            return AuditCheck(
                name="Coverage",
                status=AuditCheckStatus.PARTIAL,
                detail=(
                    f"minimum enforced threshold is {min_threshold:g}% "
                    f"({min_source}); acceptable minimum met, target 70%+{target_suffix}"
                ),
            )

        return AuditCheck(
            name="Coverage",
            status=AuditCheckStatus.PRESENT,
            detail=(
                f"minimum enforced threshold {min_threshold:g}% ({min_source})"
                f"{target_suffix}"
            ),
        )

    # -- Async checks ---------------------------------------------------------

    async def _check_gh_cli(self) -> AuditCheck:
        """Check gh CLI authentication and repo access."""
        try:
            await run_subprocess("gh", "auth", "status", gh_token=self._config.gh_token)
        except RuntimeError as exc:
            return AuditCheck(
                name="gh CLI",
                status=AuditCheckStatus.MISSING,
                detail=f"auth failed: {exc}",
                critical=True,
            )

        try:
            permission = await run_subprocess(
                "gh",
                "repo",
                "view",
                self._config.repo,
                "--json",
                "viewerPermission",
                "--jq",
                ".viewerPermission",
                gh_token=self._config.gh_token,
            )
            permission = permission.strip().upper()
            if permission in ("WRITE", "ADMIN"):
                return AuditCheck(
                    name="gh CLI",
                    status=AuditCheckStatus.PRESENT,
                    detail="authenticated, push access",
                    critical=True,
                )
            return AuditCheck(
                name="gh CLI",
                status=AuditCheckStatus.PARTIAL,
                detail="authenticated, read-only access",
                critical=True,
            )
        except RuntimeError as exc:
            return AuditCheck(
                name="gh CLI",
                status=AuditCheckStatus.PARTIAL,
                detail=f"authenticated, repo check failed: {exc}",
                critical=True,
            )

    async def _check_labels(self) -> AuditCheck:
        """Check for HydraFlow lifecycle labels on the GitHub repo."""
        expected = set(self._get_hydra_labels())

        try:
            output = await run_subprocess(
                "gh",
                "label",
                "list",
                "--repo",
                self._config.repo,
                "--json",
                "name",
                "--jq",
                ".[].name",
                gh_token=self._config.gh_token,
            )
            existing = {line.strip() for line in output.splitlines() if line.strip()}
        except RuntimeError:
            return AuditCheck(
                name="Labels",
                status=AuditCheckStatus.MISSING,
                detail="could not fetch labels",
            )

        missing = expected - existing
        if not missing:
            return AuditCheck(
                name="Labels",
                status=AuditCheckStatus.PRESENT,
                detail=f"all {len(expected)} labels",
            )
        if missing == expected:
            return AuditCheck(
                name="Labels",
                status=AuditCheckStatus.MISSING,
                detail=f"missing all {len(expected)} HydraFlow labels",
            )
        return AuditCheck(
            name="Labels",
            status=AuditCheckStatus.PARTIAL,
            detail=f"missing: {', '.join(sorted(missing))}",
        )

    def _check_agents_md(self) -> AuditCheck:
        """Check for AGENTS.md in the repo root.

        AGENTS.md is the canonical prompt contract document.  Its presence
        ensures every agent (Claude, Codex, Pi.dev) has documented role
        expectations, output markers, and behaviour rules.

        See: AGENTS.md in the HydraFlow repo.
        """
        agents_md = self._root / "AGENTS.md"

        if agents_md.is_dir():
            return AuditCheck(
                name="AGENTS.md",
                status=AuditCheckStatus.PARTIAL,
                detail="AGENTS.md exists as a directory, not a file — remove it and run `make setup`",
            )

        if agents_md.is_file():
            return AuditCheck(
                name="AGENTS.md",
                status=AuditCheckStatus.PRESENT,
                detail="agent prompt contracts documented",
            )

        return AuditCheck(
            name="AGENTS.md",
            status=AuditCheckStatus.MISSING,
            detail=(
                "missing AGENTS.md — agent roles, output markers, and prompt "
                "contracts are undocumented; copy from the HydraFlow repo or run "
                "`make setup` to sync it"
            ),
        )

    def _get_hydra_labels(self) -> list[str]:
        """Return the full list of HydraFlow lifecycle label names from config."""
        labels: list[str] = []
        for label_field in _LABEL_FIELDS:
            labels.extend(getattr(self._config, label_field))
        return labels
