"""Per-phase-run tracing context passed from coordinators into runners."""

from __future__ import annotations

from dataclasses import dataclass, replace

# Mapping from runner source identifier to canonical phase name.
# Sources not in this dict pass through verbatim.
_SOURCE_TO_PHASE: dict[str, str] = {
    "implementer": "implement",
    "planner": "plan",
    "reviewer": "review",
    "review_fixer": "review",
    "triage": "triage",
    "decomposition": "triage",
    "hitl": "hitl",
}


def source_to_phase(source: str) -> str:
    """Map a runner source identifier to its canonical phase name."""
    return _SOURCE_TO_PHASE.get(source, source)


@dataclass(frozen=True)
class TracingContext:
    """Per-phase-run state passed from a phase coordinator into its runner.

    The coordinator constructs the initial context after allocating a
    ``run_id`` via ``state.begin_trace_run()``. The runner uses it for
    its main subprocess and calls :meth:`next_subprocess` for each
    skill subprocess it spawns.
    """

    issue_number: int
    phase: str
    source: str
    run_id: int
    subprocess_idx: int = 0

    def next_subprocess(self) -> TracingContext:
        """Return a copy with ``subprocess_idx`` incremented."""
        return replace(self, subprocess_idx=self.subprocess_idx + 1)
