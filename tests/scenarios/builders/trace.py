"""AgentTraceBuilder — scripts phase results for FakeLLM.

Phase 1: scalar result sequences. Phase 2 will add streamed events.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from models import ReviewVerdict
from tests.conftest import (
    PlanResultFactory,
    ReviewResultFactory,
    TriageResultFactory,
    WorkerResultFactory,
)

if TYPE_CHECKING:
    from tests.scenarios.fakes.mock_world import MockWorld


def _triage_factory(*, issue_number: int, success: bool = True, **kw: Any) -> Any:
    return TriageResultFactory.create(issue_number=issue_number, ready=success, **kw)


def _plan_factory(*, issue_number: int, success: bool = True, **kw: Any) -> Any:
    return PlanResultFactory.create(issue_number=issue_number, success=success, **kw)


def _implement_factory(*, issue_number: int, success: bool = True, **kw: Any) -> Any:
    return WorkerResultFactory.create(
        issue_number=issue_number, success=success, commits=1, **kw
    )


def _review_factory(*, issue_number: int, success: bool = True, **kw: Any) -> Any:  # noqa: ARG001
    return ReviewResultFactory.create(
        verdict=ReviewVerdict.APPROVE, merged=True, ci_passed=True, **kw
    )


_PHASE_FACTORIES: dict[str, Any] = {
    "triage": _triage_factory,
    "plan": _plan_factory,
    "implement": _implement_factory,
    "review": _review_factory,
}

# Result specifiers used by preset methods. Each is a ``(kind, kwargs)``
# tuple resolved in ``.at()`` — ``kind`` is "success" | "fail" | "zero_diff"
# and ``kwargs`` is extra factory kwargs (e.g. ``{"error": "credit exhausted"}``).
_SENTINEL_SUCCESS = ("success", {})
_SENTINEL_FAIL = ("fail", {})


@dataclass(frozen=True)
class AgentTraceBuilder:
    """Fluent builder that scripts per-phase LLM results onto a MockWorld."""

    _phase: str | None = None
    _issue_number: int | None = None
    _results: tuple[Any, ...] = field(default_factory=tuple)

    def for_phase(self, phase: str) -> AgentTraceBuilder:
        """Set the target phase. Must be called before .at(world)."""
        if phase not in _PHASE_FACTORIES:
            msg = f"Unknown phase {phase!r}; valid: {sorted(_PHASE_FACTORIES)}"
            raise ValueError(msg)
        return replace(self, _phase=phase)

    def for_issue(self, number: int) -> AgentTraceBuilder:
        """Set the target issue number. Must be called before .at(world)."""
        return replace(self, _issue_number=number)

    def with_result(self, result: Any) -> AgentTraceBuilder:
        """Append a raw result object to the script sequence."""
        return replace(self, _results=(*self._results, result))

    # --- presets ---

    def happy_path(self) -> AgentTraceBuilder:
        """Script a single success result."""
        return replace(self, _results=(_SENTINEL_SUCCESS,))

    def fail_then_succeed(self) -> AgentTraceBuilder:
        """Script a failure followed by a success."""
        return replace(self, _results=(_SENTINEL_FAIL, _SENTINEL_SUCCESS))

    def zero_diff(self) -> AgentTraceBuilder:
        """Script an implement result with zero commits."""
        return replace(self, _results=(("zero_diff",),))

    def credit_exhaustion_then_recovery(self) -> AgentTraceBuilder:
        """Preset: first call fails with a credit-exhaustion error, second succeeds."""
        return replace(
            self,
            _results=(
                ("fail", {"error": "credit exhausted: resume_at pending"}),
                ("success", {}),
            ),
        )

    def hitl_escalation(self, *, reason: str = "escalation") -> AgentTraceBuilder:
        """Preset: single scripted fail tagged as a HITL escalation with ``reason``."""
        return replace(
            self,
            _results=(("fail", {"error": f"hitl: {reason}"}),),
        )

    def parse_error_mid_stream(self) -> AgentTraceBuilder:
        """Preset: single scripted fail simulating an agent-cli parse error."""
        return replace(
            self,
            _results=(("fail", {"error": "agent-cli parse error"}),),
        )

    def at(self, world: MockWorld) -> None:
        """Resolve results and register them with world.set_phase_results."""
        if self._phase is None:
            msg = "AgentTraceBuilder requires .for_phase(...) before .at(world)"
            raise ValueError(msg)
        if self._issue_number is None:
            msg = "AgentTraceBuilder requires .for_issue(N) before .at(world)"
            raise ValueError(msg)

        factory = _PHASE_FACTORIES[self._phase]
        resolved: list[Any] = []

        for r in self._results:
            if isinstance(r, tuple) and len(r) == 2 and r[0] == "success":
                resolved.append(
                    factory(issue_number=self._issue_number, success=True, **r[1])
                )
            elif isinstance(r, tuple) and len(r) == 2 and r[0] == "fail":
                resolved.append(
                    factory(issue_number=self._issue_number, success=False, **r[1])
                )
            elif isinstance(r, tuple) and len(r) == 1 and r[0] == "zero_diff":
                if self._phase == "implement":
                    resolved.append(
                        WorkerResultFactory.create(
                            issue_number=self._issue_number, success=True, commits=0
                        )
                    )
                else:
                    resolved.append(
                        factory(issue_number=self._issue_number, success=True)
                    )
            else:
                resolved.append(r)

        world.set_phase_results(self._phase, self._issue_number, resolved)
