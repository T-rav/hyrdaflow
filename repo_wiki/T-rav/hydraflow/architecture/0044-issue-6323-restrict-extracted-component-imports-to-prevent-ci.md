---
id: 0044
topic: architecture
source_issue: 6323
source_phase: plan
created_at: 2026-04-10T04:47:03.630704+00:00
status: active
---

# Restrict extracted component imports to prevent circular dependencies

Extracted modules (PipelineStatsBuilder, CreditPauseManager, LoopSupervisor) must only import from a safe set: config, events, models, subprocess_util, service_registry, bg_worker_manager. Never import from orchestrator.py, even transitively. This strict boundary prevents import-time deadlocks and keeps extracted components independently testable and reusable.
