"""s17 — SkillPromptEvalLoop runs with a clean corpus and emits a worker-status event.

Golden path: the loop is wired into the sandbox's caretaker registry.
With no corpus cases to run (corpus runner returns empty list), the loop
finishes with zero drift regressions and zero weak-case issues, emitting
a BACKGROUND_WORKER_STATUS event for ``skill_prompt_eval``.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s17_skill_prompt_eval_clean_corpus"
DESCRIPTION = "SkillPromptEvalLoop fires with empty corpus → emits worker-status event."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["skill_prompt_eval"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by skill_prompt_eval."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "skill_prompt_eval"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    skill_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "skill_prompt_eval"
    ]
    assert len(skill_events) >= 1, (
        f"Expected at least one skill_prompt_eval worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
