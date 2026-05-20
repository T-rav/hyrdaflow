---
id: "01KRBL0F20M01PGF32CF88W9B6"
name: "AdrTouchpointAuditorLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/adr_touchpoint_auditor_loop.py:AdrTouchpointAuditorLoop"
aliases: ["ADR touchpoint auditor loop", "adr drift auditor loop", "adr touchpoint gate caretaker"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Trust-fleet loop that replaces the deleted ADR touchpoint pre-merge gate with an async caretaker (ADR-0056). Periodically scans recently-merged PRs and files `hydraflow-find` issues when an Accepted or Proposed ADR's cited `src/` modules changed without the ADR file appearing in the same diff. Issues are aggregated into one rollup per ADR (`ADR-NNNN` dedup key) listing all drifted PRs; subsequent ticks update the body in-place. When the ADR file itself appears in a PR diff the rollup is auto-closed. The cursor (`state.adr_audit_cursor`) is seeded to "now" on first deploy — pre-existing history is not retroactively scanned.

## Invariants

- One rollup issue per ADR, never one issue per drifted PR.
- First-deploy cursor seed is "now" — historical PRs before deploy are not scanned.
- ADR self-appearance in a PR diff closes the rollup; partial fixes (some-but-not-all modules updated) do not close it.
- Maximum 3 repair attempts before HITL escalation.
- Kill-switch is via `enabled_cb("adr_touchpoint_auditor")` (ADR-0049).
