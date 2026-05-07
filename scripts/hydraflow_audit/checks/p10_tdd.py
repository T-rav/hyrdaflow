"""P10 — TDD workflow discipline (ADR-0044)."""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import finding


@register("P10.1")
def _claude_md_documents_tdd(ctx: CheckContext) -> Finding:
    claude = ctx.root / "CLAUDE.md"
    if not claude.exists():
        return finding("P10.1", Status.FAIL, "CLAUDE.md missing")
    text = claude.read_text(encoding="utf-8", errors="replace")
    names_skill = "test-driven-development" in text
    mentions_test_first = bool(
        re.search(
            r"\btest[- ]first\b|\bwrite.*test.*before\b|\bTDD\b", text, re.IGNORECASE
        )
    )
    if names_skill and mentions_test_first:
        return finding("P10.1", Status.PASS)
    missing: list[str] = []
    if not names_skill:
        missing.append("`superpowers:test-driven-development` skill reference")
    if not mentions_test_first:
        missing.append("a test-first / TDD mention")
    return finding(
        "P10.1",
        Status.WARN,
        f"CLAUDE.md missing: {', '.join(missing)}",
    )


@register("P10.2")
def _every_module_has_a_test(ctx: CheckContext) -> Finding:
    src = ctx.root / "src"
    tests = ctx.root / "tests"
    if not src.is_dir():
        return finding("P10.2", Status.NA, "no src/")
    if not tests.is_dir():
        return finding("P10.2", Status.FAIL, "tests/ missing")
    test_stems = {_normalise_test_stem(p.stem) for p in tests.rglob("test_*.py")}
    orphans: list[str] = []
    for module in src.rglob("*.py"):
        if _skip_module(module):
            continue
        expected = module.stem
        if expected.startswith("_"):
            continue
        if expected not in test_stems:
            orphans.append(module.relative_to(ctx.root).as_posix())
    if not orphans:
        return finding("P10.2", Status.PASS)
    total = sum(
        1
        for p in src.rglob("*.py")
        if not _skip_module(p) and not p.stem.startswith("_")
    )
    ratio = len(orphans) / total if total else 0
    if ratio < 0.2:
        return finding(
            "P10.2",
            Status.PASS,
            f"{len(orphans)}/{total} modules without matching test ({ratio:.0%})",
        )
    sample = ", ".join(orphans[:3])
    return finding(
        "P10.2",
        Status.WARN,
        f"{len(orphans)}/{total} src/ modules have no test_<module>.py counterpart ({sample})",
    )


def _skip_module(path: Path) -> bool:
    name = path.name
    return (
        name == "__init__.py"
        or name.endswith("_pb2.py")
        or "/migrations/" in path.as_posix()
    )


def _normalise_test_stem(stem: str) -> str:
    """`test_config` → `config`; `test_config_integration` → `config_integration` (preserve for later)."""
    return stem.removeprefix("test_")


_FIX_COMMIT_RE = re.compile(r"^(fix|bugfix|bug)[\(:]", re.IGNORECASE)
_BASELINE_FILE = ".hydraflow-audit-baseline"


