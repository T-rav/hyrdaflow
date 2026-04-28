"""Extract MockWorldMap from src/mockworld/fakes/ and scenario users.

For each Fake* class under fakes_dir (excluding `__*` and `test_*`) that
carries the ``_is_fake_adapter = True`` class-body marker, records its
name, dotted module path, repo-relative source path, and candidate Port
(Fake<X> → XPort by name). Scans scenarios_dir for test_*.py files that
mention the fake's module + class name; lists each as a scenario user.

The marker filter intentionally excludes nested-record dataclasses
(``FakeIssue``, ``FakePR``, ``FakeIssueRecord``, ``FakeIssueSummary``)
that live in the same file as a Fake adapter but are not themselves
Port-implementing adapters. Without this filter, the naive
``Fake<Stem>`` → ``<Stem>Port`` rule invented Ports that don't exist
(``IssuePort``, ``PRPort`` linking to ``FakeIssue``/``FakePR``, …) in
the generated MockWorld map.
"""

from __future__ import annotations

import ast
from pathlib import Path

from arch._models import FakeInfo, MockWorldMap


def _repo_relative_module(path: Path, repo_root: Path) -> str:
    """For repo/src/mockworld/fakes/fake_x.py, return 'mockworld.fakes.fake_x'.

    Trims a leading ``src`` segment so the emitted dotted module matches the
    importable path (``mockworld.fakes.X``, not ``src.mockworld.fakes.X``).
    Falls back to the dotted repo-relative path for any other layout (e.g.
    extractor unit-test fixtures rooted at ``tests/scenarios/fakes/``).
    """
    rel = path.relative_to(repo_root)
    parts = rel.with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def _has_fake_adapter_marker(cls: ast.ClassDef) -> bool:
    """True if the class body contains ``_is_fake_adapter = True``.

    Detected purely via AST so we don't have to import the fake module
    (importing fakes pulls in production deps that may not be installed
    when this extractor runs).

    Accepts two assignment shapes used in the codebase:

    1. Plain class-level attribute (most fakes):

        class FakeFoo:
            _is_fake_adapter = True

    2. ``ClassVar`` annotation (used for ``@dataclass`` fakes like
       ``FakeWikiCompiler`` so the marker isn't promoted to a dataclass
       init field):

        @dataclass
        class FakeFoo:
            _is_fake_adapter: ClassVar[bool] = True
    """
    for stmt in cls.body:
        # Plain assignment: `_is_fake_adapter = True`
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "_is_fake_adapter"
                    and isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is True
                ):
                    return True
        # Annotated assignment: `_is_fake_adapter: ClassVar[bool] = True`
        elif isinstance(stmt, ast.AnnAssign) and (
            isinstance(stmt.target, ast.Name)
            and stmt.target.id == "_is_fake_adapter"
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is True
        ):
            return True
    return False


def _fake_classes(fakes_dir: Path, repo_root: Path) -> list[FakeInfo]:
    """Walk fakes_dir for `class Fake*:` declarations carrying the marker.

    Only includes classes that have ``_is_fake_adapter = True`` in their
    body (see :func:`_has_fake_adapter_marker`). This excludes
    nested-record dataclasses like ``FakeIssue`` / ``FakePR`` that live
    alongside Fake adapters but don't implement a Port themselves.

    `source_path` is recorded as repo-root-relative so generated Markdown is
    portable and diffable; absolute paths would leak the developer's home dir
    into committed `docs/arch/generated/mockworld.md`.
    """
    out: list[FakeInfo] = []
    if not fakes_dir.exists():
        return out
    for py in sorted(fakes_dir.glob("*.py")):
        if py.name.startswith("__") or py.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        for node in tree.body:
            if (
                isinstance(node, ast.ClassDef)
                and node.name.startswith("Fake")
                and _has_fake_adapter_marker(node)
            ):
                out.append(
                    FakeInfo(
                        name=node.name,
                        module=_repo_relative_module(py, repo_root),
                        source_path=str(py.relative_to(repo_root)),
                    )
                )
    return out


def _scenario_uses(scenarios_dir: Path, fake_module: str, fake_name: str) -> list[str]:
    """Return the list of test files that import the fake."""
    out: list[str] = []
    if not scenarios_dir.exists():
        return out
    for py in sorted(scenarios_dir.rglob("test_*.py")):
        text = py.read_text()
        # Cheap textual match — false positives are rare and harmless here.
        if fake_module in text and fake_name in text:
            out.append(str(py))
    return out


def extract_mockworld_map(*, fakes_dir: Path, scenarios_dir: Path) -> MockWorldMap:
    fakes_dir = Path(fakes_dir).resolve()
    scenarios_dir = Path(scenarios_dir).resolve()
    # Repo root: assumes fakes_dir is 3 levels deep
    # (e.g. <repo_root>/src/mockworld/fakes, or in extractor unit-test
    # fixtures, <tmp_root>/tests/scenarios/fakes).
    repo_root = fakes_dir.parents[2]

    fakes = _fake_classes(fakes_dir, repo_root)
    enriched: list[FakeInfo] = []
    for f in fakes:
        # Candidate Port name: FakeWidget -> WidgetPort
        stem = f.name.removeprefix("Fake")
        candidate_port = f"{stem}Port" if stem else None
        scenarios = _scenario_uses(scenarios_dir, f.module, f.name)
        # Trim each scenario path to repo-root-relative
        rel_scenarios = []
        for s in scenarios:
            try:
                rel_scenarios.append(str(Path(s).relative_to(repo_root)))
            except ValueError:
                rel_scenarios.append(s)
        enriched.append(
            f.model_copy(
                update={
                    "implements_port": candidate_port,
                    "used_in_scenarios": sorted(rel_scenarios),
                }
            )
        )
    enriched.sort(key=lambda fake: fake.name)
    return MockWorldMap(fakes=enriched)
