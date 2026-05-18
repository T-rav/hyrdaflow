"""MockWorld scenario for the Atlas dashboard surface (ADR-0059).

Exercises the API + the data flow that the Domain view relies on, end-to-end:
1. Seed a tracked docs/wiki/terms/ tree with two terms and an edge.
2. Hit /api/atlas/graph — the payload Domain consumes on mount.
3. Hit /api/atlas/terms/{id} for the AgentRunner node — the payload TermDetailPanel
   consumes on click.
4. Assert the payload shapes match what the UI components require, including
   that target_name resolves correctly across the edge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import HydraFlowConfig
from events import EventBus
from state import StateTracker
from tests.helpers import find_endpoint, make_dashboard_router
from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermRel,
    TermRelKind,
    TermStore,
)

pytestmark = pytest.mark.scenario_loops


class TestAtlasUserFlow:
    """User opens Atlas → graph payload arrives → click → detail arrives."""

    def test_graph_then_detail_for_agent_runner(self, tmp_path: Path) -> None:
        terms_root = tmp_path / "docs" / "wiki" / "terms"
        store = TermStore(terms_root)
        target = Term(
            id="01TARGET00000000000000",
            name="EventBus",
            kind=TermKind.SERVICE,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="Async pub/sub bus.",
            invariants=["Bounded history."],
            code_anchor="src/events.py:EventBus",
            confidence="accepted",
        )
        store.write(target)
        source = Term(
            id="01SOURCE00000000000000",
            name="AgentRunner",
            kind=TermKind.RUNNER,
            bounded_context=BoundedContext.BUILDER,
            definition="Subprocess runner for the implement phase.",
            invariants=["_phase_name == 'implement'."],
            code_anchor="src/agent.py:AgentRunner",
            related=[TermRel(kind=TermRelKind.DEPENDS_ON, target=target.id)],
            confidence="accepted",
        )
        store.write(source)

        config = HydraFlowConfig(repo_root=tmp_path)
        state = StateTracker(tmp_path / "state.json")
        bus = EventBus()
        router, _ = make_dashboard_router(config, bus, state, tmp_path)

        graph_endpoint = find_endpoint(router, "/api/atlas/graph", method="GET")
        graph = graph_endpoint()
        agent_node = next(n for n in graph["nodes"] if n["name"] == "AgentRunner")
        assert agent_node["parent"] == "builder"
        assert any(
            e["source"] == source.id
            and e["target"] == target.id
            and e["kind"] == "depends_on"
            for e in graph["edges"]
        )

        detail_endpoint = find_endpoint(
            router, "/api/atlas/terms/{term_id}", method="GET"
        )
        detail = detail_endpoint(term_id=source.id)
        assert detail["name"] == "AgentRunner"
        assert detail["definition"].startswith("Subprocess runner")
        assert len(detail["edges"]) == 1
        assert detail["edges"][0]["target_name"] == "EventBus"
