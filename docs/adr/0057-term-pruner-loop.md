# ADR-0057: Term-Pruner Loop (Dark-Factory Glossary Hygiene)

## Status

Accepted

## Date

2026-05-07

## Enforced by

`tests/test_term_pruner_loop.py`, `tests/architecture/test_term_pruner_wiring.py`

## Context

[ADR-0054](0054-term-auto-proposer-loop.md) established `TermProposerLoop` to grow the ubiquitous-language glossary from live `src/`. Without a pruner, deletions and renames in the codebase produce permanent dangling terms — `make lint-ul`'s anchor-resolution lint (chunk 1) fails until a human edits the term file. The dark-factory contract (CLAUDE.md, `docs/wiki/dark-factory.md`) requires both grow and prune to settle without humans.

PR #8681 shipped the first autonomous Term. The next class delete or rename in `src/` would block every unrelated PR via the lint until pruned. This ADR closes that loop.

## Decision

A new caretaker loop (`TermPrunerLoop`) periodically scans existing terms; for any term whose `code_anchor` no longer resolves in the live symbol index, opens an auto-merging bot PR flipping `confidence` to `deprecated` with a `superseded_reason` documenting the broken anchor.

### Detection — purely structural

Eligibility (all required):

1. `confidence == "accepted"` (proposed shouldn't exist in steady-state per the chunk-2.5 simplification; deprecated already pruned)
2. `code_anchor` does NOT resolve via `resolve_anchor`
3. `superseded_by is None` (already-superseded terms are pruned via that mechanism)

No LLM call. No rename detection.

### Output — auto-merged bot PRs as `deprecated`

For each tick, the loop bundles all eligible terms into ONE PR labelled `hydraflow-ul-deprecated`. `DependabotMergeLoop` auto-merges on CI green. `ReviewPhase` routing exception extends to skip this label (alongside `hydraflow-ul-proposed`).

### Rename handling — two-tick flow

When a class is renamed, two ticks settle the glossary:
1. Tick A: Pruner detects the OLD anchor doesn't resolve → deprecates the old term.
2. Tick B (later): TermProposerLoop detects the NEW class is uncovered → proposes a new term.

The system reaches a steady state without rename-specific logic. If observed churn ever justifies it, a future ADR can add LLM-judged rename detection as an optimization.

### Config + dashboard

Standard caretaker shape: 2 config fields with bounds, registered in `BACKGROUND_WORKERS`, manual trigger via dashboard, kill-switch via `term_pruner_enabled`.

## Consequences

- The `lint_anchor_resolution` hard-fail lint is autonomously satisfied — `make lint-ul` stays green continuously.
- The glossary self-heals: deletes and renames flow through the pruner+proposer pair without human intervention.
- LLM cost: zero — this loop is structural.
- The four-loop UL fleet is now complete for the grow/prune cycle; remaining (Edge-Proposer, Entry→Term Migrator) extend the graph rather than maintain it.

## Alternatives considered

- **Deprecate + auto-rename detection in one PR.** Rejected: rename detection is LLM-judgmental; complexity for marginal value (the two-tick flow handles it).
- **Hard-delete the term file.** Rejected: loses provenance and audit trail; supersession+`deprecated` is the right archive shape.
- **Issue-only.** Rejected: doesn't autonomously close the lint failure; human work required.

## Related

- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) — UL artifact + lints
- [ADR-0054](0054-term-auto-proposer-loop.md) — companion grow loop
- `src/term_pruner_loop.py` — the loop
- `src/ubiquitous_language.py` — `TermStore`, `resolve_anchor`
