---
id: 0119
topic: architecture
source_issue: 6365
source_phase: plan
created_at: 2026-04-10T07:59:04.461050+00:00
status: active
---

# Grep-based verification validates dead code removal completeness

After removing orphaned modules, use systematic grep for `from X import` patterns across src/ and tests/ to confirm no remaining references. This catches both direct imports and transitive dependencies, and serves as the acceptance criterion for cleanup completeness.
