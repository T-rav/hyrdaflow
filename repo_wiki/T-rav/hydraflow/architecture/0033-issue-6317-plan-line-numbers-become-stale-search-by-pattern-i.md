---
id: 0033
topic: architecture
source_issue: 6317
source_phase: plan
created_at: 2026-04-10T03:55:35.397280+00:00
status: active
---

# Plan line numbers become stale; search by pattern instead

When implementing a plan generated in a prior session, files may have been modified since the plan was written. Prefer searching for method signature patterns rather than relying on exact line numbers provided in the plan.
