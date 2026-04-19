---
id: 0116
topic: architecture
source_issue: 6365
source_phase: plan
created_at: 2026-04-10T07:59:04.461030+00:00
status: active
---

# Distinguish similarly-named modules during cleanup

When removing dead code, watch for naming collisions—e.g., `verification.py` (orphaned formatter) vs `verification_judge.py` (active production code with real callers). Confusion between them can lead to removing live code or missing dependencies. Always verify caller graphs and module purpose separately.
