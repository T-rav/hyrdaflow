# ADR-0007: Dashboard API Architecture for Multi-Repo Scoping

**Status:** Accepted
**Date:** 2026-02-28

## Context

The dashboard routes (`dashboard_routes.py`) use a closure-based pattern where
all endpoints are defined inside `create_router()` and share `config`, `state`,
`event_bus`, and `orchestrator` via closure variables. This design assumes a
single repo context per dashboard instance.

The supervisor layer (`supervisor_service.py`, `supervisor_client.py`,
`supervisor_state.py`) already manages multi-repo lifecycle via a TCP protocol
with actions: `ping`, `list_repos`, `add_repo`, `remove_repo`. Each repo gets
its own subprocess with its own dashboard port.

The UI context (`HydraFlowContext.jsx`) already tracks `supervisedRepos` and
exposes `addRepoShortcut` / `removeRepoShortcut`. Sessions support repo
filtering via `state.load_sessions(repo=repo)`.

The key gap: operational endpoints lack `?repo=` scoping, and there are no
per-repo start/stop/status endpoints at the dashboard level. A user viewing the
dashboard sees only one repo's data with no way to switch or aggregate.

## Decision

Extend the dashboard API to support multi-repo scoping through two mechanisms:

1. **Query parameter scoping:** Add optional `?repo=<slug>` query parameters to
   operational endpoints (`/api/pipeline`, `/api/sessions`, `/api/metrics`,
   `/api/workers`). When omitted, the response covers the current repo (backward
   compatible). When provided, the dashboard proxies or filters to the specified
   repo.

2. **Repo management endpoints:** Add dashboard-level endpoints for repo
   lifecycle operations:
   - `GET /api/repos` — list managed repos with status (already exists via
     supervisor polling)
   - `POST /api/repos/{slug}/start` — start a repo runtime
   - `POST /api/repos/{slug}/stop` — stop a repo runtime
   - `GET /api/repos/{slug}/status` — per-repo health and pipeline state

3. **WebSocket scoping:** Extend the existing WebSocket connection to accept a
   `repo` parameter, allowing the frontend to subscribe to events from a
   specific repo or all repos.

## Consequences

**Positive:**
- Dashboard becomes repo-aware without breaking existing single-repo deployments.
- Frontend can switch between repos or show aggregated views.
- Repo lifecycle management moves from CLI-only to dashboard-accessible.

**Trade-offs:**
- Proxying to per-repo dashboard ports adds latency and complexity.
- WebSocket multiplexing for multiple repos requires message routing logic.
- Backward compatibility constraint means `?repo=` is optional, adding
  conditional paths in every endpoint.

## Alternatives considered

1. **Separate dashboard per repo with a meta-dashboard aggregator.**
   Rejected for initial implementation: adds operational complexity. May revisit
   for large-scale deployments.
2. **Embed repo awareness directly in `create_router()` closure.**
   Rejected: would require the single dashboard process to hold state for all
   repos, breaking the subprocess isolation model.
3. **Use the supervisor TCP protocol directly from the frontend.**
   Rejected: exposes internal protocol to the browser and requires a WebSocket
   bridge anyway.

## Related

- Source memory: #1617
- Implementation: #1468
- `src/dashboard_routes.py`, `src/dashboard.py`
- `src/hf_cli/supervisor_service.py`, `src/hf_cli/supervisor_client.py`
- `src/ui/src/context/HydraFlowContext.jsx`
- ADR-0006 (RepoRuntime isolation)
## Council Amendment Notes

The following amendments were generated from council feedback:

- Architect: The ADR is structurally sound and complementary to ADR-0008 (not superseded by it), but
- Pragmatist: ADR-0007 defines the API contract layer (query-param scoping, endpoint signatures, WebSocket
- Editor: The Architect's evidence that ADR-0008 explicitly references ADR-0007 as a prerequisite settles

These notes are intended to be incorporated before final acceptance.
