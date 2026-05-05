---
id: "01KQV37D10M06PGF32CF77W6K5"
name: "BaseBackgroundLoop"
kind: "loop"
bounded_context: "shared-kernel"
code_anchor: "src/base_background_loop.py:BaseBackgroundLoop"
aliases: ["base background loop", "background loop", "loop base class"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668776+00:00"
updated_at: "2026-05-05T03:35:36.668777+00:00"
---

## Definition

Abstract base class for every concurrent worker loop in the HydraFlow orchestrator (ADR-0001, ADR-0029). Owns the run-loop skeleton — enabled-check, interval management, status callbacks, BACKGROUND_WORKER_STATUS event publishing, error reporting, and trigger-based early wake-up — leaving subclasses to implement only the domain-specific _do_work and _get_default_interval hooks.

## Invariants

- Subclasses must implement abstract methods _do_work and _get_default_interval.
- AuthenticationError, AuthenticationRetryError, and CreditExhaustedError propagate; all other exceptions are logged and the loop retries on the next cycle.
- Shared dependencies (event_bus, stop_event, status_cb, enabled_cb, sleep_fn, interval_cb) are bundled into a LoopDeps record passed to __init__.
