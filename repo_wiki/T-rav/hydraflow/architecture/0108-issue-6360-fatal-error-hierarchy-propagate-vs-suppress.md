---
id: 0108
topic: architecture
source_issue: 6360
source_phase: plan
created_at: 2026-04-10T07:37:26.758732+00:00
status: active
---

# Fatal error hierarchy—propagate vs. suppress

AuthenticationError and CreditExhaustedError are fatal and must propagate; all other exceptions are suppressed. This pattern is canonical across the codebase (base_background_loop.py:141, orchestrator.py:948, phase_utils.py:392). Always catch fatal errors first in except clauses before a generic Exception fallback.
