---
id: 0002
topic: patterns
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:38:18.766124+00:00
status: active
---

# Refactoring and testing practices

**Refactoring**: Before changing function signatures, grep the codebase to find all call sites and confirm scope. For public functions, use `git grep` to verify zero remaining matches after refactoring. Changes to widely-used utilities require exhaustive caller audits—missing even one call site causes `TypeError` at runtime. When return types change (e.g., `str | None` → `dict | None`), all callers must be updated atomically in a single commit. Preserve public/semi-public method signatures using thin delegation stubs, `__getattr__` facades, or mixin inheritance from shared base clients when tests/external code depend on extracted code; use optional parameters to gate composition logic when decomposing large methods. Extract pure transform functions first—they lack mutable closure state and are lowest-risk candidates. Error isolation preservation: preserve per-concern try/except blocks exactly as-is to prevent failures in one concern from blocking others. Keep early-return cases inline in parent rather than extracting. Extract to pure module-level functions before moving to new classes for independent testability. Pre-compute loop variables outside iteration (e.g., `event_type = str(...)`). Remove vestigial variables from incomplete features, guards for dead paths, and functions with trivial implementations if they have no production callers. Extract duplicated JSONL-reading logic to shared `_load_jsonl(path, label)` helpers to prevent divergence and ensure consistency across refactors.

**Testing**: Mock at the definition site (e.g., `hindsight.tombstone_safe`) not the import site, combined with deferred imports inside test methods—prevents import-time failures and keeps optional dependencies truly optional. When testing dependency injection, explicitly verify that the injected dependency is used instead of self-constructed. Verify protocol implementation via structural subtype checks (signature inspection with `inspect.signature()`) rather than `isinstance()`. When methods are moved during refactoring, retarget mock patches to the new location before refactoring to preserve mock interception at the facade level. Both parametrized tests and explicit named spot-check methods improve readability. Supply async variants of sync methods with a-prefix (arecord_outcome, aupdate_scores) following Python conventions. Generated content (test skeletons, comments) must not reference line numbers—use exact function/class names and string search for stability across refactors. Meta-tests scan the codebase for anti-patterns and fail if found (e.g., `sys.path.insert` outside conftest.py). Run existing tests unchanged after refactoring as the primary regression test.

See also: Backward compatibility and schema evolution — type narrowing and state preservation; Concurrency and I/O safety — error isolation and crash-safe patterns; State machine transitions — test preservation and dispatcher refactoring.
