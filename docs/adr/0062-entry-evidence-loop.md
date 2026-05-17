# ADR-0062: Entry-Evidence Loop — Term ↔ Wiki-Entry Backlinks (Dark-Factory Glossary Enrichment)

## Status

Accepted

## Date

2026-05-10

## Enforced by

`tests/test_entry_evidence_loop.py`, `tests/scenarios/test_entry_evidence_loop_scenario.py`

## Context

[ADR-0053](0053-ubiquitous-language-as-living-artifact.md) introduced `Term.evidence: list[str]` so each term can carry the wiki-entry IDs that justify it. [ADR-0061](0061-atlas-entries-as-evidence.md) added the Atlas surface that renders those backlinks (entry nodes attached to terms; orphans land in a Discovered bucket).

The intermediate step — actually populating `evidence` — has been a one-shot script (`scripts/migrate_entries_to_term_evidence.py`) requiring a manual operator run. That's load-bearing infrastructure for the Atlas Domain view but doesn't fit the dark-factory operating model: glossary churn happens continuously (new wiki entries arrive from `RepoWikiLoop`, new terms from `TermProposerLoop`), so backlinks should be maintained autonomously like every other graph maintenance task.

The term-graph already has a trio of background loops:
- `TermProposerLoop` (ADR-0054) — adds new terms via LLM
- `TermPrunerLoop` (ADR-0057) — deprecates stale terms via anchor resolution
- `EdgeProposerLoop` (ADR-0058) — adds `depends_on` + `implements` edges via structural analysis

This ADR adds the fourth: a loop that closes the entry→term linking gap on an interval, mirroring the structure of its three siblings.

## Decision

### A new `EntryEvidenceLoop` class

`src/entry_evidence_loop.py` subclasses `BaseBackgroundLoop` and mirrors `EdgeProposerLoop`'s shape exactly:
- Reads from `docs/wiki/terms/*.md` (via `TermStore`) and `docs/wiki/*.md` (via `RepoWikiStore._load_topic_entries`).
- For each wiki entry it doesn't already see in some term's `evidence`, asks the LLM (`TermProposerLLM` shared with the proposer loop) which terms the entry GENUINELY discusses.
- Aggregates per-term, applies set-difference idempotence, and renders the updated term files.
- Opens a bot PR labelled `hydraflow-ul-evidence` via the existing `OpenAutoPRBotPRPort` (same auto-merge plumbing as `EdgeProposerLoop`).

### LLM matching, not substring search

Substring matching against term names + aliases is too noisy at the wiki-entry scale (paragraphs of prose vs. a 14-line Related section). The LLM prompt — already shipped via the migration script — explicitly tells the model "include only terms the entry GENUINELY discusses, not terms that just happen to share a name fragment." Returning the structured `{"term_ids": [...]}` JSON keeps the matching deterministically-validated against the live term set.

### Config and dashboard

```
HYDRAFLOW_ENTRY_EVIDENCE_ENABLED=true     # kill-switch
HYDRAFLOW_ENTRY_EVIDENCE_INTERVAL=86400   # default 24h (glossary churn is slow)
HYDRAFLOW_ENTRY_EVIDENCE_MAX_ENTRIES_PER_TICK=20  # bound credit cost
```

The loop registers under worker name `entry_evidence`, appears in `BACKGROUND_WORKERS` (`group: 'learning'`, `tags: ['knowledge']`), and surfaces in Atlas → Maintenance via the existing term-loops status card (ADR-0060). No new endpoints; the existing `/api/atlas/term-loops/status` keys by loop name.

### Idempotence + bounded cost

Each tick:
1. Loads the full term store and walks `docs/wiki/{topic}.md`.
2. Builds the "already linked" set by unioning every term's `evidence` field.
3. Processes at most `max_entries_per_tick` entries that aren't already linked — LLM call per entry, so the per-tick credit cost is bounded.
4. Applies set-difference before writing; if nothing changes, returns `opened_pr=False` without opening a no-op PR.

This makes the loop fully resumable: if it processes 20 entries this tick and 30 remain, the next tick picks up where it left off without re-running matched entries.

## Consequences

- The one-shot `scripts/migrate_entries_to_term_evidence.py` becomes a manual escape hatch (e.g., for backfill after a large wiki import). The loop is the steady-state path.
- Credit cost is bounded but non-zero: 1 LLM call per uncached wiki entry, capped at `max_entries_per_tick` per tick. The dashboard's existing `BackgroundWorkerStatusPayload` carries the per-tick count for monitoring.
- The bot-PR label (`hydraflow-ul-evidence`) joins the existing skip list for the review pipeline — same plumbing as edge/pruner PRs.

## Alternatives considered

- **Fold into `TermProposerLoop`.** Rejected: that loop already has its own work (proposing new terms). Adding a second responsibility couples two failure modes and inflates per-tick credit cost.
- **Fold into `RepoWikiLoop`.** Rejected: `RepoWikiLoop`'s domain is per-repo wiki maintenance — it doesn't load the term store and shouldn't grow that dependency.
- **Trigger only on new wiki-entry commits via a Git hook.** Rejected: hooks add a different failure mode and don't handle the bootstrap case (an existing wiki being added to a new term).
- **Keep it as a manual script.** Rejected by design (this ADR's reason for existing).

## Related

- [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) — `Term.evidence` field
- [ADR-0054](0054-term-auto-proposer-loop.md) — `TermProposerLoop`
- [ADR-0057](0057-term-pruner-loop.md) — `TermPrunerLoop`
- [ADR-0058](0058-edge-proposer-loop.md) — `EdgeProposerLoop`
- [ADR-0061](0061-atlas-entries-as-evidence.md) — Atlas surface for entry-evidence
- `scripts/migrate_entries_to_term_evidence.py` — original one-shot script (now a manual fallback)
- `src/term_proposer_llm.py` — `TermProposerLLM` client (shared)
