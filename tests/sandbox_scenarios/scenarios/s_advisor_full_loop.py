"""s_advisor_full_loop — advisor pattern end-to-end (Tier-2).

T23 of the advisor-pattern feature, activated by T34. Tier-2 parity for
``tests/scenarios/test_pr_review_advisor_happy_path.py`` per ADR-0052
rule 3 (every sandbox scenario has a Tier-1 parity test).

End-to-end flow
---------------

1. ``seed()`` registers issue 7 ("Add advisor wiring") with
   hydraflow-ready, plus plan/implement/review scripts that drive the
   in-process parity test (``tests/scenarios/test_sandbox_parity.py``)
   past ``queued`` — Tier-1 passes today with no advisor wiring needed.
2. The seed also carries an ``advisor_scripts`` entry that the Tier-2
   loader hands to ``FakeLLM.script_advisor(7, "post_verify", [...])``.
3. Tier-2 (sandbox) flow expects the executor to APPROVE and the
   PostVerifyAdvisor to APPROVE, ending with PR merged. The
   ``review_advisor`` worker card on the System tab proves the
   ``BACKGROUND_WORKERS`` registration (src/ui/src/constants.js) is
   rendered by the live stack.

T34 closed the two infrastructure gaps T23 left open:

a. ``src/mockworld/sandbox_main.py`` now sets
   ``svc.reviewers._mockworld_fake_llm = fake_llm`` so the
   ``_PostVerifyRunner`` adapter routes advisor consults to FakeLLM
   instead of spawning a real Claude subprocess (which fails under the
   air-gapped sandbox network).

b. ``MockWorldSeed`` now carries an ``advisor_scripts`` field and
   ``sandbox_main`` invokes ``FakeLLM.script_advisor(issue, role,
   results)`` for each entry. The 2-arg loader for ``seed.scripts``
   couldn't carry the role axis advisor calls require.
"""

from __future__ import annotations

import json
from typing import Any

from mockworld.seed import MockWorldSeed

NAME = "s_advisor_full_loop"
DESCRIPTION = (
    "Advisor pattern end-to-end: executor APPROVE + post-verify advisor APPROVE → "
    "PR merged + review_advisor worker card visible on the System tab."
)


# Scripted advisor verdict. Pinned at module scope so the shape stays
# next to the seed and is reviewable in isolation.
_ADVISOR_POST_VERIFY_APPROVE: str = json.dumps(
    {
        "verdict": "APPROVE",
        "reasoning": "Executor verdict matches diff intent.",
        "disagreements": [],
        "suggested_fix_direction": None,
    }
)


def seed() -> MockWorldSeed:
    """Drive a single issue through the full pipeline + advisor APPROVE.

    The plan/implement/review scripts drive Tier-1 (parity) past
    ``queued`` without touching the advisor seam. The ``advisor_scripts``
    entry queues the post-verify APPROVE that Tier-2 (sandbox) consumes
    via ``FakeLLM.script_advisor`` in ``mockworld.sandbox_main``.
    """
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 7,
                "title": "Add advisor wiring",
                "body": "Wire PostVerifyAdvisor into ReviewPhase",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {7: [{"success": True, "task_count": 1}]},
            "implement": {7: [{"success": True, "branch": "hf/issue-7"}]},
            "review": {7: [{"verdict": "approve", "comments": []}]},
        },
        advisor_scripts={
            7: {"post_verify": [_ADVISOR_POST_VERIFY_APPROVE]},
        },
        cycles_to_run=4,
    )


async def assert_outcome(api: Any, page: Any) -> None:
    """End-to-end assertions: API confirms merged + UI renders advisor card.

    The Tier-2 surface only exposes API/UI affordances (no FakeLLM
    introspection over HTTP). The advisor's involvement is asserted
    indirectly: if the post_verify advisor hadn't APPROVED, the merge
    flow would have stopped short of ``merged``. The ``review_advisor``
    worker card check then proves the backend's loop registration is
    actually wired into the dashboard the operator sees.
    """

    # API assertion — eventually consistent: poll history until issue 7
    # carries an outcome of "merged". Same source of truth as the
    # Outcomes UI tab (IssueHistoryEntry payload).
    def _has_merged_issue_7(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("issue_number") != 7:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    history = await api.wait_until(
        "/api/issues/history?limit=500",
        _has_merged_issue_7,
        timeout=30.0,
    )
    items = history.get("items") if isinstance(history, dict) else None
    assert isinstance(items, list), f"history payload missing items: {history!r}"
    matching = [i for i in items if isinstance(i, dict) and i.get("issue_number") == 7]
    assert matching, f"no issue_number=7 entry in history: {history!r}"
    outcome = matching[0].get("outcome") or {}
    assert outcome.get("outcome") == "merged", (
        f"PR should merge after advisor APPROVE; got {matching[0]!r}"
    )

    # UI assertion — System tab renders the review_advisor worker card.
    # Proves BACKGROUND_WORKERS registration in src/ui/src/constants.js
    # is rendered by the running stack (SystemPanel.jsx emits
    # data-testid="worker-card-${def.key}" per worker).
    await page.goto("/")
    await page.click("text=System")
    card = page.locator("[data-testid='worker-card-review_advisor']")
    await card.wait_for(timeout=10_000)
    assert await card.is_visible()
