"""MockWorld scenario for the Atlas P3 entries-as-evidence flow (ADR-0061).

Verifies the data path Domain/Graph views consume when ?include_entries=true
plus /api/atlas/discovered:

1. Seed two terms; only one references a wiki entry via its evidence list.
2. Seed two wiki entries on disk under config.repo_wiki_path:
   - One referenced by the term (linked).
   - One with no term backlink (orphan / discovered bucket).
3. Hit /api/atlas/graph?include_entries=true. Assert:
   - The linked entry appears as type='entry' attached to the term's
     bounded_context parent, with an 'evidence_for' edge.
   - The orphan entry does NOT appear in the graph payload.
4. Hit /api/atlas/discovered. Assert it contains only the orphan.
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
    TermStore,
)

pytestmark = pytest.mark.scenario_loops


class TestAtlasEntriesAsEvidence:
    def test_graph_separates_linked_from_discovered(self, tmp_path: Path) -> None:
        # 1. Term store with two terms — only EventBus carries an evidence
        # backlink to the linked entry id "0001".
        terms_root = tmp_path / "docs" / "wiki" / "terms"
        store = TermStore(terms_root)
        store.write(
            Term(
                id="01TARGET00000000000000",
                name="EventBus",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="Async pub/sub bus.",
                code_anchor="src/events.py:EventBus",
                confidence="accepted",
                evidence=["0001"],
            )
        )
        store.write(
            Term(
                id="01OTHER000000000000000",
                name="StateTracker",
                kind=TermKind.SERVICE,
                bounded_context=BoundedContext.SHARED_KERNEL,
                definition="Persistence.",
                code_anchor="src/state.py:StateTracker",
                confidence="accepted",
            )
        )

        # 2. Wiki entries on disk — one linked, one orphan.
        config = HydraFlowConfig(repo_root=tmp_path)
        wiki_root = tmp_path / config.repo_wiki_path
        repo_dir = wiki_root / "acme" / "widget"
        (repo_dir / "patterns").mkdir(parents=True)
        (repo_dir / "gotchas").mkdir(parents=True)
        (repo_dir / "patterns" / "0001-issue-10-linked.md").write_text(
            "---\nstatus: active\n---\n\nbody.\n"
        )
        (repo_dir / "gotchas" / "0002-issue-11-orphan.md").write_text(
            "---\nstatus: active\n---\n\nbody.\n"
        )

        state = StateTracker(tmp_path / "state.json")
        bus = EventBus()
        router, _ = make_dashboard_router(config, bus, state, tmp_path)

        # 3. Graph payload with entries.
        graph_endpoint = find_endpoint(router, "/api/atlas/graph", method="GET")
        graph = graph_endpoint(include_entries=True)

        entry_nodes = [n for n in graph["nodes"] if n.get("type") == "entry"]
        # Only the linked entry should land in the graph.
        assert len(entry_nodes) == 1
        linked = entry_nodes[0]
        assert linked["entry_id"] == "0001"
        assert linked["topic"] == "patterns"
        assert linked["parent"] == "shared-kernel"

        ev_edges = [e for e in graph["edges"] if e["kind"] == "evidence_for"]
        assert len(ev_edges) == 1
        assert ev_edges[0]["source"] == linked["id"]
        assert ev_edges[0]["target"] == "01TARGET00000000000000"

        # 4. Discovered endpoint surfaces the orphan and only the orphan.
        discovered_endpoint = find_endpoint(
            router, "/api/atlas/discovered", method="GET"
        )
        orphans = discovered_endpoint()
        orphan_ids = {e["id"] for e in orphans}
        assert orphan_ids == {"0002"}
        assert orphans[0]["topic"] == "gotchas"
