---
id: 0098
topic: architecture
source_issue: 6350
source_phase: plan
created_at: 2026-04-10T06:55:39.084060+00:00
status: active
---

# Config tuples enable clean parameterized loops

Replace copy-paste blocks with a list-of-tuples configuration like `[(Bank.TRIBAL, "learnings", "memory"), ...]` where each tuple drives one loop iteration. Each position in the tuple holds enum value, display label, and dict key. This pattern scales to N similar blocks and makes the parameterization explicit and maintainable.
