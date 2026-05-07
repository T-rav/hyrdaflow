---
id: "01KR1GDECRP5Z9X3HNGX3XFS8B"
name: "Task"
kind: "entity"
bounded_context: "builder"
code_anchor: "src/models.py:Task"
aliases: ["work item", "ticket"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-07T15:20:32.920858+00:00"
updated_at: "2026-05-07T15:20:32.920863+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-05-07T15:20:32.920451+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 2
---

## Definition

A source-agnostic work item abstraction representing tasks from any source (GitHub issues, Linear tickets, etc.) that flow through HydraFlow's pipeline. Tasks carry metadata, support typed relationships via TaskLink, and serve as the unified representation for all work regardless of origin. Relationship extraction follows first-match precedence across compiled regex patterns.

## Invariants

- TaskLink relationships extracted via regex patterns with first-match precedence per target_id
- URLs validated as empty or http(s):// via AfterValidator
- Timestamps validated as empty or ISO 8601 format
