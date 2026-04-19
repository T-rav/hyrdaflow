---
id: 0058
topic: architecture
source_issue: 6332
source_phase: plan
created_at: 2026-04-10T05:33:08.098291+00:00
status: active
---

# Coordinator + focused helpers decomposition pattern

Decompose oversized methods by creating a lean coordinator (30-50 lines) that delegates to focused single-concern helpers (12-45 lines each). This pattern applies when a method mixes concerns like prompt assembly, retry coordination, and validation. Each helper encapsulates one concern; the coordinator orchestrates them without duplicating logic.
