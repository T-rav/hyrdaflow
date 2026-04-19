---
id: 0052
topic: architecture
source_issue: 6330
source_phase: plan
created_at: 2026-04-10T05:17:59.124008+00:00
status: active
---

# Coordinator pattern with call-order sensitivity

When extracting sub-methods from a large method, the original method becomes a thin orchestrator calling extracted methods in sequence. Execution order is critical—e.g., builder.record_history() must happen before builder.build_stats(). Preserve exact call order in the coordinator; tests should verify this order is maintained after extraction.
