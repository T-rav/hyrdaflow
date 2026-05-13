from pathlib import Path

import pytest
import yaml

from arch._functional_areas_schema import load_functional_areas
from arch.extractors.loops import extract_loops
from arch.extractors.ports import extract_ports

_PRE_ASSIGNED: set[str] = set()


def test_every_loop_is_assigned_to_an_area(real_repo_root: Path):
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    if not yaml_path.exists():
        pytest.skip("docs/arch/functional_areas.yml not yet authored (Task 4)")

    fa = load_functional_areas(yaml_path)
    assigned: set[str] = set()
    for area in fa.areas.values():
        assigned.update(area.loops)

    discovered = {info.name for info in extract_loops(real_repo_root / "src")}
    missing = discovered - assigned
    if missing:
        pytest.fail(
            f"{len(missing)} loops are not assigned to any functional area:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nFix: edit docs/arch/functional_areas.yml and add each to the "
            "appropriate area's `loops:` list."
        )


def test_every_port_is_assigned_to_an_area(real_repo_root: Path):
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    if not yaml_path.exists():
        pytest.skip("docs/arch/functional_areas.yml not yet authored")

    fa = load_functional_areas(yaml_path)
    assigned: set[str] = set()
    for area in fa.areas.values():
        assigned.update(area.ports)

    discovered = {
        info.name
        for info in extract_ports(
            src_dir=real_repo_root / "src",
            fakes_dir=real_repo_root / "src/mockworld/fakes",
        )
    }
    missing = discovered - assigned
    if missing:
        pytest.fail(
            f"{len(missing)} ports are not assigned to any functional area:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nFix: edit docs/arch/functional_areas.yml `ports:` lists."
        )


def test_functional_areas_modules_paths_exist(real_repo_root: Path):
    """Every literal (non-glob) path in a modules: list must exist on disk.

    Glob patterns (containing '*') are exempt — they are validated at
    generation time by the extractor, not here.
    """
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    if not yaml_path.exists():
        pytest.skip("docs/arch/functional_areas.yml not yet authored")

    data = yaml.safe_load(yaml_path.read_text())
    missing: list[str] = []
    for area in data.get("areas", {}).values():
        for path in area.get("modules", []):
            if "*" in path:
                continue  # glob — skip literal-existence check
            if not (real_repo_root / path).exists():
                missing.append(path)

    assert not missing, (
        f"Bad modules: paths in docs/arch/functional_areas.yml "
        f"(paths that don't exist on disk):\n  " + "\n  ".join(sorted(missing))
    )


def test_no_phantom_assignments(real_repo_root: Path):
    """Loops/ports listed in the YAML but absent from code → fail."""
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    if not yaml_path.exists():
        pytest.skip("docs/arch/functional_areas.yml not yet authored")

    fa = load_functional_areas(yaml_path)
    discovered_loops = {info.name for info in extract_loops(real_repo_root / "src")}
    discovered_ports = {
        info.name
        for info in extract_ports(
            src_dir=real_repo_root / "src",
            fakes_dir=real_repo_root / "src/mockworld/fakes",
        )
    }

    phantom_loops: list[tuple[str, str]] = []
    phantom_ports: list[tuple[str, str]] = []
    for key, area in fa.areas.items():
        for ln in area.loops:
            if ln not in discovered_loops and ln not in _PRE_ASSIGNED:
                phantom_loops.append((key, ln))
        for pn in area.ports:
            if pn not in discovered_ports:
                phantom_ports.append((key, pn))

    if phantom_loops or phantom_ports:
        msg = []
        if phantom_loops:
            msg.append("Phantom loops (in YAML, not in code):")
            msg.extend(f"  {area}.loops: {ln}" for area, ln in phantom_loops)
        if phantom_ports:
            msg.append("Phantom ports:")
            msg.extend(f"  {area}.ports: {pn}" for area, pn in phantom_ports)
        pytest.fail(
            "\n".join(msg)
            + "\n\nFix: rename the YAML entry to match the live class name, or remove it."
        )
