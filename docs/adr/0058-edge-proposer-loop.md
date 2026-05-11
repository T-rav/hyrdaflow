# ADR-0058: Edge-Proposer Loop (Dark-Factory Graph Densification)

## Status

Accepted

## Date

2026-05-08

## Enforced by

`tests/test_edge_proposer_loop.py`, `tests/architecture/test_edge_proposer_wiring.py`

## Context

[ADR-0053](0053-ubiquitous-language-as-living-artifact.md) established the
ubiquitous-language glossary as a living artifact, and
[ADR-0054](0054-term-auto-proposer-loop.md) /
[ADR-0057](0057-term-pruner-loop.md) closed the term lifecycle (grow + prune).
The graph now has stable nodes — but the rendered Mermaid context map still
shows only a handful of hand-authored edges between bounded contexts. Without
an edge-densifying loop, edges remain stale relative to the codebase's
actual dependency structure: every refactor that adds an import or a Protocol
implementation between term-anchored classes silently leaves the graph less
representative of reality.

The dark-factory contract (`docs/wiki/dark-factory.md`) requires the graph
to settle without humans. The grow/prune cycle alone produces a node-rich
but edge-poor graph; this ADR closes the structural-edge half of the gap.

## Decision

A new caretaker loop (`EdgeProposerLoop`) periodically scans existing terms
and proposes typed edges between them based on **purely structural** signals:
the live import graph (`depends_on`) and class-inheritance AST
(`implements`). Per tick, all proposals are bundled into ONE auto-merging
bot PR labelled `hydraflow-ul-edges`.

### Detection — purely structural

Two signals, both deterministic, no LLM:

1. **`depends_on`**: For each term `A`, every name imported by `A`'s anchored
   module that resolves to another term `B` becomes a candidate
   `A depends_on B` edge (skip self-loops; skip already-present edges).
2. **`implements`**: For each term `A`, every direct class base in `A`'s
   anchored `ClassDef.bases` that resolves to another term `B` becomes a
   candidate `A implements B` edge (same skip rules).

`implements` is the closest typed-edge match in the closed `TermRelKind` set
even when the base isn't strictly a Protocol; subclassing already expresses
the relationship the edge is meant to capture. LLM-judgmental edge kinds
(`is_a`, `part_of`, `publishes`, `consumes`, `guarded_by`, `contradicts`)
are out of scope and deferred to a future extension.

### Output — auto-merged bot PRs labelled `hydraflow-ul-edges`

For each tick, the loop bundles all affected terms into ONE PR. Each affected
term file is re-rendered with `related` extended by the new edges and
`updated_at` bumped. `DependabotMergeLoop` auto-merges on CI green.
`ReviewPhase` routing exception extends to skip this label (alongside
`hydraflow-ul-proposed` and `hydraflow-ul-deprecated`).

### Idempotence — set-difference at runtime, no DedupStore

Re-running on the same graph produces the same proposal set; existing edges
are detected and filtered before the PR is opened. If nothing is new, no PR
opens. No DedupStore is needed.

### Edge pruning — out of scope

Removing stale edges when an import disappears is symmetric work parallel
to ADR-0057's term pruning; a future small follow-up can extend this loop
or add a sibling. Keeping the initial loop additive only minimises blast
radius and matches the staged rollout in the chunk-5 plan.

### Config + dashboard

Standard caretaker shape: 2 config fields with bounds (`edge_proposer_enabled`,
`edge_proposer_interval` default 24h, 1h ≤ x ≤ 7d), registered in
`BACKGROUND_WORKERS`, manual trigger via dashboard, kill-switch via
`edge_proposer_enabled`.

## Consequences

- The Mermaid context map densifies as the codebase evolves: every new
  import or inheritance between term-anchored classes flows into `related`
  within one tick after the merge.
- LLM cost: zero — this loop is purely structural.
- The four-loop UL fleet now covers grow (proposer), prune (pruner), and
  densify (edge-proposer); the remaining piece (Entry→Term Migrator)
  back-fills historical wiki entries rather than maintaining live state.
- Concurrent writes against the same term file (e.g., pruner deprecating
  while edge-proposer extends `related`) result in standard PR merge
  conflicts; the next tick retries deterministically.

## Alternatives considered

- **LLM-judged edges in one loop.** Rejected: mixes a deterministic structural
  pass with a non-deterministic semantic pass; harder to reason about
  correctness and cost; the structural signals alone close most of the gap.
- **Edge pruning in the same loop.** Rejected: adds churn (every removal
  creates a PR) without the deterministic safety net the term-pruner gets
  from `lint_anchor_resolution`. Defer until churn is observed.
- **Issue-only.** Rejected: doesn't autonomously densify the graph; defeats
  the dark-factory contract.

## Related

- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) — UL artifact + lints
- [ADR-0054](0054-term-auto-proposer-loop.md) — companion grow loop
- [ADR-0057](0057-term-pruner-loop.md) — companion prune loop
- `src/edge_proposer_loop.py` — the loop
- `src/ubiquitous_language.py` — `TermStore`, `build_import_graph`
