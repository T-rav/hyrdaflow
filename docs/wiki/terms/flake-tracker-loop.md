---
id: "01KRBL0F20M01PGF32CF88W9B2"
name: "FlakeTrackerLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/flake_tracker_loop.py:FlakeTrackerLoop"
aliases: ["flake tracker loop", "flaky test detector", "flake detector loop"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Trust-fleet loop that detects persistently flaky tests by parsing JUnit XML from the last 20 RC runs and counting mixed pass/fail occurrences per test (spec §4.5, ADR-0065). When a test's flake count reaches `flake_threshold` (default 3, comparison `>=`), the loop files a `hydraflow-find` + `flaky-test` issue. After 3 repair attempts on the same test_name the loop escalates to a second issue labeled `hitl-escalation` + `flaky-test-stuck`. The dedup key for the escalation issue clears when the escalation issue is closed.

## Invariants

- The rolling window is fixed at the last 20 RC runs; earlier history is not scanned.
- Flake detection requires at least one pass AND one fail within the window — pure-fail tests are not flakes.
- Maximum 3 repair attempts per test before HITL escalation; the dedup key for the `hydraflow-find` issue does not reset until the escalation is resolved.
- Kill-switch is via `enabled_cb("flake_tracker")` (ADR-0049).
