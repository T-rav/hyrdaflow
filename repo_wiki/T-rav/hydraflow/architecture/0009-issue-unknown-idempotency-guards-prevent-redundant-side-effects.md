---
id: 0009
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849551+00:00
status: active
---

# Idempotency Guards Prevent Redundant Side Effects

Add idempotency guards by checking outcome state at handler entry: `if state.get_outcome(issue_number) == MERGED: return`. This prevents redundant side effects (label swaps, counter increments, hook re-execution) from race conditions or retries. Log at info level when guard triggers for observability. Test three cases: (1) outcome already exists—side effects don't execute, (2) no prior outcome—normal flow, (3) non-MERGED outcome—normal flow. Use test helper pattern: `_setup_*()` method returning setup object with `.call()` method for test invocation. This pattern ensures idempotent handlers don't over-suppress valid operations. See also: Pre-Flight Validation for related validation patterns, State Persistence for outcome storage.
