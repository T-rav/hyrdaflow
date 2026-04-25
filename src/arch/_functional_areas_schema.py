"""Pydantic schema for docs/arch/functional_areas.yml.

The YAML is the only hand-curated input to the architecture knowledge
system. Every load goes through this schema so a typo or missing field
fails fast with a useful error rather than producing a confusing diff
in the generated Markdown.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class FunctionalArea(BaseModel):
    label: str = Field(min_length=1, description="Display name shown on the site.")
    description: str = Field(
        min_length=1, description="One-paragraph summary of what this area does."
    )
    loops: list[str] = Field(
        default_factory=list,
        description="Class names of loops belonging to this area.",
    )
    ports: list[str] = Field(
        default_factory=list,
        description="Class names of Ports belonging to this area.",
    )
    modules: list[str] = Field(
        default_factory=list,
        description="Path globs (relative to repo root) of modules belonging to this area.",
    )
    related_adrs: list[str] = Field(
        default_factory=list,
        description="ADR ids in 'NNNN' or 'ADR-NNNN' form.",
    )

    @field_validator("related_adrs")
    @classmethod
    def _normalize_adr_ids(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            stripped = raw.strip()
            if not stripped:
                continue
            normalized = (
                stripped if stripped.startswith("ADR-") else f"ADR-{stripped.zfill(4)}"
            )
            out.append(normalized)
        return out


class FunctionalAreas(BaseModel):
    """Top-level structure: `areas: {key: FunctionalArea}`."""

    areas: dict[str, FunctionalArea]

    @field_validator("areas")
    @classmethod
    def _at_least_one_area(
        cls, v: dict[str, FunctionalArea]
    ) -> dict[str, FunctionalArea]:
        if not v:
            raise ValueError("functional_areas.yml must declare at least one area")
        return v


def load_functional_areas(yaml_path: Path) -> FunctionalAreas:
    import yaml

    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"{yaml_path} does not exist")
    with yaml_path.open() as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"{yaml_path}: top-level must be a mapping")
    return FunctionalAreas.model_validate(raw)
