# ADR-0002: GitHub Labels as the Pipeline State Machine

**Status:** Accepted
**Date:** 2026-02-26

## Context

HydraFlow needs a way to track which stage each issue is currently in, and to
hand off issues between pipeline stages. Options considered:

1. A separate database or file tracking issue → stage mappings.
2. GitHub issue labels as the state signal.
3. A dedicated state file in the repo (`.hydraflow/state.json`).

The system must support:
- Multi-process / multi-machine operation (state must be shared).
- Human visibility into what the system is doing without custom tooling.
- Human override (move an issue backwards or skip a stage).
- Crash recovery (state survives process restarts).

## Decision

Use GitHub issue labels as the authoritative state machine. Each pipeline stage
maps to exactly one label:

```
hydraflow-find   → triageable
hydraflow-plan   → needs planning
hydraflow-ready  → ready for implementation
hydraflow-review → PR open, under review
hydraflow-hitl   → escalated for human intervention
hydraflow-fixed  → merged, done
```

Transitions are atomic via `swap_pipeline_labels()`: all other pipeline labels
are removed before the new one is added. This prevents the dual-label bug (where
a crash between remove and add leaves conflicting labels).

State is polled, not pushed: each loop queries GitHub for issues with its label.

## Consequences

**Positive:**
- Zero infrastructure: no database, no message broker, no external state store.
- Human-readable: anyone with GitHub access can see and modify pipeline state.
- Human override is trivial: drag a label to move an issue to any stage.
- Crash recovery is free: the orchestrator re-polls labels on startup and picks up
  where it left off.
- Works across machines and processes with no coordination protocol.

**Negative / Trade-offs:**
- GitHub API rate limits apply to all label reads/writes; high-volume repos may
  hit limits.
- Polling introduces latency proportional to the poll interval (default 30–60s).
  Label changes are not instant.
- No history: the label state machine has no built-in audit log of how an issue
  moved through stages (git history / transcript logs compensate for this).
- The dual-label invariant (exactly one pipeline label) must be maintained by all
  code paths; bypassing `swap_pipeline_labels` can break it.

## Related

- `src/pr_manager.py:swap_pipeline_labels` — atomic swap implementation
- `src/config.py:all_pipeline_labels` — the full label set
- `tests/test_state_machine.py` — property-based invariant tests
- ADR-0001 for why polling loops were chosen over a push-based model
