"""s39 — ShapePhase with diversified-council round-3 wiring runs a happy-path issue to plan.

Golden path (ADR-0063 W4): a ``hydraflow-ready`` issue flows through
triage → discover → shape (first council vote converges) → plan → implement
→ review → merged. Proves the round-3 diversified-persona wiring in
``ShapePhase`` does not disrupt the happy path. Round 3 fires only when
rounds 1 and 2 both split; this scenario confirms the guard condition is
transparent when the council converges in round 1.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s39_shape_council_round_3_convergence"
DESCRIPTION = (
    "ShapePhase with council round-3 wiring → happy-path council converges, "
    "issue reaches merged."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 3,
                "title": "Add feature Z",
                "body": "Implement feature Z in src/feature_z.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {3: [{"success": True, "task_count": 1}]},
            "implement": {3: [{"success": True, "branch": "hf/issue-3"}]},
            "review": {3: [{"verdict": "approve", "comments": []}]},
        },
        cycles_to_run=6,
    )


async def assert_outcome(api, page) -> None:
    """Verify the issue reaches merged — shape round-3 guard is transparent."""

    def _has_merged(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != 3:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    await api.wait_until(
        "/api/issues/history?limit=500",
        _has_merged,
        timeout=60.0,
    )
