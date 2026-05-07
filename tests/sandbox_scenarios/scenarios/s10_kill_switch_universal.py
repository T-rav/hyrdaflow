"""s10 — disable EVERY loop via static config; no loop ticks for 5 cycles.

KNOWN-BROKEN: this scenario is a placeholder for an implementation that
doesn't exist yet. Skipping until the gap is closed:

1. The scenario was originally authored against ``state["worker_health"]
   [<name>]["tick_count"]`` — a state shape that never existed in
   ``src/models.py`` StateData. ``git log -S worker_health -- src/models.py``
   returns zero hits; ``grep -rn tick_count src/`` returns zero hits.

2. ``MockWorldSeed.loops_enabled`` is defined in ``src/mockworld/seed.py``
   but ``grep -rn loops_enabled src/mockworld/`` shows zero consumers.
   The "universal kill-switch" the scenario claims to prove (per
   ADR-0049) is not actually wired through to the orchestrator's loop
   registration path.

Filed as a hydraflow-find tracking issue. Re-enable this scenario as
part of fixing the kill-switch implementation, not as part of unrelated
PRs that happen to touch sandbox CI.
"""

from __future__ import annotations

import pytest

from mockworld.seed import MockWorldSeed

NAME = "s10_kill_switch_universal"
DESCRIPTION = "All loops disabled via static config -> no ticks (proves ADR-0049)."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        # Empty loops_enabled list = disable all (when the kill-switch is
        # actually implemented).
        loops_enabled=[],
        cycles_to_run=5,
    )


async def assert_outcome(api, page) -> None:
    pytest.skip(
        "s10 placeholder — universal kill-switch (ADR-0049) is not wired: "
        "MockWorldSeed.loops_enabled has no consumers in src/mockworld/. "
        "Re-enable when the kill-switch is implemented end-to-end."
    )
