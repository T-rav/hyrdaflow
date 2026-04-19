---
id: 0041
topic: architecture
source_issue: 6323
source_phase: plan
created_at: 2026-04-10T04:47:03.630680+00:00
status: active
---

# Move generic utilities to module-level functions to keep classes small

Rather than making `polling_loop` an instance method of LoopSupervisor, extract it as a module-level async function (~80 lines). This keeps the supervisor class under 200 lines while keeping polling logic independently testable. Orchestrator retains `_polling_loop()` as a thin wrapper for backward compatibility with existing mocks. This pattern aligns with codebase wiki guidance: 'Prefer module-level utility functions over instance methods.'
