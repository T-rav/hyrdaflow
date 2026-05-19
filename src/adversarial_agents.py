"""Shared Protocol + types for adversarial-pipeline agent adapters.

The earlier-adversarial pipeline (AssumptionSurfacer, PlanCouncil,
SpecACGenerator, SpecJudge) each take an agent satisfying the same
two-string-in, JSON-string-out contract. Extracting that Protocol once
keeps the four adversarial stages testable with a single fake.

Per Task 5/6 reflections this is the natural extraction point. No
behavior change — just a shared Protocol so call sites can type against
``AgentLike`` from one place.
"""

from __future__ import annotations

from typing import Protocol


class AgentLike(Protocol):
    """Two-string-in, string-out adversarial-stage agent contract.

    Implementations return a JSON-encoded string. Each adversarial-stage
    adapter is responsible for parsing the JSON and turning failures into
    soft outputs (empty findings list or synthetic high-severity
    concern) so a malformed agent reply never crashes the wiring.
    """

    async def run(self, system_prompt: str, user_message: str) -> str: ...
