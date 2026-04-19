---
id: 0050
topic: architecture
source_issue: 6327
source_phase: plan
created_at: 2026-04-10T05:07:55.384597+00:00
status: active
---

# Immutable Scalars in Shared State Pattern

`_last_poll_ts` (a string) cannot be shared by reference like dicts — reassignment on the facade doesn't propagate to sub-components. Solution: snapshot's `get_queue_stats()` accepts `last_poll_ts` as a parameter; the facade passes `self._last_poll_ts` at call time. This pattern applies to any immutable scalar in shared state.
