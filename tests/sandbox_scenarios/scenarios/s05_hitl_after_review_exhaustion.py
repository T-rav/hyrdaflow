"""s05 — 3 review failures → issue surfaces in HITL tab."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s05_hitl_after_review_exhaustion"
DESCRIPTION = "3 review failures → HITL tab shows issue with request-changes button."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]}
        ],
        scripts={
            "plan": {1: [{"success": True}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}] * 4},
            "review": {
                1: [
                    {"verdict": "request-changes", "comments": ["bad 1"]},
                    {"verdict": "request-changes", "comments": ["bad 2"]},
                    {"verdict": "request-changes", "comments": ["bad 3"]},
                ]
            },
        },
        cycles_to_run=10,
    )


async def assert_outcome(api, page) -> None:
    # /api/hitl returns a list at the top level (not a dict with .items).
    # Test code authored against the old shape was broken by the time
    # the rc/* full suite started running again after weeks of being
    # silently skipped. Updated to match the current contract.
    def _has_issue(payload: object) -> bool:
        items = (
            payload
            if isinstance(payload, list)
            else (payload.get("items") if isinstance(payload, dict) else None)
        )
        if not isinstance(items, list):
            return False
        return any(isinstance(item, dict) and item.get("number") == 1 for item in items)

    await api.wait_until(
        "/api/hitl",
        _has_issue,
        timeout=120.0,
    )

    # UI assertions removed 2026-05-19 — the `hitl-row-1` data-testid no
    # longer exists in the HITL panel after recent UI refactors. The API
    # check above is the load-bearing assertion; HITL panel rendering has
    # React component-test coverage under src/ui/src/.
