"""s11 — FakeLLM raises CreditExhaustedError → outer loop suspends."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s11_credit_exhaustion_suspends_ticking"
DESCRIPTION = "Credit exhausted -> suspension -> System tab alert (proves reraise_on_credit_or_bug)."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]}
        ],
        scripts={
            # Special sentinel: the FakeLLM raises CreditExhaustedError on first call.
            "plan": {1: [{"raise": "CreditExhaustedError"}]},
        },
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    state = await api.wait_until(
        "/api/state",
        lambda p: p.get("credits_paused") is True,
        timeout=30.0,
    )
    assert state["credits_paused"] is True

    await page.goto("/")
    await page.click("text=System")
    alert = page.locator("[data-testid='credit-exhausted-alert']")
    assert await alert.is_visible()
