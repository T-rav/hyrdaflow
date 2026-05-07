"""Cassette YAML schema + normalizer registry for fake contract tests.

Spec: docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.2 "Cassette schema".
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class CassetteInput(BaseModel):
    """One-interaction input block."""

    command: str
    args: list[str] = Field(default_factory=list)
    stdin: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class CassetteOutput(BaseModel):
    """One-interaction output block."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""


class Cassette(BaseModel):
    """A single recorded interaction between HydraFlow and a real adapter."""

    adapter: str
    interaction: str
    recorded_at: str
    recorder_sha: str
    fixture_repo: str
    input: CassetteInput
    output: CassetteOutput
    normalizers: list[str] = Field(default_factory=list)

    @field_validator("recorded_at", mode="before")
    @classmethod
    def _coerce_recorded_at(cls, v: object) -> str:
        """yaml.safe_load parses ISO8601 timestamps as datetime — coerce to str."""
        if isinstance(v, datetime | date):
            return v.isoformat()
        return str(v)

    @field_validator("adapter")
    @classmethod
    def _validate_adapter(cls, v: str) -> str:
        if v not in {"github", "git", "docker"}:
            msg = f"adapter must be one of github|git|docker, got {v!r}"
            raise ValueError(msg)
        return v

    @field_validator("normalizers")
    @classmethod
    def _validate_normalizers(cls, v: list[str]) -> list[str]:
        for name in v:
            if name not in NORMALIZERS:
                msg = f"unknown normalizer {name!r}; known: {sorted(NORMALIZERS)}"
                raise ValueError(msg)
        return v


# --- Normalizer registry -----------------------------------------------------

# A normalizer transforms a stdout/stderr string so that volatile bytes
# (e.g. auto-assigned PR numbers, fresh timestamps) collapse to a stable
# token before comparison. Both sides of the replay harness run every
# listed normalizer on both texts before `==`.

_PR_NUMBER_RE = re.compile(
    r"/pull/(\d+)\b|pr[_ -]?(?:number|num)[:= ]+(\d+)\b", re.IGNORECASE
)
_ISO8601_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})\b"
)
_SHORT_SHA_RE = re.compile(r"\b[0-9a-f]{7,12}\b")
# Bare 40-hex git object SHAs (full SHA1). Must be applied before sha:short
# because sha:short's {7,12} boundary would not match a 40-char run, but
# ordering makes the intent explicit.
_LONG_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")


def _norm_pr_number(text: str) -> str:
    return _PR_NUMBER_RE.sub(
        lambda m: m.group(0).replace(m.group(1) or m.group(2), "<PR_NUMBER>"), text
    )


def _norm_iso8601(text: str) -> str:
    return _ISO8601_RE.sub("<ISO8601>", text)


def _norm_short_sha(text: str) -> str:
    return _SHORT_SHA_RE.sub("<SHORT_SHA>", text)


def _norm_long_sha(text: str) -> str:
    return _LONG_SHA_RE.sub("<LONG_SHA>", text)


NORMALIZERS: dict[str, Callable[[str], str]] = {
    "pr_number": _norm_pr_number,
    "timestamps.ISO8601": _norm_iso8601,
    "sha:short": _norm_short_sha,
    "sha:long": _norm_long_sha,
}


def apply_normalizers(text: str, names: list[str]) -> str:
    """Apply each named normalizer to *text* in order; return the result."""
    for name in names:
        text = NORMALIZERS[name](text)
    return text


def load_cassette(path: Path) -> Cassette:
    """Parse a YAML cassette file and return a validated Cassette model."""
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        msg = f"cassette {path} did not parse to a mapping: {type(raw).__name__}"
        raise ValueError(msg)
    return Cassette.model_validate(raw)


def dump_cassette(cassette: Cassette, path: Path) -> None:
    """Serialize *cassette* to YAML at *path*."""
    payload = cassette.model_dump(mode="json")
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
