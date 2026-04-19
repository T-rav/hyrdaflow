---
id: 0101
topic: architecture
source_issue: 6354
source_phase: plan
created_at: 2026-04-10T07:09:55.773107+00:00
status: active
---

# Partial migrations of similar components create maintenance burden

When multiple similar classes share the same pattern (e.g., 8 runner instantiations with identical kwargs), refactoring only some of them creates future maintenance risk. Always refactor all instances together, even if some seem unnecessary. Use explicit line-number lists to catch all occurrences and prevent partial migrations.
