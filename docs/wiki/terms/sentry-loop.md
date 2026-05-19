---
id: "01KR9A3F20M01PGF32CF88W9A7"
name: "SentryLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/sentry_loop.py:SentryLoop"
aliases: ["sentry loop", "sentry ingestion loop", "sentry issue poller"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Background loop that polls the Sentry API for unresolved issues across configured projects, deduplicates them against already-filed GitHub issues, and invokes a Claude agent via `/hf.issue` to research the codebase and file a properly triaged GitHub issue — the same flow as dashboard bug reports (ADR-0055). Requires Sentry credentials in config. Sentry captures real code bugs only; transient failures and operational noise are excluded by the loop's dedup and filtering logic.

## Invariants

- Issues are deduplicated before filing; re-ingestion of the same Sentry event does not produce duplicate GitHub issues.
- Kill-switch is via `enabled_cb("sentry")` (ADR-0049).
- Sentry errors in the `ERROR+` level range trigger the issue-filing path; `WARNING` and below are skipped.
