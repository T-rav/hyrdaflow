# ADR-0019: Background Task Delegation — Call the Right Abstraction Layer

**Status:** Proposed
**Date:** 2026-03-01

## Context

HydraFlow runs background tasks that must trigger high-level operations on
shared state (e.g. releasing an epic, closing completed epics, refreshing
caches).  Two concrete bugs exposed a recurring pattern:

1. **Wrong delegation target.**  `PostMergeHandler._handle_merge` needed to
   trigger epic-level release logic after a child PR merged.  The handler
   originally called `EpicChecker.check_and_close_epics(issue_number)` — a
   method designed for a *different* trigger point (post-merge completion
   scanning) — instead of `EpicManager.release_epic(epic_number)`, the
   authoritative entry-point for the release operation.  The two methods touch
   overlapping state but have entirely different preconditions, locking, and
   side-effects:

   | Method                     | Trigger point       | Key behaviour                          |
   |----------------------------|---------------------|----------------------------------------|
   | `check_and_close_epics`    | Post-merge hook     | Scans *all* open epics, closes any whose children are done |
   | `release_epic`             | API / dashboard     | Lock-protected, idempotent, sequential merge of a single epic's PRs |
   | `on_child_completed`       | Post-merge hook     | Marks one child done and attempts auto-close |

   Calling the wrong method skipped the per-epic lock, bypassed the
   `released` idempotency guard, and could merge PRs out of order.

2. **Cache TTL sentinel not updated on all write paths.**  When a direct
   caller wrote to a shared in-memory cache (e.g. the issue-fetcher
   collaborator cache), the TTL sentinel tracking freshness was only updated in
   the *scheduled* refresh path.  Direct callers wrote valid data that was
   immediately treated as stale on the next read, triggering unnecessary API
   calls and occasionally returning empty results during the re-fetch window.

Both issues share a root cause: a background task delegated to a *similar-
looking* method rather than the *authoritative* method for the intended
operation, and the difference was invisible without tracing the full call
graph.

## Decision

Adopt the following rules for background-task delegation in HydraFlow workers:

1. **Always call the highest-level authoritative method for the intended
   operation.**  If a dashboard endpoint or CLI command exposes a method for an
   operation (e.g. `release_epic`), background tasks that need the same
   operation must call that same method — not a lower-level helper or a
   different hook that happens to touch the same state.

2. **Trace the full call graph before wiring a delegation.**  Before a
   background task delegates to any method, the implementer must trace the
   call chain to confirm that the method's preconditions (locking, guards,
   state mutations, event publication) match the background task's execution
   context.

3. **Cache writes must always update the TTL sentinel.**  Every code path that
   writes to a shared cache must also update the associated freshness sentinel
   (e.g. `_last_refresh`, `_cache_updated_at`) so that subsequent reads see
   the data as fresh.  This applies to both scheduled refresh paths and direct
   / ad-hoc writes.

4. **Distinguish hooks from operations in naming.**  Methods that are designed
   as event hooks (`on_child_completed`, `check_and_close_epics`) should be
   clearly named and documented as hooks.  Methods that are authoritative
   entry-points for an operation (`release_epic`) should be clearly named as
   such.  Background tasks must call operations, not hooks, unless they are
   genuinely responding to the hook's event.

## Consequences

**Positive:**

- Eliminates a class of subtle state-corruption bugs where background tasks
  bypass locking, idempotency guards, or ordering constraints.
- Makes cache behaviour consistent: reads always see fresh data after any
  write, regardless of the write path.
- Improves code reviewability — reviewers can check that a delegation target
  matches the operation's authoritative entry-point instead of reasoning about
  whether a similar-looking alternative is safe.

**Trade-offs:**

- Requires implementers to trace call graphs during development, adding
  upfront effort for each new background task or delegation change.
- Authoritative methods may need to be made more accessible (e.g. moved to a
  shared service) if background tasks currently only have access to lower-level
  helpers.
- Strict naming conventions (hook vs. operation) require ongoing discipline
  during code review.

## Alternatives considered

1. **Centralised task dispatcher with method-type validation.**
   A registry that tags methods as "hook" or "operation" and rejects
   hook-to-operation mismatches at dispatch time.
   Rejected: high implementation cost for a problem better solved by naming
   conventions and review discipline.

2. **Wrap all shared state behind a single facade.**
   Force all writes through a single `StateManager` that auto-updates TTL
   sentinels.
   Rejected for now: would require a large refactor of `EpicManager`,
   `EpicChecker`, `IssueFetcher`, and `StateTracker`.  May revisit if cache
   bugs recur.

3. **Lint rule requiring docstrings on public methods to declare trigger context.**
   Rejected: too noisy and unlikely to catch transitive call-graph issues.

## Related

- Source memory: #1793
- `src/epic.py` — `EpicManager.release_epic`, `EpicChecker.check_and_close_epics`, `EpicManager.on_child_completed`
- `src/post_merge_handler.py` — `PostMergeHandler._handle_merge` (delegation call-site)
- `src/issue_fetcher.py` — collaborator cache TTL pattern
- `src/dashboard_routes.py` — `release_epic` API entry-point
