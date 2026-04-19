---
id: 0020
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849593+00:00
status: active
---

# Pre-Flight Validation and Escalation Pattern

Insert validation checks after environment setup but before main work. Return early with WorkerResult(success=False) on failure and escalate to HITL via escalator. This pattern cleanly separates precondition checking from implementation logic without entangling them. See also: Idempotency Guards for post-execution validation, Prevent Scope Creep for validation as design constraint.
