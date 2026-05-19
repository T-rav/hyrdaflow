---
id: "01KR9A3F20M01PGF32CF88W9A3"
name: "PRUnstickerLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/pr_unsticker_loop.py:PRUnstickerLoop"
aliases: ["pr unsticker loop", "pr unsticker", "hitl unsticker"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Caretaker loop that polls HITL items and delegates to `PRUnsticker` to resolve all HITL causes — merge conflicts, CI failures, and generic stuck states. Operates only on HITL issues that currently have an open PR. The loop wraps the unsticker worker in the standard `BaseBackgroundLoop` tick-and-interval skeleton, keeping the HITL resolution logic in `PRUnsticker` separate from the polling infrastructure.

## Invariants

- Only processes HITL issues with an associated open PR (`item.pr > 0`); issues without PRs are skipped.
- Kill-switch is via `enabled_cb("pr_unsticker")` and `config.pr_unsticker_loop_enabled` (ADR-0049).
- Interval is driven by `config.pr_unstick_interval`.
