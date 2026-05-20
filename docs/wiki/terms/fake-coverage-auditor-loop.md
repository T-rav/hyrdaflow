---
id: "01KRBL0F20M01PGF32CF88W9B5"
name: "FakeCoverageAuditorLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/fake_coverage_auditor_loop.py:FakeCoverageAuditorLoop"
aliases: ["fake coverage auditor loop", "fake coverage gap detector", "uncassetted method detector"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Trust-fleet loop that detects uncovered methods on fake adapters under `src/mockworld/fakes/` via `ast.parse` (ADR-0045, ADR-0056, ADR-0057, spec §4.7). Compares two method sets: `adapter-surface` (public methods, covered by cassettes under `tests/trust/contracts/cassettes/<adapter>/`) and `test-helper` (scenario drivers like `script_*`, `fail_service`, `heal_service`, covered by scenario tests). Files one rollup issue per `(fake_class, gap_kind)` labeled `hydraflow-find` + `fake_coverage_gap`. Subsequent ticks update the body via `PRPort.update_issue_body` — appending newly-uncovered methods and striking through methods that gained coverage. Escalates after 3 attempts to `hitl_escalation` + `fake_coverage_stuck`.

## Invariants

- One rollup issue per `(fake_class, gap_kind)` — never one issue per missing method.
- Issue bodies are updated in-place on repeat ticks, not replaced.
- Maximum 3 repair attempts before HITL escalation.
- Kill-switch is via `enabled_cb("fake_coverage_auditor")` (ADR-0049).
