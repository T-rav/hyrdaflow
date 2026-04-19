---
id: 0043
topic: architecture
source_issue: 6323
source_phase: plan
created_at: 2026-04-10T04:47:03.630696+00:00
status: active
---

# Use callbacks to decouple isolated components from orchestrator state

CreditPauseManager accepts `cancel_fn` and `resume_fn` callbacks instead of directly accessing loop task dicts. This avoids circular dependencies between manager and supervisor while allowing the manager to trigger orchestration actions (pause all loops, recreate them on resume). Apply this pattern whenever an extracted component needs to coordinate with the orchestration layer.
