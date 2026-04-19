---
id: 0118
topic: architecture
source_issue: 6365
source_phase: plan
created_at: 2026-04-10T07:59:04.461047+00:00
status: active
---

# Inline implementations preferred over extracted utility classes

The orchestrator implements its own circuit-breaking logic (consecutive-failure counter at :926-1026) rather than using the extracted `CircuitBreaker` class. This suggests the project favors inline implementations for simple patterns over shared utility classes, reducing coupling and import complexity.
