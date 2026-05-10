---
id: 0006
topic: testing
source_issue: 7644
source_phase: review
created_at: 2026-05-07T07:44:17.831331+00:00
status: active
corroborations: 1
---

# Pin function signatures in one canonical location before writing any callers

Decide the authoritative signature (argument order, return tuple order) in the source file first; then write docs and tests to match that single source of truth.

- `_diff_targets` was documented as `(a, b) -> (warnings, to_add)` in one artifact
- Tests called it as `(a) -> (to_add, warnings)` — a different arity and reversed return order

Steps: write the function stub → copy its exact signature into the docstring → write the test.

**Why:** When docs and tests are authored before implementation, signature drift goes undetected until runtime, and both artifacts may be wrong.
