---
id: 0089
topic: architecture
source_issue: 6346
source_phase: plan
created_at: 2026-04-10T06:38:22.369952+00:00
status: active
---

# Document trade-off when removing implicit documentation

When a method like invalidate() serves as implicit documentation (its list of attributes documents cache structure), note that removal trades explicitness for simplicity. The data structure remains self-documenting through __init__ and usage patterns.
