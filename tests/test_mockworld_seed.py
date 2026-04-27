"""MockWorldSeed — serializable initial state for a sandbox scenario."""

from __future__ import annotations

import json

from mockworld.seed import MockWorldSeed


def test_default_seed_is_empty() -> None:
    seed = MockWorldSeed()
    assert seed.repos == []
    assert seed.issues == []
    assert seed.prs == []
    assert seed.scripts == {}
    assert seed.cycles_to_run == 4
    assert seed.loops_enabled is None


def test_seed_round_trips_through_json() -> None:
    original = MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[{"number": 1, "title": "t", "body": "b", "labels": ["x"]}],
        scripts={"plan": {1: [{"success": True}]}},
        cycles_to_run=10,
        loops_enabled=["triage_loop"],
    )

    raw = original.to_json()
    parsed = MockWorldSeed.from_json(raw)

    assert parsed == original


def test_seed_json_is_valid_json() -> None:
    seed = MockWorldSeed(issues=[{"number": 1}])
    raw = seed.to_json()
    parsed = json.loads(raw)
    assert parsed["issues"] == [{"number": 1}]
