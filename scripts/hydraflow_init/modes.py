"""Decide whether a repo is greenfield or adopting incrementally.

Greenfield: a project with no HydraFlow scaffolding at all. Most P1 (docs),
P3 (testing), P4 (quality), P5 (CI) checks will FAIL. The prompt starts
with `superpowers:brainstorming` because the team has not yet decided what
shape this project should take — jumping straight to a plan would bake in
defaults that the user never chose.

Incremental: a project with the skeleton in place but individual checks
failing. Brainstorming would waste the user's time; go straight to
`superpowers:writing-plans` for the failing principles.

The threshold (70% FAIL in structural checks) is deliberately strict. A
repo at 40% FAIL still has enough bones to reason about; a repo at 80%
FAIL has almost nothing to anchor a plan against.
"""

from __future__ import annotations

from enum import StrEnum


class Mode(StrEnum):
    GREENFIELD = "greenfield"
    INCREMENTAL = "incremental"


_GREENFIELD_STRUCTURAL_FAIL_RATIO = 0.7


def decide(findings: list[dict]) -> Mode:
    structural = [f for f in findings if f.get("severity") == "STRUCTURAL"]
    if not structural:
        return Mode.INCREMENTAL
    fails = [f for f in structural if f.get("status") == "FAIL"]
    ratio = len(fails) / len(structural)
    return (
        Mode.GREENFIELD
        if ratio >= _GREENFIELD_STRUCTURAL_FAIL_RATIO
        else Mode.INCREMENTAL
    )
