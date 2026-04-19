---
id: 0054
topic: architecture
source_issue: 6330
source_phase: plan
created_at: 2026-04-10T05:17:59.124014+00:00
status: active
---

# Parameter threading across extracted methods

Some parameters (like bead_mapping) appear as arguments to multiple extracted methods across different extraction phases. Watch for these cross-cutting parameters during design—they indicate a concern that spans multiple extracted methods and should be threaded consistently through the coordinator to avoid silent bugs from missing arguments.
