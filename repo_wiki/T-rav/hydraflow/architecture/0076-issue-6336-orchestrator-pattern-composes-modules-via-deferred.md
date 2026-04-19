---
id: 0076
topic: architecture
source_issue: 6336
source_phase: plan
created_at: 2026-04-10T05:57:03.732554+00:00
status: active
---

# Orchestrator pattern composes modules via deferred registration calls

A factory function can become a thin orchestrator (~80 lines) that creates a shared context object and delegates route registration to ~12 sub-modules via a consistent `register(router, ctx)` signature. Each sub-module owns 50–200 lines; the factory merely composes them. This pattern decouples endpoint logic from factory complexity and enables parallel implementation.
