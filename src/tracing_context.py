"""Per-phase-run tracing context passed from coordinators into runners."""

from __future__ import annotations

from dataclasses import dataclass

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

    The coordinator constructs a context after allocating a ``run_id`` via
    ``state.begin_trace_run()``. The ``subprocess_idx`` for each individual
    ``_execute`` call within the run is allocated by the runner from a
    monotonic counter (see ``BaseRunner._allocate_trace_subprocess_idx``);
    it is **not** carried on the context, because skills, pre-quality
    review loops, and quality fix loops all spawn additional subprocesses
    that need unique indices to avoid overwriting each other's traces.
    """

    issue_number: int
    phase: str
    source: str
    run_id: int
