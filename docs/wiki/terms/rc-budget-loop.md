---
id: "01KR9A3F20M01PGF32CF88W9A4"
name: "RCBudgetLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/rc_budget_loop.py:RCBudgetLoop"
aliases: ["rc budget loop", "rc ci wall-clock detector", "rc duration regression detector"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

4-hour RC CI wall-clock regression detector (ADR-0045 §4.8). Reads the last 30 days of `rc-promotion-scenario.yml` runs via `gh run list`, extracts per-run wall-clock duration, and emits a `hydraflow-find` + `rc-duration-regression` issue when the newest run trips either a gradual-bloat signal (current run ≥ 1.5× rolling median) or a sudden-spike signal (current run ≥ 2.0× recent-five maximum). Both signals are independent; both may fire on the same tick with distinct dedup keys. After 3 unresolved attempts per signal the loop escalates to `hitl-escalation` + `rc-duration-stuck`.

## Invariants

- Kill-switch is via `enabled_cb("rc_budget")` only — no `rc_budget_enabled` config field (ADR-0049 §12.2).
- Requires at least 5 historical data points before emitting any signal.
- Dedup keys clear on escalation-close.
