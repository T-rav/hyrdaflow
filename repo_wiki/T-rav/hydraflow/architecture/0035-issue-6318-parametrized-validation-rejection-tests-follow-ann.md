---
id: 0035
topic: architecture
source_issue: 6318
source_phase: plan
created_at: 2026-04-10T04:05:05.202985+00:00
status: active
---

# Parametrized validation rejection tests follow annotated-type pattern

Test annotated types by extending existing validation test classes with parametrized tests covering malformed inputs (rejection) and valid inputs (acceptance). This pattern isolates validation logic testing and reuses test infrastructure for new validators across multiple models.
