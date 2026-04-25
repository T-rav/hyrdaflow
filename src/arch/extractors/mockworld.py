"""Extract MockWorldMap from tests/scenarios/fakes/ and scenario users.

For each Fake* class under fakes_dir (excluding `__*` and `test_*`),
records its name, dotted module path, repo-relative source path, and
candidate Port (Fake<X> → XPort by name). Scans scenarios_dir for
test_*.py files that mention the fake's module + class name; lists
each as a scenario user.
"""

from __future__ import annotations

import ast
from pathlib import Path

from arch._models import FakeInfo, MockWorldMap


def _repo_relative_module(path: Path, repo_root: Path) -> str:
    rel = path.relative_to(repo_root)
    return ".".join(rel.with_suffix("").parts)


def _fake_classes(fakes_dir: Path, repo_root: Path) -> list[FakeInfo]:
    """Walk fakes_dir for `class Fake*:` declarations.

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
            if isinstance(node, ast.ClassDef) and node.name.startswith("Fake"):
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
    # Repo root: assumes fakes_dir == <repo_root>/tests/scenarios/fakes
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
