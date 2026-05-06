---
id: "01KQV37D10M06PGF32CF77W6K7"
name: "PRPort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/ports.py:PRPort"
aliases: ["pr port", "pull request port", "github pr port"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668784+00:00"
updated_at: "2026-05-05T03:35:36.668785+00:00"
---

## Definition

Hexagonal port for GitHub PR, label, and CI operations — branch push, PR creation/merge, RC-branch creation, and the related label manipulations consumed by domain phases and background loops. Implemented by pr_manager.PRManager; signatures are kept identical to the concrete class to enable structural subtype checks.

## Invariants

- Pure Protocol — no implementation, no state.
- Method signatures must match pr_manager.PRManager exactly so structural subtype checks in tests/test_ports.py pass.
