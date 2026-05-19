"""s22 — CorpusLearningLoop runs with no escape issues and emits a worker-status event.

Golden path: FakeGitHub returns an empty escape-issue list, so the loop
finds no candidates and emits a BACKGROUND_WORKER_STATUS event for
``corpus_learning``, proving caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s22_corpus_learning_no_escape_issues"
DESCRIPTION = (
    "CorpusLearningLoop sees no open escape issues → idle tick, "
    "emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["corpus_learning"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by corpus_learning."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "corpus_learning"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    cl_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "corpus_learning"
    ]
    assert len(cl_events) >= 1, (
        f"Expected at least one corpus_learning worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
