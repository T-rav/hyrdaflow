from pathlib import Path

import pytest
from pydantic import ValidationError

from arch._functional_areas_schema import load_functional_areas


def test_schema_accepts_minimum_valid_doc(tmp_path: Path):
    p = tmp_path / "fa.yml"
    p.write_text(
        "areas:\n"
        "  orchestration:\n"
        "    label: Orchestration\n"
        "    description: The plan→implement→review pipeline.\n"
    )
    fa = load_functional_areas(p)
    assert "orchestration" in fa.areas
    assert fa.areas["orchestration"].loops == []


def test_schema_rejects_missing_label(tmp_path: Path):
    p = tmp_path / "fa.yml"
    p.write_text("areas:\n  orchestration:\n    description: Some text.\n")
    with pytest.raises(ValidationError):
        load_functional_areas(p)


def test_schema_rejects_empty_areas(tmp_path: Path):
    p = tmp_path / "fa.yml"
    p.write_text("areas: {}\n")
    with pytest.raises(ValidationError):
        load_functional_areas(p)


def test_schema_normalizes_adr_ids(tmp_path: Path):
    p = tmp_path / "fa.yml"
    p.write_text(
        "areas:\n"
        "  caretaking:\n"
        "    label: Caretaking\n"
        "    description: x\n"
        "    related_adrs: ['29', '0049', 'ADR-0032']\n"
    )
    fa = load_functional_areas(p)
    assert fa.areas["caretaking"].related_adrs == [
        "ADR-0029",
        "ADR-0049",
        "ADR-0032",
    ]


def test_real_yaml_passes_schema(real_repo_root: Path):
    """Once Task 4 commits docs/arch/functional_areas.yml, this lights up."""
    p = real_repo_root / "docs/arch/functional_areas.yml"
    if not p.exists():
        pytest.skip("docs/arch/functional_areas.yml not yet authored (Task 4)")
    fa = load_functional_areas(p)
    assert len(fa.areas) >= 1
