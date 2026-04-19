---
id: 0030
topic: architecture
source_issue: 6295
source_phase: review
created_at: 2026-04-10T03:47:50.097416+00:00
status: active
---

# Visual consistency outweighs functional correctness

Code dict entries should visually align with their layer assignment comment blocks, not with the layer they logically belong to. Even when functionally harmless, misalignment is visually misleading and reduces code clarity for future maintainers.
