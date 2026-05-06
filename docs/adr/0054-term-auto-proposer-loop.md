# ADR-0054: Term Auto-Proposer Loop (Dark-Factory Glossary Growth)

## Status

Accepted

## Date

2026-05-06

## Enforced by

`tests/test_term_proposer_loop.py`, `tests/architecture/test_term_proposer_wiring.py`

## Context

[ADR-0053](0053-ubiquitous-language-as-living-artifact.md) established `Term` as a first-class wiki entity with closed-set vocabularies and three CI lint rules. The slice landed in PR #8474 with 9 hand-authored seed terms. The reverse-coverage lint reports **64 uncovered load-bearing symbols** as warn-only baseline.

Without auto-proposal, those 64 stay uncovered indefinitely — humans must author each one. The dark-factory premise (CLAUDE.md, [`docs/wiki/dark-factory.md`](../wiki/dark-factory.md)) is that human work is not the goal; the system grows itself. ADR-0029's caretaker pattern provides the operational shell; ADR-0050's auto-agent pre-flight pattern shows that bot-authored auto-merging PRs are an established surface in this codebase.

## Decision

A new caretaker loop (`TermProposerLoop`) periodically scans `src/`, identifies classes that should be terms via graph-grounded gap-finding, drafts them via LLM, and opens auto-merging bot PRs as `confidence: proposed`.

### Detection — graph-grounded gap-finding

Candidates surface via three signals over the live symbol index + import graph:
- **S1** — classes ending in `Loop` / `Runner` / `Port` / `Adapter` not anchored by an existing term (matches the existing reverse-coverage lint rule)
- **S2** — classes imported by ≥1 module that anchors an existing term, not themselves anchored (catches non-suffix terms like `WorkspaceManager`)
- **S5** — ranking by in-degree from covered-term anchors (composite signal)

The detection is conservative on purpose: utility helpers nothing important imports never surface; non-suffix classes that lots of terms depend on do.

### Output — auto-merged bot PRs as `proposed`

For each tick, the loop drafts ≤N candidates (default 10), validates each draft locally, and ships ALL surviving drafts as ONE bundled PR labelled `hydraflow-ul-proposed`. `DependabotMergeLoop` auto-merges on CI green. Bad drafts (anchor doesn't resolve, kind not in vocabulary, etc.) are dropped pre-PR and filed as `hydraflow-find` issues with the raw LLM output for human inspection. `PRManager` gets a routing exception so the agent pipeline ignores `hydraflow-ul-proposed` PRs (the LLM call inside the loop IS the work).

Drafts ship as `confidence: proposed`. The Confidence-Promoter (chunk 2 of the program — separate ADR, separate slice) is what later ages `proposed` → `accepted`.

### Edges — `depends_on` to existing terms only

When a candidate's imports reveal it depends on an existing-term anchor, the draft includes `depends_on` edges (E2 from the brainstorm). The proposer never proposes new terms AND new edges between unknown terms in the same draft — broader edge inference is the Edge-Proposer (chunk 4)'s job.

### Provenance fields on `Term`

Drafts authored by the loop carry four optional frontmatter fields: `proposed_by`, `proposed_at`, `proposal_signals`, `proposal_imports_seen`. Hand-authored terms omit them. These give chunk 2 the data it needs to make promotion decisions and let audits filter by source.

### Config + dashboard

Standard caretaker shape per ADR-0029: 4 config fields with bounds, registered in `BACKGROUND_WORKERS`, manual trigger via dashboard, kill-switch via `term_proposer_enabled`.

## Consequences

- The reverse-coverage lint (chunk 1) decreases monotonically tick-over-tick until it hits a small steady-state floor (classes that genuinely shouldn't be terms — test scaffolding, internal helpers).
- The glossary becomes a living, self-growing artifact. Humans only intervene when the loop files a `hydraflow-find` issue (validation failure) or when CI fails on a bot PR (`hydraflow-hitl` routing).
- `Term` model gains four optional fields; serialization remains backward-compatible (defaults to None for hand-authored terms).
- LLM cost is bounded: ≤N (default 10) calls per tick × 4h interval = ≤60 calls/day. Negligible against existing caretaker budgets, governed by `CostBudgetWatcherLoop`.
- The Confidence-Promoter (next ADR) becomes load-bearing: without it, terms accumulate as `proposed` forever. Both ADRs ship as a coherent pair from a program perspective; this ADR ships first as the keystone.

## Alternatives considered

- **Issue-only proposal** — file a `hydraflow-find` issue per uncovered class; humans take it from there. Rejected: doesn't grow the ontology automatically; "the system grows itself" requires more than a queue of human work.
- **Required human review on every PR** — bot drafts, humans gate every merge. Rejected: defeats the dark-factory premise. Conservative middle ground; acceptable as a temporary stance if the auto-merge approach proves unstable, but not the target.
- **LLM judges every public class (no graph grounding)** — walk all `src/` classes, ask LLM "is this load-bearing?" Rejected: high token cost, low precision, surfaces internal helpers.
- **Bundle-vs-per-PR** — open one PR per draft (high noise) vs one bundle per tick (chosen). Bundles match the "small batch going forward" pattern.

## Related

- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0044](0044-hydraflow-principles.md) §P2.9 — names are load-bearing
- [ADR-0045](0045-trust-architecture-hardening.md) — trust fleet (must allowlist the proposer's bot author)
- [ADR-0050](0050-auto-agent-hitl-preflight.md) — auto-agent caretaker pattern (sibling pattern: bot intercepts work before humans see it)
- [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) — the artifact this loop maintains
- `src/term_proposer_loop.py` — the loop
- `src/ubiquitous_language.py` — `Term`, `TermStore`, `lint_anchor_resolution`
