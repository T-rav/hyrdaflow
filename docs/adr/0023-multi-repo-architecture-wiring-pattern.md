# ADR-0023: Multi-Repo Architecture Wiring Pattern

**Status:** Proposed
**Date:** 2026-03-08

## Context

HydraFlow's multi-repo support relies on `RepoRuntime` (bundles config, event bus,
state tracker, and orchestrator per repository) and `RepoRuntimeRegistry` (manages
multiple `RepoRuntime` instances by slug). Both abstractions exist in
`src/repo_runtime.py` and the dashboard routes in `src/dashboard_routes.py` already
accept an optional `registry` parameter with a `_resolve_runtime()` fallback that
transparently supports single-repo and multi-repo modes.

However, the wiring is incomplete in two places:

1. **`cli.py` `_run_main()`**: The dashboard-enabled path manually assembles bare
   `EventBus`, `EventLog`, and `StateTracker` instances instead of creating a
   `RepoRuntime`. The non-dashboard path correctly uses `RepoRuntime.create()`.
   This means the dashboard path bypasses the runtime abstraction, duplicating
   initialization logic and preventing multi-repo use when the dashboard is active.

2. **`dashboard.py`**: `HydraFlowDashboard` never passes a `RepoRuntimeRegistry`
   to `create_router()`, so the multi-repo API endpoints (`/api/runtimes`,
   `/api/runtimes/{slug}`, etc.) are always inoperative even though they are fully
   implemented in the router.

This gap was identified through memory issue #2266 and confirmed by code inspection.

## Decision

Adopt the following wiring pattern to close the multi-repo architecture gap:

1. **Unify `_run_main()` around `RepoRuntime`**: Both the dashboard and
   non-dashboard paths in `cli.py` should create a `RepoRuntime` (or
   `RepoRuntimeRegistry` for multi-repo configs) and derive `event_bus`, `state`,
   and `orchestrator` from it, eliminating the duplicate bare-object construction.

2. **Thread `RepoRuntimeRegistry` into the dashboard**: When multi-repo mode is
   active, `HydraFlowDashboard` should accept and forward the registry to
   `create_router()`, activating the already-implemented multi-repo API surface.

3. **Preserve single-repo backward compatibility**: The `_resolve_runtime()`
   fallback in `dashboard_routes.py` already handles the `registry=None` case.
   Single-repo deployments continue to work without any configuration change.

4. **Keep the process-per-repo model** (ADR-0009): Each repo's `RepoRuntime` runs
   its own orchestrator loops. The registry is a coordination index, not a shared
   execution context.

## Consequences

**Positive:**
- Single initialization path for all modes (dashboard / headless, single / multi-repo),
  reducing divergence and maintenance burden.
- Multi-repo dashboard endpoints become functional without new route code.
- Runtime lifecycle (start, stop, log rotation) is consistently managed through
  `RepoRuntime` regardless of deployment mode.
- Cleaner dependency injection: dashboard receives a registry rather than individual
  service references.

**Negative / Trade-offs:**
- Refactoring `_run_main()` touches the critical startup path; changes must be
  carefully tested to avoid regressions in single-repo mode.
- `HydraFlowDashboard` constructor gains an additional optional parameter, slightly
  increasing its surface area.
- Multi-repo mode remains opt-in and undertested until integration tests cover
  the registry lifecycle (see ADR-0022).

## Alternatives considered

- **Keep bare-object construction in `_run_main()`**: Avoids touching the startup
  path but permanently blocks multi-repo dashboard support and increases
  initialization code drift between dashboard and non-dashboard paths.
- **Replace `RepoRuntimeRegistry` with a service-locator pattern**: More flexible
  but adds indirection and makes dependency flow harder to trace. The explicit
  registry is simpler and sufficient for the current scale.
- **Move multi-repo wiring entirely into `orchestrator.py`**: Would centralize
  logic but conflates orchestration (loop scheduling) with runtime lifecycle
  management, violating the current separation of concerns.

## Related

- Source memory: #2266 — [Memory] Multi-repo architecture wiring pattern
- Decision issue: #2267 — [ADR] Draft decision from memory #2266
- ADR-0006: RepoRuntime Isolation Architecture (Superseded)
- ADR-0009: Multi-Repo Process-Per-Repo Model (Accepted)
- ADR-0007: Dashboard API Architecture for Multi-Repo Scoping (Accepted)
- ADR-0008: Multi-Repo Dashboard Architecture (Accepted)
- `src/repo_runtime.py` — `RepoRuntime` and `RepoRuntimeRegistry`
- `src/cli.py` — `_run_main()` startup path
- `src/dashboard_routes.py` — `create_router()` and `_resolve_runtime()`
