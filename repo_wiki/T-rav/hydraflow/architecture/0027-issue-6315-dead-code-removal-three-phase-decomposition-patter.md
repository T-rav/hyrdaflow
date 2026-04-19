---
id: 0027
topic: architecture
source_issue: 6315
source_phase: plan
created_at: 2026-04-10T03:43:46.872729+00:00
status: active
---

# Dead-code removal: three-phase decomposition pattern

Systematic approach: P1 removes core methods and constructor plumbing; P2 removes dependent tests and updates helpers; P3 verifies via grep and type checking. This phased structure prevents partial removals and ensures all callers are updated before verification.