@register("P10.3")
def _bug_fixes_land_with_regression_tests(ctx: CheckContext) -> Finding:  # noqa: PLR0911 — fast-path NA returns are clearer than a chain
    """Measure recent fix commits against regression-test discipline.

    The principle's intent is "every bug fix *from now on* lands with a
    regression test." Historical drift predates the principle's adoption.
    Two mechanisms keep the check honest:

    1. A `.hydraflow-audit-baseline` file (commit SHA or ISO date) lets a
       project declare the point at which the rule took effect; earlier
       fix commits are excluded.
    2. The threshold is 60% compliance on *recent* fixes — a project
       improving its discipline reaches PASS before rewriting history.
    """
    if not (ctx.root / ".git").exists():
        return finding("P10.3", Status.NA, "not a git repo")
    baseline = _read_baseline(ctx.root)
    git_args = ["git", "log", "--no-merges", "-n", "50", "--format=%H%x09%s"]
    if baseline is not None:
        git_args.append(f"{baseline}..HEAD")
    try:
        result = subprocess.run(
            git_args,
            check=False,
            cwd=ctx.root,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return finding("P10.3", Status.NA, "git log timed out")
    if result.returncode != 0:
        return finding("P10.3", Status.NA, "git log failed")
    fix_commits = [
        line.split("\t", 1)[0]
        for line in result.stdout.splitlines()
        if "\t" in line and _FIX_COMMIT_RE.match(line.split("\t", 1)[1])
    ]
    scope = f"since baseline {baseline[:7]}" if baseline else "last 50 commits"
    if not fix_commits:
        return finding(
            "P10.3", Status.PASS, f"no fix/bug commits {scope} — nothing to audit"
        )
    missing: list[str] = []
    for sha in fix_commits:
        if not _touched_regressions(ctx.root, sha):
            missing.append(sha[:7])
    covered = len(fix_commits) - len(missing)
    ratio = covered / len(fix_commits)
    if not missing:
        return finding(
            "P10.3",
            Status.PASS,
            f"{len(fix_commits)} fix commit(s) {scope} all touched regressions/",
        )
    if ratio >= 0.6:
        return finding(
            "P10.3",
            Status.PASS,
            f"{covered}/{len(fix_commits)} fix commits {scope} carry regression tests ({ratio:.0%})",
        )
    sample = ", ".join(missing[:3])
    return finding(
        "P10.3",
        Status.WARN,
        f"{len(missing)}/{len(fix_commits)} fix commits {scope} without a regression test ({sample}) — "
        "set .hydraflow-audit-baseline to a post-adoption commit to exclude historical drift",
    )


def _read_baseline(root: Path) -> str | None:
    """Return a commit SHA or ISO date the user declared as the rule's start point."""
    path = root / _BASELINE_FILE
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return None
    # Strip a leading `#`-prefixed comment line if present.
    lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return lines[0] if lines else None


def _touched_regressions(root: Path, sha: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "show", "--stat", "--format=", sha],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return True  # don't false-alarm on errors
    return "tests/regressions/" in result.stdout


@register("P10.4")
def _test_names_describe_behaviour(ctx: CheckContext) -> Finding:
    tests = ctx.root / "tests"
    if not tests.is_dir():
        return finding("P10.4", Status.NA, "no tests/")
    sampled = 0
    bad: list[str] = []
    for py in tests.rglob("test_*.py"):
        if sampled >= 300:
            break
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                sampled += 1
                if _is_implementation_named(node.name):
                    bad.append(f"{py.name}::{node.name}")
                if sampled >= 300:
                    break
    if sampled == 0:
        return finding("P10.4", Status.NA, "no test functions to sample")
    ratio = len(bad) / sampled
    if ratio < 0.1:
        return finding(
            "P10.4",
            Status.PASS,
            f"{len(bad)}/{sampled} tests with implementation-shaped names ({ratio:.0%})",
        )
    sample = ", ".join(bad[:3])
    return finding(
        "P10.4",
        Status.WARN,
        f"{len(bad)}/{sampled} tests named after functions (not behaviour): {sample}",
    )


def _is_implementation_named(test_name: str) -> bool:
    """Flag names like `test_merge_function` or `test_handler` that echo identifiers."""
    suffix = test_name.removeprefix("test_")
    # Heuristic: single word or camel-free snake = likely implementation name.
    # Behavioural names contain `_when_`, `_if_`, `_after_`, `_returns_`, etc.
    behavioural_markers = (
        "_when_",
        "_if_",
        "_given_",
        "_returns_",
        "_raises_",
        "_fails_",
        "_passes_",
        "_warns_",
        "_handles_",
        "_rejects_",
        "_accepts_",
        "_emits_",
    )
    if any(marker in test_name for marker in behavioural_markers):
        return False
    return "_" not in suffix or suffix.endswith(
        ("_function", "_method", "_handler", "_class")
    )


@register("P10.5")
def _tests_use_3as(ctx: CheckContext) -> Finding:
    """Heuristic: a test with ≥3 assertions in a row is likely conflating scenarios.

    Not a universal rule (parametrised tests with one assert are fine; some
    state-machine tests need two), so we only warn when the ratio is high.
    """
    tests = ctx.root / "tests"
    if not tests.is_dir():
        return finding("P10.5", Status.NA, "no tests/")
    multi_assert = 0
    total = 0
    for py in tests.rglob("test_*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                total += 1
                assert_count = sum(
                    1 for n in ast.walk(node) if isinstance(n, ast.Assert)
                )
                if assert_count >= 4:
                    multi_assert += 1
    if total == 0:
        return finding("P10.5", Status.NA, "no test functions")
    ratio = multi_assert / total
    if ratio < 0.1:
        return finding(
            "P10.5",
            Status.PASS,
            f"{multi_assert}/{total} tests with ≥4 assertions ({ratio:.0%})",
        )
    return finding(
        "P10.5",
        Status.WARN,
        f"{multi_assert}/{total} tests have ≥4 assertions — possible 3As violation",
    )
