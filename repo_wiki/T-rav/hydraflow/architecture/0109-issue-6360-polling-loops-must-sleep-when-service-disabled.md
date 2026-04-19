---
id: 0109
topic: architecture
source_issue: 6360
source_phase: plan
created_at: 2026-04-10T07:37:26.758846+00:00
status: active
---

# Polling loops must sleep when service disabled

Polling loops that run against a service should always check a boolean flag (e.g., _pipeline_enabled) and sleep when disabled. This prevents tight loops that attempt operations against uninitialized resources. See _polling_loop (line 940) pattern.
