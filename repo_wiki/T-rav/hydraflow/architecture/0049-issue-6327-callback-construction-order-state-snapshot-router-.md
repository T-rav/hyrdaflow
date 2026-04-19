---
id: 0049
topic: architecture
source_issue: 6327
source_phase: plan
created_at: 2026-04-10T05:07:55.384592+00:00
status: active
---

# Callback Construction Order: State → Snapshot → Router → Tracker

`_publish_queue_update_nowait` callback invokes `self._snapshot.get_queue_stats()`. Sub-components are constructed in order of dependency: state dicts first, then snapshot (used by publish_fn), then router and tracker (which receive publish_fn as a callback). Reordering breaks with AttributeError.
