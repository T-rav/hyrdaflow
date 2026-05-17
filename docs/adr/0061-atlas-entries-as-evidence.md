# ADR-0061: Atlas — Wiki Entries as Term Evidence + Discovered Bucket

## Status

Accepted

## Date

2026-05-09

## Enforced by

`tests/test_atlas_routes.py`, `src/ui/src/components/atlas/__tests__/`

## Context

[ADR-0059](0059-atlas-knowledge-graph-dashboard.md) shipped the Atlas dashboard with a unified `Articles` browser that lists ADRs and wiki entries side-by-side. [ADR-0060](0060-atlas-graph-view-and-provenance.md) added ADR nodes to the graph with `relates_to` edges to terms.

Wiki entries — bot-generated knowledge nuggets captured by `RepoWikiLoop` from review escalations, gotchas, patterns, etc. — are still graph-invisible. The `Term` Pydantic model has carried an `evidence: list[str]` field since [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) and a one-shot migration script (`scripts/migrate_entries_to_term_evidence.py`) populates it via LLM matching, but the dashboard does nothing with it.

This ADR closes that loop. Wiki entries become a third node type in the graph, attached to the term(s) they document. Entries with no term link form a virtual "Discovered" subgraph — visually distinct, but discoverable, so they can be triaged into terms manually or by the next migration run.

## Decision

### Entries as graph nodes

`/api/atlas/graph` gains `?include_entries=true|false` (default `false` for backward compatibility — flips to `true` once the UI ships). When enabled:

- Each wiki entry that appears in some term's `evidence` list is emitted as a node with `type: 'entry'` and `parent: <term_context>` (so it lives inside the same parent box as the term it documents).
- An `evidence_for` edge connects each entry node to its term node.
- Entry nodes are visually smaller than term nodes — they are leaves, not concepts.

### Discovered bucket

A new `GET /api/atlas/discovered` returns wiki entries that no term references. The frontend renders these inside a virtual `discovered` parent context — dashed grey border, lower opacity — so the operator can see what knowledge the term proposer hasn't classified yet.

### Term detail panel evidence list

`TermDetailPanel` already had an "Evidence (P3 — 0 today)" placeholder. P3 replaces the placeholder with a real list: each linked entry rendered as a clickable row that selects the entry node in the graph (or, in P4, deep-links to the article view).

### Articles "Linked to term" facet

The unified Articles list gains a third filter dimension alongside `Type` and the wiki filters: `All / Linked / Discovered`. When set to "Linked" only entries that some term references survive; when "Discovered" only the orphans remain.

## Consequences

- The graph payload schema gains a `type: 'entry'` discriminator. P1/P2 consumers that check `type === 'term'` already coexist with the P2 ADR addition; entries follow the same pattern.
- `include_entries=false` remains available as an escape hatch for callers that want a smaller payload.
- Phase 4 (polish) builds on the same selection-routing chassis; clicking an entry node will deep-link to its Articles row.
- The migration script run remains a separate operational step (or, eventually, an autonomous loop). This ADR specifies how the dashboard surfaces what's already in the data — not when the data is computed.

## Alternatives considered

- **Treat entries as edges, not nodes.** Rejected: an entry can document multiple terms (1:N), so an edge model needs join nodes anyway, and entries carry their own selectable detail (the markdown body) which a pure-edge representation hides.
- **Keep entries hidden, surface only via the Articles list.** Rejected: the user's original goal was to make the term graph navigable to the knowledge that justifies it. Hiding entries from the graph defeats that.
- **Auto-classify orphan entries into a term inferred at render time.** Rejected: the migration script already exists, runs on a schedule, and can apply LLM judgment. Re-running that logic in the dashboard would duplicate cost and produce inconsistent results vs. the persisted evidence list.

## Related

- [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) — UL terms + `evidence` field
- [ADR-0054](0054-term-auto-proposer-loop.md) — `TermProposerLoop`
- [ADR-0059](0059-atlas-knowledge-graph-dashboard.md) — Atlas Phase 1
- [ADR-0060](0060-atlas-graph-view-and-provenance.md) — Atlas Phase 2 (graph + ADR nodes)
- `scripts/migrate_entries_to_term_evidence.py` — entry→term linker
- `src/repo_wiki.py` — `RepoWikiStore`, `WikiEntry`
