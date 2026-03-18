"""Pre-built DORA event histories that produce known metric values.

Use these in tests to verify DORATracker computes expected snapshots
from synthetic event streams.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from events import EventType, HydraFlowEvent


def _event(
    event_type: str,
    data: dict | None = None,
    timestamp: datetime | None = None,
) -> HydraFlowEvent:
    ts = timestamp or datetime.now(UTC)
    return HydraFlowEvent(
        type=EventType(event_type),
        timestamp=ts.isoformat(),
        data=data or {},
    )


@dataclass
class DORAScenario:
    """A named event history with expected metric ranges."""

    name: str
    events: list[HydraFlowEvent] = field(default_factory=list)
    min_deploy_freq: float = 0.0
    max_deploy_freq: float = 100.0
    max_change_failure_rate: float = 1.0
    max_rework_rate: float = 1.0


def _build_elite() -> DORAScenario:
    """High frequency, low failure, low rework."""
    now = datetime.now(UTC)
    events: list[HydraFlowEvent] = []
    # 14 merges in 7 days → 2/day
    for i in range(14):
        events.append(
            _event(
                "merge_update",
                {
                    "status": "merged",
                    "issue_created_at": (
                        now - timedelta(days=i % 7 + 1, hours=12)
                    ).isoformat(),
                },
                now - timedelta(days=i % 7, hours=i),
            )
        )
    return DORAScenario(
        name="elite",
        events=events,
        min_deploy_freq=1.5,
        max_change_failure_rate=0.05,
        max_rework_rate=0.05,
    )


def _build_degrading() -> DORAScenario:
    """Some merges with HITL escalations and rework."""
    now = datetime.now(UTC)
    events: list[HydraFlowEvent] = []
    # 5 merges in 7 days
    for i in range(5):
        events.append(
            _event(
                "merge_update",
                {"status": "merged"},
                now - timedelta(days=i + 1),
            )
        )
    # 2 HITL escalations
    for i in range(2):
        events.append(
            _event(
                "hitl_escalation",
                {"issue": 100 + i},
                now - timedelta(days=i + 2),
            )
        )
    # 1 rework event
    events.append(
        _event(
            "phase_change",
            {"rework": True},
            now - timedelta(days=3),
        )
    )
    return DORAScenario(
        name="degrading",
        events=events,
        min_deploy_freq=0.5,
        max_change_failure_rate=0.50,
        max_rework_rate=0.30,
    )


def _build_low() -> DORAScenario:
    """Infrequent merges, high failure rate."""
    now = datetime.now(UTC)
    events: list[HydraFlowEvent] = []
    # 1 merge in 7 days
    events.append(_event("merge_update", {"status": "merged"}, now - timedelta(days=3)))
    # 1 HITL escalation
    events.append(_event("hitl_escalation", {"issue": 200}, now - timedelta(days=2)))
    # 1 rework
    events.append(_event("phase_change", {"rework": True}, now - timedelta(days=1)))
    return DORAScenario(
        name="low",
        events=events,
        min_deploy_freq=0.0,
        max_change_failure_rate=1.0,
        max_rework_rate=1.0,
    )


SCENARIOS: dict[str, DORAScenario] = {
    "elite": _build_elite(),
    "degrading": _build_degrading(),
    "low": _build_low(),
}
