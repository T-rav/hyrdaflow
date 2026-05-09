# ADR-0059: Atlas — Knowledge Graph Dashboard Surface

## Status

Accepted

## Date

2026-05-08

## Enforced by

`tests/test_atlas_routes.py`, `src/ui/src/components/atlas/__tests__/`

## Context

The dashboard "Wiki" tab is a flat list of repo wiki entries with topic + status filters. It surfaces no relationships and no ranking. Meanwhile, ADR-0053 established a structured ubiquitous-language graph in `docs/wiki/terms/` with kinds, bounded contexts, code anchors, and typed edges — but the dashboard does not render it. ADR-0053 explicitly anticipated a follow-up that defines how entries reference terms via `evidence`. This ADR is partly that.

## Decision

Rename the top-level tab `wiki` → `atlas`. Inside Atlas, three sub-tabs share a single `AtlasExplorer` shell:

- **Domain** (default) — interactive node-link diagram of the term graph. Bounded contexts as parent boxes, terms as child nodes, typed edges between them.
- **Articles** — unified browser for ADRs and wiki entries. Top bar has a type filter (All / ADRs / Wiki entries) and existing wiki filters when entries are in scope. List on left shows merged records with a type chip; right pane renders the selected article's markdown body via `react-markdown`.
- **Maintenance** — the existing `WikiMaintenancePanel` hoisted into its own sub-tab with run-status, health, and admin-action surfaces.

Phase 2 introduces ADRs as a second node type and a force-directed Graph sub-tab; Phase 3 adds wiki entries as a third node type with a Discovered bucket for unlinked entries. Each phase ships independently.

The graph renders via `@xyflow/react` (~150KB gz). Bounded contexts use React Flow's first-class `parent` node grouping. Hand-tuned static positions for P1's 11 terms; auto-layout (`dagre`) lands in Phase 2 alongside the larger ADR dataset.

The new API surface lives in `src/dashboard_routes/_atlas_routes.py` and reads from the existing `TermStore` and `docs/adr/*.md`. No new persistence.

Backward compat: `?tab=wiki` query params and stored selections coerce to `'atlas'` on read.

## Consequences

- The existing `src/ui/src/components/wiki/` directory remains in P1 (composed by `ArticlesView` for the entry list + `MaintenanceView` for the panel). P4 removes `wiki/` once Atlas is the sole surface and the merged article shape has stabilized.
- `_wiki_routes.py` is unchanged in P1. Articles uses both `/api/wiki/repos/.../entries` (existing) and `/api/atlas/adrs` (new in P1, Tasks 14 + 15).
- "Atlas" and "System Map" coexist as complementary surfaces (interactive in-dashboard navigator vs. static auto-generated arch site). They are not duplicates.

## Alternatives considered

- **Replace wiki entries with terms entirely.** Rejected: today's entries have no term link; they would orphan.
- **Static Mermaid render in the existing tab.** Rejected: no interaction model, no side-panel selection.
- **Keep "Wiki" as the tab name.** Rejected: the new surface no longer maps to the wiki concept; "Atlas" frames it as a navigable reference.

## Related

- ADR-0032 — per-repo wiki knowledge base
- ADR-0053 — ubiquitous language as living artifact
- ADR-0054 — term auto-proposer loop
- ADR-0057 — term pruner loop
- ADR-0058 — edge proposer loop
- `src/ubiquitous_language.py` — `TermStore`, `Term`, `TermRel`
- `docs/wiki/terms/` — current 11 seed terms
- `docs/superpowers/specs/2026-05-08-atlas-design.md` — design spec
