"""s36 — DiscoverPhase with expander wiring runs a happy-path issue to merge.

Golden path (ADR-0063 W3a): a ``hydraflow-ready`` issue flows through
triage → discover (first attempt succeeds) → plan → implement → review →
merged. Proves the discover-expander wiring in ``DiscoverRunner`` does not
crash the happy path. The expander intercept fires only on coherence failure;
this scenario confirms the guard condition is transparent when discovery
succeeds on the first attempt.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s36_discover_expander_recovery"
DESCRIPTION = (
    "DiscoverPhase with expander wiring → happy-path issue reaches merged, "
    "expander guard is transparent."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 1,
                "title": "Add feature X",
                "body": "Implement feature X in src/feature_x.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {1: [{"success": True, "task_count": 1}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}]},
            "review": {1: [{"verdict": "approve", "comments": []}]},
        },
        cycles_to_run=6,
    )


async def assert_outcome(api, page) -> None:
    """Verify the issue reaches merged — discover+expander wiring is transparent."""

    def _has_merged(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != 1:
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
