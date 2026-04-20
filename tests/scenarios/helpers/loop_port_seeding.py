"""Shared helper for pre-seeding MockWorld._loop_ports with AsyncMock variants.

Caretaker-loop scenarios need to pre-seed the port dict BEFORE `run_with_loops`
triggers the catalog builder. Builders use `ports.get(key) or MagicMock()` —
if a bare MagicMock is created first, `await mock.async_method()` raises
TypeError. AsyncMock avoids that.
"""

from __future__ import annotations

from typing import Any

from tests.scenarios.fakes.mock_world import MockWorld


def seed_ports(world: MockWorld, **ports: Any) -> None:
    """Pre-seed world._loop_ports with the provided port instances.

    Call BEFORE `await world.run_with_loops(...)`. Any port not seeded
    explicitly will be created as a bare MagicMock by the catalog builder.

    Args:
        world: The MockWorld instance.
        **ports: Keyword arguments mapping port name to instance (typically
            AsyncMock variants for async methods).

    Example:
        seed_ports(world, adr_reviewer=AsyncMock(review_proposed_adrs=AsyncMock(return_value={"filed": 0})))
        await world.run_with_loops(["adr_reviewer"], cycles=1)
    """
    if not hasattr(world, "_loop_ports"):
        world._loop_ports = {}
    for key, value in ports.items():
        world._loop_ports[key] = value
