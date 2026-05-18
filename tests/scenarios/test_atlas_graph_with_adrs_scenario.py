"""MockWorld scenario for the Atlas P2 graph + ADRs flow (ADR-0060).

Exercises the data path that the Domain/Graph views consume when ADRs
are included:

1. Seed two terms with an edge.
2. Seed two ADRs — one whose '## Related' section references a known
   term by name; one with no related terms.
3. Hit /api/atlas/graph (default include_adrs=True) and assert:
   - Both ADR nodes appear with type='adr' and parent='adrs'.
   - The 'adrs' context is present in `contexts`.
   - A 'relates_to' edge connects the citing ADR to the matched term.
4. Hit /api/atlas/graph?include_adrs=False and assert ADRs are absent.
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


class TestAtlasGraphWithAdrs:
    def test_includes_adr_nodes_and_relates_to_edges(self, tmp_path: Path) -> None:
        terms_root = tmp_path / "docs" / "wiki" / "terms"
        store = TermStore(terms_root)
        target = Term(
            id="01TARGET00000000000000",
            name="EventBus",
            kind=TermKind.SERVICE,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition="Async pub/sub bus.",
            invariants=[],
            code_anchor="src/events.py:EventBus",
            confidence="accepted",
        )
        store.write(target)
        source = Term(
            id="01SOURCE00000000000000",
            name="AgentRunner",
            kind=TermKind.RUNNER,
            bounded_context=BoundedContext.BUILDER,
            definition="Subprocess runner.",
            code_anchor="src/agent.py:AgentRunner",
            related=[TermRel(kind=TermRelKind.DEPENDS_ON, target=target.id)],
            confidence="accepted",
        )
        store.write(source)

        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0042-event-bus.md").write_text(
            "# ADR-0042: EventBus design\n\n"
            "## Status\n\nAccepted\n\n"
            "## Date\n\n2026-01-15\n\n"
            "## Related\n\n- `EventBus` — the bus itself\n"
        )
        (adr_dir / "0050-orphan.md").write_text(
            "# ADR-0050: Orphan ADR\n\n"
            "## Status\n\nAccepted\n\n"
            "## Date\n\n2026-02-15\n\n"
            "## Related\n\n- something unrelated\n"
        )

        config = HydraFlowConfig(repo_root=tmp_path)
        state = StateTracker(tmp_path / "state.json")
        bus = EventBus()
        router, _ = make_dashboard_router(config, bus, state, tmp_path)

        endpoint = find_endpoint(router, "/api/atlas/graph", method="GET")
        assert endpoint is not None
        graph = endpoint()

        adr_nodes = [n for n in graph["nodes"] if n.get("type") == "adr"]
        adr_ids = {n["id"] for n in adr_nodes}
        assert adr_ids == {"adr-42", "adr-50"}
        assert all(n["parent"] == "adrs" for n in adr_nodes)
        assert "adrs" in {c["id"] for c in graph["contexts"]}

        relates = [e for e in graph["edges"] if e["kind"] == "relates_to"]
        assert any(
            e["source"] == "adr-42" and e["target"] == target.id for e in relates
        )
        assert all(e["source"] != "adr-50" for e in relates)

    def test_excludes_adrs_when_disabled(self, tmp_path: Path) -> None:
        terms_root = tmp_path / "docs" / "wiki" / "terms"
        store = TermStore(terms_root)
        store.write(
            Term(
                id="01TARGET00000000000000",
                name="EventBus",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="x",
                code_anchor="src/events.py:EventBus",
                confidence="accepted",
            )
        )
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0042-x.md").write_text(
            "# ADR-0042: X\n\n## Status\n\nAccepted\n\n## Related\n\n- `EventBus`\n"
        )

        config = HydraFlowConfig(repo_root=tmp_path)
        state = StateTracker(tmp_path / "state.json")
        bus = EventBus()
        router, _ = make_dashboard_router(config, bus, state, tmp_path)

        endpoint = find_endpoint(router, "/api/atlas/graph", method="GET")
        result = endpoint(include_adrs=False)

        assert all(n.get("type") != "adr" for n in result["nodes"])
        assert "adrs" not in {c["id"] for c in result["contexts"]}
