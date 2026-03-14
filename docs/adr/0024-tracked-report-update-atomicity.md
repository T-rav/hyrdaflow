# ADR-0024: TrackedReport Update Atomicity — Explicit Parameters over In-Place Mutation

**Status:** Proposed
**Date:** 2026-03-14

## Context

In `src/report_issue_loop.py`, the `linked_issue_url` field on a `TrackedReport` is
set by mutating the object returned from `StateTracker.get_tracked_report()` before
calling `update_tracked_report()`. This works because `get_tracked_report()` iterates
`self._data.tracked_reports` and returns a direct reference to the Pydantic model
stored in the list. Mutating that reference and then calling `update_tracked_report()`
(which also finds the same object by ID and calls `self.save()`) results in a single
`save()` that persists both the status change and the URL.

While correct today, this pattern is fragile:

1. **Copy semantics break it silently.** If `get_tracked_report()` is ever refactored
   to return a copy (e.g. via `model_copy()`, serialization round-trip, or a database
   query), the in-place mutation is silently lost — `linked_issue_url` would be set on
   the copy, not on the persisted object.

2. **No API contract guarantees reference identity.** Nothing in the method signature
   or docstring of `get_tracked_report()` promises that callers receive a mutable
   reference to the canonical instance. Future contributors may reasonably assume
   it returns a snapshot.

3. **Split responsibility.** The caller is responsible for knowing which fields
   `update_tracked_report` manages (status, history) vs. which must be set
   externally (linked_issue_url, linked_pr_url, progress_summary). This division
   is implicit and undocumented.

**Source memory:** Issue #2559 — [Memory] update_tracked_report linked_issue_url
atomicity pattern.

## Decision

Adopt explicit parameter passing as the standard pattern for updating `TrackedReport`
fields through `StateTracker`:

1. **Add optional keyword parameters** to `update_tracked_report()` for fields that
   callers currently set via in-place mutation: `linked_issue_url`, `linked_pr_url`,
   and `progress_summary`. When provided, these are applied to the model inside the
   method, before the single `save()` call.

2. **Callers must not rely on reference identity** from `get_tracked_report()`. All
   persistent mutations should go through `update_tracked_report()` parameters. The
   get method remains useful for reads and conditional logic but should be treated as
   returning an opaque snapshot.

3. **Single save() per update is preserved.** The method continues to locate the
   model by ID, apply all requested changes, append a history entry, and call
   `save()` exactly once — maintaining the same atomicity guarantee without relying
   on external mutation.

## Consequences

- **Resilience:** The update path is safe regardless of whether the state store
  returns references or copies, making it compatible with future persistence backends
  (database, cache, immutable snapshots).

- **Discoverability:** New contributors can see all mutable fields in the
  `update_tracked_report()` signature. No need to grep callers to discover which
  fields are set externally.

- **Backward compatibility:** Existing callers that set fields before calling
  `update_tracked_report()` continue to work until migrated, since the parameters
  are optional. Migration can be incremental.

- **Slightly larger method signature:** `update_tracked_report()` gains three
  optional keyword arguments. This is acceptable given the clarity benefit and is
  consistent with the existing `status`, `detail`, and `action_label` parameters.

## Alternatives Considered

- **Document the reference-identity contract instead:** Rejected because it creates
  a permanent coupling between the state store's internal data structure and caller
  behavior. Any persistence refactor (e.g. moving to SQLite) would break the
  contract.

- **Return a mutable proxy / wrapper object:** Over-engineered for the current scale
  of `TrackedReport` updates. The explicit-parameter approach is simpler and
  sufficient.

- **Freeze `TrackedReport` (make it immutable):** Would enforce copy semantics but
  require all updates to go through builder/replace patterns, adding complexity
  across many call sites without proportional benefit.

## Related

- Issue #2559 — Source memory: update_tracked_report linked_issue_url atomicity pattern
- Issue #2567 — This ADR task
- `src/state.py` — `StateTracker.get_tracked_report` (line ~930)
- `src/state.py` — `StateTracker.update_tracked_report` (line ~937)
- `src/report_issue_loop.py` — Caller that sets `linked_issue_url` before update
- `src/models.py` — `TrackedReport` model (line ~1466)
