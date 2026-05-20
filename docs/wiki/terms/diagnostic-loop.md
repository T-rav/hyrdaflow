---
id: "01KRBL0F20M01PGF32CF88W9B9"
name: "DiagnosticLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/diagnostic_loop.py:DiagnosticLoop"
aliases: ["diagnostic loop", "diagnostic self-healing loop", "escalation diagnostic loop"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Caretaker loop that picks up escalated HITL issues and attempts autonomous self-healing via `DiagnosticRunner` (ADR-0050). For each escalated issue the loop runs a diagnosis that identifies severity, root cause, affected files, and a fix plan, then posts a structured diagnostic comment with human-guidance section. Attempts are tracked via `AttemptRecord`; the loop respects the attempt budget before escalating further. `CreditExhaustedError` is re-raised via `reraise_on_credit_or_bug` so attempt budgets are not silently burned against an exhausted billing signal.

## Invariants

- `reraise_on_credit_or_bug(exc)` is called in the broad `except` block — credit exhaustion is never silently swallowed.
- Severity is structured (`P0_SECURITY` through `P4_HOUSEKEEPING`) and appears in the diagnostic comment; reviewers do not need to parse free text to triage.
- Kill-switch is via `enabled_cb("diagnostic")` (ADR-0049).
