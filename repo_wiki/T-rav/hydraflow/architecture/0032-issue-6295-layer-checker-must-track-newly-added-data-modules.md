---
id: 0032
topic: architecture
source_issue: 6295
source_phase: review
created_at: 2026-04-10T03:47:50.097432+00:00
status: active
---

# Layer checker must track newly added data modules

When creating new constant/data modules at a given layer, update the layer import checker to recognize them. This prevents false positives and ensures the layer checker stays current as the codebase grows.
