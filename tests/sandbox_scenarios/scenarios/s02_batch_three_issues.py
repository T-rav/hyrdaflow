"""s02_batch_three_issues — 3 issues progress in parallel through the pipeline."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s02_batch_three_issues"
DESCRIPTION = "3 issues batch-implemented; Work Stream tab shows all progressing."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": n,
                "title": f"task {n}",
                "body": "b",
                "labels": ["hydraflow-ready"],
            }
            for n in (1, 2, 3)
        ],
        scripts={
            "plan": {n: [{"success": True}] for n in (1, 2, 3)},
            "implement": {
                n: [{"success": True, "branch": f"hf/issue-{n}"}] for n in (1, 2, 3)
            },
            "review": {n: [{"verdict": "approve"}] for n in (1, 2, 3)},
        },
        cycles_to_run=6,
    )


async def assert_outcome(api, page) -> None:
    # /api/timeline/issue/N (IssueTimeline) has no `outcome` field. The
    # dashboard's /api/issues/history endpoint exposes IssueHistoryEntry
    # — same source the Outcomes UI tab consumes. s01_happy_single_issue
    # documents this gotcha and uses the same shape.
    def _merged(payload: dict, n: int) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != n:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    for n in (1, 2, 3):
        await api.wait_until(
            "/api/issues/history?limit=500",
            lambda p, _n=n: _merged(p, _n),
            timeout=60.0,
        )

    # NOTE: the Work Stream tab assertion was removed 2026-05-19. The
    # `[data-testid='stream-issue-N']` selector this test polled never
    # existed in the UI source tree — `grep -r 'stream-issue-'
    # src/ui/src/` returns zero hits, so the assertion would always
    # time out. The merged-outcome history check above is the load-
    # bearing assertion; UI rendering of the Work Stream tab has its
    # own React component tests under src/ui/src/.
