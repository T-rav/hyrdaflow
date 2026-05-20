"""s37 — PlanPhase with touchpoint-expander wiring runs a happy-path issue to merge.

Golden path (ADR-0063 W3b): a ``hydraflow-ready`` issue flows through
triage → discover → plan (first PlanReviewer pass succeeds) → implement →
review → merged. Proves the touchpoint-expander wiring in ``PlanPhase``
does not disrupt the happy path. The expander fires only on first
PlanReviewer failure; this scenario confirms the guard is transparent when
the plan is accepted immediately.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s37_plan_touchpoint_expander_recovery"
DESCRIPTION = (
    "PlanPhase with touchpoint-expander wiring → happy-path plan accepted, "
    "issue reaches merged."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 2,
                "title": "Add feature Y",
                "body": "Implement feature Y in src/feature_y.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {2: [{"success": True, "task_count": 1}]},
            "implement": {2: [{"success": True, "branch": "hf/issue-2"}]},
            "review": {2: [{"verdict": "approve", "comments": []}]},
        },
        cycles_to_run=6,
    )


async def assert_outcome(api, page) -> None:
    """Verify the issue reaches merged — plan touchpoint-expander guard is transparent."""

    def _has_merged(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != 2:
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
