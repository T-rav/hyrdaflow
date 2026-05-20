"""s40 — ImplementPhase with two-stage spec-compliance review wiring runs a happy-path issue to merge.

Golden path (ADR-0063 W5): a ``hydraflow-ready`` issue flows through
triage → discover → shape → plan → implement (first attempt succeeds) →
spec-compliance review (guard: ``implement_two_stage_review_enabled`` is
False by default so the reviewer is skipped) → review → merged. Proves the
two-stage review wiring in ``ImplementPhase`` does not crash the happy path.
The spec-compliance review fires only when enabled and the diff passes;
this scenario confirms the phase advances correctly regardless.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s40_implement_two_stage_review_gap_feed"
DESCRIPTION = (
    "ImplementPhase with two-stage review wiring → happy-path implement "
    "succeeds, issue reaches merged."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 4,
                "title": "Add feature W",
                "body": "Implement feature W in src/feature_w.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {4: [{"success": True, "task_count": 1}]},
            "implement": {4: [{"success": True, "branch": "hf/issue-4"}]},
            "review": {4: [{"verdict": "approve", "comments": []}]},
        },
        cycles_to_run=6,
    )


async def assert_outcome(api, page) -> None:
    """Verify the issue reaches merged — implement two-stage review guard is transparent."""

    def _has_merged(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != 4:
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
