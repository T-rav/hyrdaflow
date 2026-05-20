---
id: "01KRBL0F20M01PGF32CF88W9B4"
name: "CorpusLearningLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/corpus_learning_loop.py:CorpusLearningLoop"
aliases: ["corpus learning loop", "adversarial corpus loop", "escape signal ingestion loop"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Trust-fleet loop that autonomously grows the adversarial test corpus from escape signals (ADR-0045, spec §4.1 v2). Each tick: reads open issues tagged with the escape label from the last `DEFAULT_LOOKBACK_DAYS` days, synthesizes each into a `SynthesizedCase`, runs three self-validation gates (harness acceptance, expected catcher trips, unambiguity across all catchers), materializes passing cases to `tests/trust/adversarial/cases/<slug>/`, and opens auto-merge PRs. A `DedupStore` keyed on `corpus_learning:<issue_number>:<slug>` prevents re-filing the same case on subsequent ticks.

## Invariants

- All three validation gates must pass before a case reaches disk: harness accepts it, expected catcher trips, no other catcher also trips.
- Cases that trip more than one catcher are rejected as ambiguous before they can corrupt the corpus.
- No `corpus_learning_enabled` config field exists — kill-switch is purely via `enabled_cb("corpus_learning")` (spec §12.2, ADR-0049).
