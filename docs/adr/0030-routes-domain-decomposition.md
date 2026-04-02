# ADR-0030: Dashboard Routes Domain Decomposition

## Status

Accepted

## Context

`src/dashboard_routes/_routes.py` was 4,178 lines with 95 route handlers in a single `create_router()` function. Route handlers captured 17+ closure variables (config, event_bus, state, pr_manager, etc.). Navigation, testing, and modification were difficult.

A `RouteContext` dataclass already existed (ADR-0007) bundling all dependencies, but all routes remained in one file.

## Decision

### Pattern: `register(router, ctx)` functions in domain files

Extracted 70 route handlers into 7 domain-specific files, each exporting a `register(router: APIRouter, ctx: RouteContext) -> None` function:

| Module | Routes | Scope |
|--------|--------|-------|
| `_epic_routes.py` | 3 | Epic tracking and release |
| `_crates_routes.py` | 9 | Crate CRUD, items, active, advance |
| `_hitl_routes.py` | 9 | HITL management, human-input |
| `_control_routes.py` | 13 | Pipeline control, admin tasks, bot-pr settings |
| `_metrics_routes.py` | 12 | Metrics, insights, runs, artifacts |
| `_reports_routes.py` | 5 | Bug report submission and tracking |
| `_state_routes.py` | 19 | Runtimes, repos, filesystem, GitHub |

### Why `register()` over `include_router()`

FastAPI's `include_router` with prefix mounting would change URL paths (e.g., `/api/control/start` becomes a sub-router concern). Since existing tests use `find_endpoint(router, "/api/control/start")` to locate handlers, changing the routing structure would break all 381 dashboard tests.

The `register(router, ctx)` pattern is simpler: each domain function decorates the shared router directly. No URL changes, no test changes, no prefix management. The domain files are just organizational — the runtime behavior is identical.

### What stays in `_routes.py`

`RouteContext` dataclass, `create_router()` coordinator, issue history routes (complex cache infrastructure), core routes (healthz, pipeline, sessions, websocket, SPA catchall), and all shared helper functions. This reduced `_routes.py` from 4,178 to 2,019 lines (52% reduction).

### Import structure

- Domain files import `RouteContext` from `dashboard_routes._routes` (direct, not via package)
- `_routes.py` imports domain files only inside `create_router()` (local imports, deferred)
- `__init__.py` re-exports public symbols from `_routes.py` and `_common.py`
- No circular import risk

## Consequences

- `_routes.py` is now navigable — 2,019 lines with a clear table of contents via the `_register_*` calls in `create_router()`
- Adding a new route domain: create `_<domain>_routes.py`, add a `register()` call in `create_router()`
- All 381 existing tests pass without modification (except 2 monkeypatch target updates)
- Further decomposition of the remaining 25 core routes is possible using the same pattern
