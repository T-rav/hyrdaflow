---
id: 0088
topic: architecture
source_issue: 6346
source_phase: plan
created_at: 2026-04-10T06:38:22.369945+00:00
status: active
---

# Use method names not line numbers for refactoring plans

Identify code to remove by symbol name (def method_name) rather than line numbers. Files drift; methods remain stable. This reduces off-by-N errors and makes plans self-correcting when file structure changes.
