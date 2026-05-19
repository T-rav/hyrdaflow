---
id: "01KR9A3F20M01PGF32CF88W9A8"
name: "StaleIssueGCLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/stale_issue_gc_loop.py:StaleIssueGCLoop"
aliases: ["stale issue gc loop", "stale hitl gc loop", "hitl stale closer"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Caretaker loop that auto-closes stale HITL escalation issues (ADR-0029). Scope is specifically open issues carrying the configured HITL label that have been inactive beyond `stale_issue_threshold_days`. Posts a farewell comment, then closes. Caps at 10 closures per cycle to avoid GitHub rate-limiting. Distinct from `StaleIssueLoop`, which handles stale general issues with no HydraFlow lifecycle label — the two loops share only the `BaseBackgroundLoop` framework and have zero business-logic overlap.

## Invariants

- Maximum 10 issues closed per tick to respect GitHub rate limits.
- Only closes issues carrying the HITL label (`config.hitl_label`), not general issues.
- `StaleIssueGCLoop` and `StaleIssueLoop` are fully separate; do not conflate them.
