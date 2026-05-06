---
id: "01KQV37D10M06PGF32CF77W6K9"
name: "IssueStorePort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/ports.py:IssueStorePort"
aliases: ["issue store port", "issue queue port", "work queue port"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668794+00:00"
updated_at: "2026-05-05T03:35:36.668795+00:00"
---

## Definition

Hexagonal port for the in-memory issue work-queue — exposes only the queue accessors that domain code (phases, background loops, phase utilities) actually uses (get_triageable, get_plannable, get_implementable, get_reviewable, ...). Implemented by issue_store.IssueStore; orchestrator-only and dashboard-only methods stay on the concrete class to keep the domain surface narrow.

## Invariants

- Pure Protocol — no implementation, no state.
- Only domain-consumed methods are declared; orchestrator and dashboard methods deliberately stay off the port.
