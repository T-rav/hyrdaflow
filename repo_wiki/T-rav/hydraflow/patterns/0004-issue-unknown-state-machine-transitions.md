---
id: 0004
topic: patterns
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:38:18.766130+00:00
status: active
---

# State machine transitions

When extracting phase result classification or handling logic, preserve exact retry counter state and escalation conditions (like epic-child label swaps) from the original flow. These behavioral subtleties directly impact correctness of phase state transitions. Dry-run mode must not emit state-changing events (e.g., TRIAGE_ROUTING) to ensure dry-run has no observable side effects. Phase result routing through dispatch patterns must maintain the immutable return contract exactly (tuple[str, str | None] for parse()). Event/worker mappings must precede skip detection—EVENT_TO_STAGE and SOURCE_TO_STAGE mappings must be implemented together with skip detection logic. Run existing tests unchanged after refactoring as the primary regression test to validate behavior preservation.

See also: Backward compatibility and schema evolution — retry counter state preservation; Refactoring and testing practices — call site verification and test preservation; Concurrency and I/O safety — state mutation patterns.
