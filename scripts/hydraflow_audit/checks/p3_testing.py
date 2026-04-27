"""P3 — Testing, MockWorld, and layered tests (ADR-0044)."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import exists, finding

# ---------------------------------------------------------------------------
# Simple presence checks.
# ---------------------------------------------------------------------------


@register("P3.1")
def _scenarios_dir_exists(ctx: CheckContext) -> Finding:
    return exists(ctx.root, "tests/scenarios", "P3.1")


@register("P3.4")
def _root_conftest_has_fixtures(ctx: CheckContext) -> Finding:
    path = ctx.root / "tests" / "conftest.py"
    if not path.exists():
        return finding("P3.4", Status.FAIL, "tests/conftest.py missing")
    text = path.read_text(encoding="utf-8", errors="replace")
    if "@pytest.fixture" in text or "pytest.fixture" in text:
        return finding("P3.4", Status.PASS)
    return finding("P3.4", Status.FAIL, "tests/conftest.py has no pytest fixtures")


@register("P3.16")
def _regressions_dir(ctx: CheckContext) -> Finding:
    return exists(ctx.root, "tests/regressions", "P3.16")


# ---------------------------------------------------------------------------
# MockWorld-shaped checks — P3.2, P3.3, P3.12–P3.15.
# ---------------------------------------------------------------------------


@register("P3.2")
def _mock_world_fixture(ctx: CheckContext) -> Finding:
    conftest = ctx.root / "tests" / "scenarios" / "conftest.py"
    if not conftest.exists():
        return finding("P3.2", Status.FAIL, "tests/scenarios/conftest.py missing")
    text = conftest.read_text(encoding="utf-8", errors="replace")
    if "mock_world" not in text:
        return finding(
            "P3.2",
            Status.FAIL,
            "tests/scenarios/conftest.py does not expose a `mock_world` fixture",
        )
    if "fixture" not in text:
        return finding(
            "P3.2",
            Status.FAIL,
            "`mock_world` referenced but no `fixture` decorator found in conftest",
        )
    return finding("P3.2", Status.PASS)


_FAKE_CLASS_RE = re.compile(r"^class\s+(Fake\w+|Mock\w+)", re.MULTILINE)


# Canonical Fake locations. Fakes were originally housed exclusively
# under ``tests/scenarios/fakes/`` (per ADR-0022). They were promoted
# to first-class adapters under ``src/mockworld/fakes/`` by the
# sandbox-tier scenario testing track (spec
# 2026-04-26-sandbox-tier-scenarios-design.md, ADR-0052). The audit
# accepts Fakes at EITHER location during the transition; once
# ADR-0022 is amended to declare ``src/mockworld/fakes/`` canonical,
# the legacy path can be dropped.
_FAKE_DIRS_REL: tuple[tuple[str, ...], ...] = (
    ("src", "mockworld", "fakes"),
    ("tests", "scenarios", "fakes"),
)


def _collect_fake_classes(ctx: CheckContext) -> set[str]:
    """Collect Fake/Mock class names from every canonical Fake directory."""
    classes: set[str] = set()
    for parts in _FAKE_DIRS_REL:
        d = ctx.root.joinpath(*parts)
        if not d.is_dir():
            continue
        for py in d.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="replace")
            classes.update(_FAKE_CLASS_RE.findall(text))
    return classes


@register("P3.3")
def _scenario_fakes(ctx: CheckContext) -> Finding:
    classes = _collect_fake_classes(ctx)
    if not classes:
        return finding(
            "P3.3",
            Status.FAIL,
            "no Fake/Mock classes in src/mockworld/fakes/ or tests/scenarios/fakes/",
        )
    if len(classes) >= 3:
        return finding(
            "P3.3", Status.PASS, f"{len(classes)} fake classes: {sorted(classes)[:5]}"
        )
    return finding(
        "P3.3",
        Status.FAIL,
        f"only {len(classes)} Fake/Mock classes (need ≥3): {sorted(classes)}",
    )


_RESULT_SHAPE_RE = re.compile(r"class\s+(Scenario\w*Result|IssueOutcome|\w*Outcome)\b")


@register("P3.12")
def _scenario_result_type(ctx: CheckContext) -> Finding:
    return _grep_in_tree(
        ctx,
        root_rel="tests/scenarios",
        pattern=_RESULT_SHAPE_RE,
        check_id="P3.12",
        missing_msg="no ScenarioResult/IssueOutcome class in tests/scenarios/ — scenarios return call-counts, not state",
    )


_FAKE_CLOCK_RE = re.compile(r"class\s+(FakeClock|FrozenClock|DeterministicClock)\b")


@register("P3.13")
def _fake_clock(ctx: CheckContext) -> Finding:
    """Look for a clock fake.

    Original audit walked all of ``tests/scenarios/`` (FakeClock can
    reasonably live alongside the harness, not only in ``fakes/``).
    Post-Task-1.1 of the sandbox-tier scenario testing track, the
    canonical home for adapter Fakes is ``src/mockworld/fakes/`` —
    so we walk that too.
    """
    search_roots = (
        ctx.root / "src" / "mockworld" / "fakes",
        ctx.root / "tests" / "scenarios",
    )
    for d in search_roots:
        if not d.is_dir():
            continue
        for py in d.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="replace")
            if _FAKE_CLOCK_RE.search(text):
                return finding(
                    "P3.13",
                    Status.PASS,
                    f"clock fake found in {py.relative_to(ctx.root)}",
                )
    return finding(
        "P3.13",
        Status.FAIL,
        "no FakeClock/FrozenClock/DeterministicClock in src/mockworld/fakes/ or tests/scenarios/",
    )


@register("P3.14")
def _fakes_are_stateful(ctx: CheckContext) -> Finding:
    """Warn when Fake classes inherit from AsyncMock / MagicMock rather than plain object."""
    fake_dirs = [
        ctx.root.joinpath(*parts)
        for parts in _FAKE_DIRS_REL
        if ctx.root.joinpath(*parts).is_dir()
    ]
    if not fake_dirs:
        return finding(
            "P3.14",
            Status.NA,
            "no Fake directories — upstream check covers this",
        )
    bad: list[str] = []
    for fakes_dir in fake_dirs:
        for py in fakes_dir.rglob("*.py"):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and _inherits_mock(node):
                    bad.append(f"{py.name}:{node.name}")
    if not bad:
        return finding("P3.14", Status.PASS)
    return finding(
        "P3.14",
        Status.WARN,
        f"{len(bad)} fake class(es) inherit from Mock/AsyncMock: {', '.join(bad[:3])}",
    )


_FAULT_INJECTION_RE = re.compile(
    r"\b(fail_service|heal_service|inject_fault|break_service)\b"
)


@register("P3.15")
def _fault_injection_api(ctx: CheckContext) -> Finding:
    return _grep_in_tree(
        ctx,
        root_rel="tests/scenarios",
        pattern=_FAULT_INJECTION_RE,
        check_id="P3.15",
        missing_msg="no fault-injection API on MockWorld (fail_service/heal_service/inject_fault)",
    )


# ---------------------------------------------------------------------------
# Factories — P3.5.
# ---------------------------------------------------------------------------


_FACTORY_CLASS_RE = re.compile(r"^class\s+(\w+Factory)\b", re.MULTILINE)


@register("P3.5")
def _factory_classes(ctx: CheckContext) -> Finding:
    tests_dir = ctx.root / "tests"
    if not tests_dir.is_dir():
        return finding("P3.5", Status.FAIL, "tests/ missing")
    for py in tests_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if _FACTORY_CLASS_RE.search(text):
            return finding("P3.5", Status.PASS)
    return finding("P3.5", Status.FAIL, "no *Factory classes found under tests/")


# ---------------------------------------------------------------------------
# pyproject / Makefile-driven checks — P3.6–P3.9, P3.17.
# ---------------------------------------------------------------------------


@register("P3.6")
def _coverage_floor(ctx: CheckContext) -> Finding:
    data = _load_pyproject(ctx.root)
    if data is None:
        return finding("P3.6", Status.FAIL, "pyproject.toml missing or unreadable")
    report = data.get("tool", {}).get("coverage", {}).get("report", {})
    fail_under = report.get("fail_under")
    if fail_under is None:
        return finding(
            "P3.6",
            Status.FAIL,
            "[tool.coverage.report] fail_under not configured",
        )
    if fail_under >= 70:
        return finding("P3.6", Status.PASS, f"fail_under = {fail_under}")
    return finding(
        "P3.6",
        Status.FAIL,
        f"coverage fail_under is {fail_under} (need ≥70)",
    )


_MAKE_TARGET_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*)\s*:", re.MULTILINE)


def _has_make_target(root: Path, name: str) -> bool:
    mf = root / "Makefile"
    if not mf.exists():
        return False
    text = mf.read_text(encoding="utf-8", errors="replace")
    return any(m.group(1) == name for m in _MAKE_TARGET_RE.finditer(text))


@register("P3.7")
def _make_test(ctx: CheckContext) -> Finding:
    if _has_make_target(ctx.root, "test"):
        return finding("P3.7", Status.PASS)
    return finding("P3.7", Status.FAIL, "Makefile has no `test` target")


@register("P3.8")
def _make_scenario(ctx: CheckContext) -> Finding:
    if _has_make_target(ctx.root, "scenario"):
        return finding("P3.8", Status.PASS)
    return finding("P3.8", Status.FAIL, "Makefile has no `scenario` target")


@register("P3.9")
def _make_smoke(ctx: CheckContext) -> Finding:
    if _has_make_target(ctx.root, "smoke"):
        return finding("P3.9", Status.PASS)
    return finding("P3.9", Status.FAIL, "Makefile has no `smoke` target")


@register("P3.17")
def _pytest_markers_registered(ctx: CheckContext) -> Finding:
    data = _load_pyproject(ctx.root)
    if data is None:
        return finding("P3.17", Status.FAIL, "pyproject.toml missing")
    pytest_cfg = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    markers_raw = pytest_cfg.get("markers", [])
    marker_names = {_marker_name(m) for m in markers_raw}
    required = {"integration", "scenario"}
    missing = required - marker_names
    if not missing:
        return finding("P3.17", Status.PASS)
    return finding(
        "P3.17",
        Status.FAIL,
        f"missing pytest markers: {sorted(missing)}",
    )


# ---------------------------------------------------------------------------
# CI and conditional checks — P3.10, P3.11, P3.18, P3.19.
# ---------------------------------------------------------------------------


@register("P3.10")
def _scenarios_release_gating(ctx: CheckContext) -> Finding:
    workflows_dir = ctx.root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return finding("P3.10", Status.FAIL, ".github/workflows/ missing")
    for yml in workflows_dir.rglob("*.y*ml"):
        text = yml.read_text(encoding="utf-8", errors="replace")
        if "scenario" in text.lower():
            return finding("P3.10", Status.PASS, f"scenarios referenced in {yml.name}")
    return finding(
        "P3.10",
        Status.FAIL,
        "no workflow references `scenario` — release gate not wired",
    )


@register("P3.11")
def _browser_e2e_when_ui_present(ctx: CheckContext) -> Finding:
    if not ctx.has_ui:
        return finding("P3.11", Status.NA, "no ui/ — browser E2E not required")
    candidates = [
        ctx.root / "tests" / "scenarios" / "browser",
        ctx.root / "tests" / "browser",
        ctx.root / "tests" / "e2e",
    ]
    for path in candidates:
        if path.is_dir():
            return finding("P3.11", Status.PASS, f"browser E2E dir: {path.name}")
    return finding(
        "P3.11",
        Status.FAIL,
        "ui/ present but no browser E2E directory (tried tests/scenarios/browser, tests/browser, tests/e2e)",
    )


@register("P3.18")
def _integration_test_file(ctx: CheckContext) -> Finding:
    tests_dir = ctx.root / "tests"
    if not tests_dir.is_dir():
        return finding("P3.18", Status.FAIL, "tests/ missing")
    hits = list(tests_dir.rglob("*_integration.py"))
    if hits:
        return finding("P3.18", Status.PASS, f"{len(hits)} *_integration.py file(s)")
    return finding(
        "P3.18",
        Status.FAIL,
        "no *_integration.py file — integration ring has no representative",
    )


@register("P3.19")
def _no_top_level_optional_imports_in_tests(ctx: CheckContext) -> Finding:
    """Flag module-level imports of deps that aren't in `[project.dependencies]`.

    An "optional" dep here is one the project itself marks as optional — via
    `[project.optional-dependencies]` or any `[dependency-groups]` table —
    rather than a fixed list. If pyproject declares no optional deps the
    check is NA.
    """
    tests_dir = ctx.root / "tests"
    if not tests_dir.is_dir():
        return finding("P3.19", Status.NA, "no tests/ directory")
    optional = _discover_optional_deps(ctx.root)
    if not optional:
        return finding(
            "P3.19", Status.NA, "pyproject.toml declares no optional dependencies"
        )
    offenders: list[str] = []
    for py in tests_dir.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            if _imports_optional_dep(node, optional):
                offenders.append(py.relative_to(ctx.root).as_posix())
                break
    if not offenders:
        return finding("P3.19", Status.PASS)
    sample = ", ".join(offenders[:3])
    return finding(
        "P3.19",
        Status.WARN,
        f"{len(offenders)} test file(s) import optional deps at module level: {sample}",
    )


_TEST_EXTRA_NAMES = {"test", "tests", "testing", "dev", "develop", "development"}


def _discover_optional_deps(root: Path) -> tuple[str, ...]:
    """Collect optional deps, excluding the test/dev extras.

    Test-extra packages (pytest, hypothesis, etc.) are installed by definition
    whenever tests run — a module-level import of pytest is not an audit
    concern. The pattern we care about is deps that may or may not be present
    at test-collection time (runtime-only extras, platform extras).
    """
    data = _load_pyproject(root)
    if data is None:
        return ()
    declared: set[str] = set()
    project = data.get("project", {})
    for name, extras in project.get("optional-dependencies", {}).items():
        if name.lower() in _TEST_EXTRA_NAMES:
            continue
        declared.update(_package_names(extras))
    for name, group in data.get("dependency-groups", {}).items():
        if name.lower() in _TEST_EXTRA_NAMES:
            continue
        declared.update(_package_names(group))
    return tuple(sorted(declared))


_DEP_NAME_RE = re.compile(r"^([A-Za-z0-9_.\-]+)")


def _package_names(items: object) -> set[str]:
    if not isinstance(items, list):
        return set()
    names: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        match = _DEP_NAME_RE.match(item)
        if match:
            # Normalise to module-import shape: `sentry-sdk` imports as `sentry_sdk`.
            names.add(match.group(1).replace("-", "_"))
    return names


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _grep_in_tree(
    ctx: CheckContext,
    *,
    root_rel: str,
    pattern: re.Pattern[str],
    check_id: str,
    missing_msg: str,
) -> Finding:
    base = ctx.root / root_rel
    if not base.is_dir():
        return finding(check_id, Status.FAIL, f"{root_rel}/ missing")
    for py in base.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            return finding(check_id, Status.PASS)
    return finding(check_id, Status.FAIL, missing_msg)


def _load_pyproject(root: Path) -> dict | None:
    path = root / "pyproject.toml"
    if not path.exists():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _marker_name(raw: str) -> str:
    # "scenario: runs the scenario tier" → "scenario"
    return raw.split(":", 1)[0].strip()


def _inherits_mock(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = ""
        if isinstance(base, ast.Name):
            name = base.id
        elif isinstance(base, ast.Attribute):
            name = base.attr
        if name in {"MagicMock", "AsyncMock", "Mock", "NonCallableMock"}:
            return True
    return False


def _imports_optional_dep(node: ast.stmt, deps: tuple[str, ...]) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name.split(".")[0] in deps for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        module = (node.module or "").split(".")[0]
        return module in deps
    return False
