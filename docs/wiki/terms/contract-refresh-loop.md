---
id: "01KRBL0F20M01PGF32CF88W9C3"
name: "ContractRefreshLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/contract_refresh_loop.py:ContractRefreshLoop"
aliases: ["contract refresh loop", "cassette refresh loop", "fake contract refresh loop"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Trust-fleet loop that refreshes cassettes for fake contract tests on a weekly cadence (ADR-0045, ADR-0047, spec §4.2). Each tick: records cassettes against live `gh`/`git`/`docker`/`claude` into a tmp directory, diffs them against committed cassettes, short-circuits on hash-matching repeat drift (dedup via `DedupStore`), stages drifted cassettes, and opens a `contract-refresh: YYYY-MM-DD (<adapters>)` PR labeled `contract-refresh` + `auto-merge`. A post-refresh replay gate (`make trust-contracts`) runs after staging; failure opens a companion `hydraflow-find` + `fake-drift` issue so the factory dispatches a fake-repair implementer — PR auto-merge is not blocked by the replay gate. Per-loop telemetry spans (`trace_collector.emit_loop_subprocess_trace`) cover each recorder subprocess and the replay gate.

## Invariants

- Dedup is keyed on the drift-report hash; identical drift on consecutive ticks does not refile the same PR.
- Dedup is recorded only after the PR is opened, never before — transient failures do not silently block the next tick.
- The replay gate failure opens a companion issue but does not block the auto-merge PR.
- Kill-switch is via `enabled_cb("contract_refresh")` (ADR-0049); no config field.
