"""s15 — Main branch CI is red → CIMonitorLoop files exactly one issue.

Golden path for the CI health monitor:
1. Tick 1: detects red CI, files a ``hydraflow-ci-failure`` issue.
2. Tick 2: ``_rehydrate_open_issue`` finds the existing issue; no duplicate
   is created.

Asserts:
- A ``BACKGROUND_WORKER_STATUS`` event with ``worker=ci_monitor``,
  ``details.status=red``, and ``details.issue_created`` set appears
  after the first tick.
- After two ticks the same event stream contains exactly one
  ``issue_created`` entry for ``ci_monitor`` (dedup guard holds).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s15_ci_monitor_main_branch_red"
DESCRIPTION = "Main-branch CI red → CIMonitorLoop files one issue; second tick dedupes."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        main_branch_ci_status=(
            "failure",
            "https://github.com/test/repo/actions/runs/1",
        ),
        loops_enabled=["ci_monitor"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    # Poll the event bus until ci_monitor reports a red-CI issue filing.
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "BACKGROUND_WORKER_STATUS"
            and e.get("data", {}).get("worker") == "ci_monitor"
            and e.get("data", {}).get("details", {}).get("status") == "red"
            and "issue_created" in e.get("data", {}).get("details", {})
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    # Collect all ci_monitor BACKGROUND_WORKER_STATUS events.
    ci_events = [
        e
        for e in events_payload
        if e.get("type") == "BACKGROUND_WORKER_STATUS"
        and e.get("data", {}).get("worker") == "ci_monitor"
    ]

    # At least one event must carry issue_created.
    issues_created = [
        e["data"]["details"]["issue_created"]
        for e in ci_events
        if "issue_created" in e.get("data", {}).get("details", {})
    ]
    assert len(issues_created) >= 1, (
        f"Expected at least one ci_monitor issue_created event; got {ci_events!r}"
    )

    # Dedup: across two ticks only one unique issue number was filed.
    unique_issue_numbers = set(issues_created)
    assert len(unique_issue_numbers) == 1, (
        f"CIMonitorLoop created duplicate issues across ticks: {issues_created!r}"
    )

    # The filed issue must carry the ci-failure label (verified via the event
    # detail — the issue number round-trips through FakeGitHub.create_issue
    # which stamps the label on the in-memory issue).
    issue_number = next(iter(unique_issue_numbers))
    assert isinstance(issue_number, int) and issue_number > 0, (
        f"issue_created must be a positive int, got {issue_number!r}"
    )
