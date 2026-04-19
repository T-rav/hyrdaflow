---
id: 0028
topic: architecture
source_issue: 6314
source_phase: plan
created_at: 2026-04-10T03:45:26.654545+00:00
status: active
---

# Wire unconnected config parameters to existing consumers

When a consumer (e.g., StateTracker) already accepts constructor parameters matching config fields, but the wiring is missing from the service builder, this is a low-risk one-line fix. Check StateTracker's signature before assuming the parameter doesn't exist; it often does with sensible defaults.
