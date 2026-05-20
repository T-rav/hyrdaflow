---
id: "01KRBL0F20M01PGF32CF88W9B3"
name: "CIMonitorLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/ci_monitor_loop.py:CIMonitorLoop"
aliases: ["CI monitor loop", "ci monitor loop", "continuous integration monitor loop"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Caretaker loop that watches CI status on the main branch and files a `hydraflow-ci-failure` issue when CI goes red (ADR-0029, ADR-0065). The loop auto-closes the issue when CI recovers to green. Duplicate issue creation is prevented by tracking the open CI-failure issue number in memory, with rehydration from GitHub labels on first tick to survive restarts cleanly.

## Invariants

- At most one open `hydraflow-ci-failure` issue exists at any time; the loop tracks `_open_issue` to enforce this.
- On startup the loop rehydrates from existing `hydraflow-ci-failure` issues before its first check — a clean restart never duplicates a pre-existing issue.
- Kill-switch is via `enabled_cb("ci_monitor")` and `config.ci_monitor_loop_enabled` (ADR-0049).
