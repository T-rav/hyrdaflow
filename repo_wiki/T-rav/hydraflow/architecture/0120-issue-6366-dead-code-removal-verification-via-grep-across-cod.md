---
id: 0120
topic: architecture
source_issue: 6366
source_phase: plan
created_at: 2026-04-10T08:02:02.177024+00:00
status: active
---

# Dead code removal verification via grep across codebase

When removing unused functions, verify with grep across both src/ and tests/ directories to ensure no remaining references. Pattern: grep -rn "symbol_name" src/ and grep -rn "symbol_name" tests/ should both return zero results after removal.
