---
id: 0104
topic: architecture
source_issue: 6355
source_phase: plan
created_at: 2026-04-10T07:14:58.678259+00:00
status: active
---

# Return Value Threading in Orchestrator Pattern

When extracting helpers from a large method, extracted helpers should return values needed by downstream logic. The orchestrator captures these returns and threads them to consuming functions (e.g., metrics collection). This maintains clean value flow without side effects.
