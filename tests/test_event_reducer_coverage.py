"""Factory validation: every EventType value is handled by the frontend reducer.

Parses ``src/events.py`` for all ``EventType`` enum member string values,
then parses ``src/ui/src/context/HydraFlowContext.jsx`` for:
- Direct ``case 'xxx':`` statements in the reducer
- Event types handled via ``getPipelineAction()`` (mapped to ``WS_PIPELINE_UPDATE``)

Every EventType value must be accounted for in one of those two paths,
or appear in an explicit skip list.

Ref: gh-5906
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# ---------------------------------------------------------------------------
# Events that are intentionally not handled by the main reducer or
# getPipelineAction.  These are events used only for:
# - WebSocket replay / backfill
# - Server-side only (never sent to frontend)
# - Handled by other mechanisms (e.g. direct fetch after event)
# ---------------------------------------------------------------------------
SKIP_LIST: set[str] = {
    # Handled via /api/stats fetch triggered by metrics_update, not direct reducer case
    "memory_sync",
    # Internal verification events consumed server-side only
    "verification_judge",
    # Transcript summaries are embedded in session data, not dispatched separately
    "transcript_summary",
    # Epic progress is fetched via /api/epics endpoint, not reduced directly
    "epic_progress",
    # Visual gate events are handled server-side (screenshot validation)
    "visual_gate",
    # Baseline update events are consumed server-side for policy decisions
    "baseline_update",
    # Crate lifecycle events are consumed by the crate manager, not the dashboard
    "crate_activated",
    "crate_completed",
    # Issue-created events are handled by pipeline snapshot refresh
    "issue_created",
    # CI check events are handled server-side for review phase decisions
    "ci_check",
    # Epic releasing is dispatched via REST (uppercase EPIC_RELEASING), not WS events
    "epic_releasing",
}


def _parse_event_type_values() -> set[str]:
    """Extract all EventType enum member string values from events.py."""
    text = (SRC / "events.py").read_text()
    # Match lines like:  PHASE_CHANGE = "phase_change"
    return set(re.findall(r'=\s*"(\w+)"', text))


def _parse_reducer_cases() -> set[str]:
    """Extract all case 'xxx' strings from the reducer in HydraFlowContext.jsx."""
    path = SRC / "ui" / "src" / "context" / "HydraFlowContext.jsx"
    text = path.read_text()
    # Match: case 'phase_change':  (single-quoted case labels)
    return set(re.findall(r"case\s+'(\w+)'", text))


def _parse_pipeline_action_events() -> set[str]:
    """Extract event types handled by getPipelineAction in HydraFlowContext.jsx."""
    path = SRC / "ui" / "src" / "context" / "HydraFlowContext.jsx"
    text = path.read_text()
    # Match: event.type === 'triage_update'
    return set(re.findall(r"event\.type\s*===\s*'(\w+)'", text))


class TestEventReducerCoverage:
    """Every EventType value must be handled by the frontend."""

    def test_all_event_types_handled(self) -> None:
        event_values = _parse_event_type_values()
        reducer_cases = _parse_reducer_cases()
        pipeline_events = _parse_pipeline_action_events()

        # Events handled by either path
        handled = reducer_cases | pipeline_events

        missing = {v for v in event_values if v not in handled and v not in SKIP_LIST}
        assert not missing, (
            f"EventType values not handled by reducer or getPipelineAction "
            f"(and not in SKIP_LIST): {sorted(missing)}"
        )

    def test_skip_list_entries_are_real_event_types(self) -> None:
        """Ensure skip-list entries refer to actual EventType values."""
        event_values = _parse_event_type_values()
        stale = SKIP_LIST - event_values
        assert not stale, (
            f"SKIP_LIST contains entries that are not real EventType values: {sorted(stale)}"
        )

    def test_skip_list_entries_not_already_handled(self) -> None:
        """Flag skip-list entries that are actually handled (stale skip)."""
        reducer_cases = _parse_reducer_cases()
        pipeline_events = _parse_pipeline_action_events()
        handled = reducer_cases | pipeline_events
        redundant = SKIP_LIST & handled
        # This is a warning, not a failure -- redundant skips are harmless
        # but indicate the skip list needs cleanup.
        if redundant:
            import warnings

            warnings.warn(
                f"SKIP_LIST entries that ARE handled (consider removing): {sorted(redundant)}",
                stacklevel=2,
            )
