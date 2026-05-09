# ADR-0060: Atlas — Graph View, ADR Nodes, and Term Provenance

## Status

Accepted

## Date

2026-05-09

## Enforced by

`tests/test_atlas_routes.py`, `src/ui/src/components/atlas/__tests__/`

## Context

[ADR-0059](0059-atlas-knowledge-graph-dashboard.md) shipped Atlas Phase 1: a `Domain` view rendering the ubiquitous-language term graph as React Flow parent-grouped nodes, an `Articles` browser unifying ADRs and wiki entries, and a `Maintenance` panel. Five new term + ADR endpoints exposed the data.

Phase 1 deferred three pieces of value that the dataset is now ready to absorb:

1. ADRs are listed in Articles but invisible in the graph itself — there's no way to see which terms an ADR governs without reading prose.
2. The ubiquitous-language vocabulary now contains both hand-authored terms and proposer-generated ones (`TermProposerLoop`, ADR-0054), but the term detail panel doesn't surface that provenance — every term looks identical regardless of how it entered the glossary.
3. The grouped layout is good for "what belongs where" but cannot reveal cross-context hubs or dependency clusters; with terms + ADRs combined the dataset is finally large enough that a force-directed layout earns its space.

## Decision

Phase 2 adds three peer surfaces inside Atlas, all driven by the existing `TermStore`, `docs/adr/*.md`, and the running term-loop telemetry — no new persistence.

### A new `Graph` sub-tab

`AtlasExplorer` grows a fourth sub-tab between `Domain` and `Articles`:

```
┌─ Atlas ──────────────────────────────────────────────────────────┐
│  ▸ Domain (default)   ▸ Graph   ▸ Articles   ▸ Maintenance       │
└──────────────────────────────────────────────────────────────────┘
```

`Graph` and `Domain` share data and selection state through `AtlasExplorer`. They differ only in *layout*:
- `Domain` keeps its parent-grouped layout (good for "what belongs where").
- `Graph` runs a `d3-force` (`~30 KB` gz) simulation over the same `nodes`/`edges` payload, free-floating, color-coded by `bounded_context` (good for "what's a hub vs. leaf, where does data flow").

A new hook, `useGraphLayout(payload, mode)` with `mode: 'domain' | 'force'`, returns positioned nodes for either view from a single source. `DomainView` is refactored to consume the hook so the chassis is shared.

### ADRs as graph nodes

`/api/atlas/graph` gains an `?include_adrs` query param (default `true` once this lands). When set:
- ADR nodes appear in the payload alongside terms. ADR nodes are rendered with a distinct shape (rectangle vs. term ellipse) and a neutral grey to recede visually.
- Edges are inferred by parsing each ADR's `## Related` section: any line that matches a known term `name` or `alias` produces an `ADR → Term` edge with kind `relates_to`.

Clicking an ADR node opens an `AdrDetailPanel` (markdown body via `react-markdown`), reusing the same shell as `TermDetailPanel`. The shared chassis lives in a new `DetailPanel` wrapper that routes to the right panel by node `type`.

### Term provenance on the detail panel

`/api/atlas/terms/{id}` adds the existing-but-unused fields from the `Term` Pydantic model:

```
proposed_by, proposed_at, proposal_signals, proposal_imports_seen
```

These fields are populated by `TermProposerLoop` and are `None` for hand-authored terms. The `TermDetailPanel` gains a **Provenance** section — hidden when `proposed_by` is null, otherwise rendering "Proposed by `TermProposerLoop` on 2026-05-09 — signals: S1, S2 — imports seen: 12".

A new **Confidence** filter chip joins `kind` and `bounded_context` in both `Domain` and `Graph` views (options: `accepted` (default on), `proposed`, `deprecated`). Combined via AND with the other filters.

### Term-loops telemetry in Maintenance

A new endpoint `GET /api/atlas/term-loops/status` reads from the orchestrator's loop registry and returns the last-tick timestamp, last-PR URL, and last-action count for `TermProposerLoop` (ADR-0054), `TermPrunerLoop` (ADR-0057), and `EdgeProposerLoop` (ADR-0058). The Maintenance sub-tab gains a third card consuming this endpoint, putting the dark-factory's glossary work in the operator's eyeline next to the wiki maintenance run-status.

## Consequences

- The graph payload schema gains an optional `type: 'term' | 'adr'` discriminator on nodes; existing P1 consumers default to `'term'` if absent.
- The frontend gains `d3-force` as a new dependency.
- The `TermDetailPanel` UI grows by one optional section; existing P1 tests keep passing because the section is hidden for hand-authored terms (the only kind the test fixtures use today).
- Phase 3 (entries-as-evidence + Discovered bucket) builds on the same `useGraphLayout` chassis without further core refactor.

## Alternatives considered

- **Auto-merge `Graph` and `Domain` into one toggle on a single view.** Rejected: distinct sub-tabs preserve URL state separation (planned in P4 deep links) and let users switch lenses without losing selection context.
- **Force layout via Cytoscape instead of d3-force.** Rejected: Cytoscape would replace React Flow as the canvas and force a re-render of `Domain` too. d3-force computes positions only; React Flow keeps rendering the result identically across both views.
- **Use a separate ADR endpoint to avoid mutating `/api/atlas/graph`.** Rejected: the frontend would need to merge two payloads on every render and re-implement the cross-type edge-resolution logic that the server already has the dataset to compute once.

## Related

- [ADR-0059](0059-atlas-knowledge-graph-dashboard.md) — Atlas Phase 1
- [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) — UL terms
- [ADR-0054](0054-term-auto-proposer-loop.md) — `TermProposerLoop`
- [ADR-0057](0057-term-pruner-loop.md) — `TermPrunerLoop`
- [ADR-0058](0058-edge-proposer-loop.md) — `EdgeProposerLoop`
- `src/dashboard_routes/_atlas_routes.py` — endpoints
- `src/ui/src/components/atlas/` — Atlas UI
- `docs/superpowers/specs/2026-05-08-atlas-design.md` — multi-phase spec
