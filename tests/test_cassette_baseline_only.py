"""Regression: github cassettes carry ``baseline_only: true`` (Phase 4 of #8786).

The marker is the machine-checkable retirement signal — when a
``LiveCorpusReplayLoop`` dispatcher covers the same shape, the
baseline cassette is redundant and a future audit can flag it. Until
then the marker just documents the corpus as hand-authored.

This test guards against:
- New github cassettes landing without the marker.
- A future PR accidentally flipping all markers off in bulk.
- The schema field disappearing.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from contracts._schema import Cassette

_GH_CASSETTES = Path(__file__).parent / "trust" / "contracts" / "cassettes" / "github"


def test_every_github_cassette_is_baseline_only() -> None:
    """Every YAML cassette under cassettes/github/ must carry
    ``baseline_only: true``. New cassettes without it suggest the author
    is recording live (which github currently does NOT do — see the
    cassette dir README)."""
    yamls = list(_GH_CASSETTES.glob("*.yaml"))
    assert yamls, "expected at least one github cassette"
    missing: list[str] = []
    for path in yamls:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if raw.get("baseline_only") is not True:
            missing.append(path.name)
    assert not missing, (
        "the following github cassettes are missing `baseline_only: true`: "
        f"{missing}. See cassettes/github/README.md for the retirement plan."
    )


def test_cassette_schema_round_trips_baseline_only() -> None:
    """The Cassette pydantic model preserves baseline_only on dump."""
    raw = {
        "adapter": "github",
        "interaction": "merge_pr",
        "recorded_at": "2026-05-13T00:00:00Z",
        "recorder_sha": "00000000",
        "fixture_repo": "x/y",
        "input": {"command": "merge_pr", "args": ["42"], "stdin": None, "env": {}},
        "output": {"exit_code": 0, "stdout": "", "stderr": ""},
        "normalizers": [],
        "baseline_only": True,
    }
    cassette = Cassette.model_validate(raw)
    assert cassette.baseline_only is True
    dumped = cassette.model_dump()
    assert dumped["baseline_only"] is True


def test_cassette_schema_defaults_baseline_only_false() -> None:
    """Default is False so existing live-recorded cassettes (git, docker,
    claude) don't suddenly claim to be baselines."""
    raw = {
        "adapter": "git",
        "interaction": "commit",
        "recorded_at": "2026-05-13T00:00:00Z",
        "recorder_sha": "abc1234",
        "fixture_repo": "x/y",
        "input": {"command": "commit", "args": ["initial"], "stdin": None, "env": {}},
        "output": {"exit_code": 0, "stdout": "[main abc1234] initial\n", "stderr": ""},
        "normalizers": ["sha:short"],
    }
    cassette = Cassette.model_validate(raw)
    assert cassette.baseline_only is False
