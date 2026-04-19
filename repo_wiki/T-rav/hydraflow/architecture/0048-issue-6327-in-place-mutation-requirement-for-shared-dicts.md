---
id: 0048
topic: architecture
source_issue: 6327
source_phase: plan
created_at: 2026-04-10T05:07:55.384588+00:00
status: active
---

# In-Place Mutation Requirement for Shared Dicts

If any sub-component reassigns a dict (e.g., `self._queues = {}`) instead of mutating in-place (e.g., `self._queues[stage].clear()`), the shared reference breaks and mutations become invisible to other components. This is the central risk — all state mutations in extracted classes must be in-place, not reassignment.
