# ADR-0008: Multi-Repo Dashboard Architecture

**Status:** Accepted
**Date:** 2026-02-28

## Context

Each supervised repo gets its own orchestrator process on a dedicated port,
started by `supervisor_service._start_repo()`. The dashboard at each port serves
only that repo's pipeline, HITL, and worker data. Sessions are stored in a
shared `sessions.jsonl` and can span repos. The `supervisedRepos` array (polled
from `GET /api/repos` every 15 seconds) provides cross-repo status at the
supervisor level.

True multi-repo aggregation requires proxying to each repo's dashboard port or
introducing a new aggregation layer. The current architecture has no unified
view — users must navigate to different ports to see different repos.

## Decision

Adopt a **supervisor-proxied aggregation model** for the multi-repo dashboard:

1. **Supervisor as proxy:** The supervisor process (which already manages repo
   lifecycle) exposes a unified dashboard that proxies API requests to per-repo
   dashboard ports. The supervisor knows each repo's port via `RepoProcess.port`.

2. **Aggregated views:** Cross-repo views (pipeline overview, session list,
   metrics summary) are served by the supervisor dashboard, which fetches from
   each repo's API and merges results. Per-repo detail views proxy directly to
   the target repo's dashboard port.

3. **Shared session store:** Sessions remain in the shared `sessions.jsonl` with
   `SessionLog.repo` as the discriminator. The supervisor dashboard reads
   sessions directly (no proxy needed) and groups by repo.

4. **Frontend repo switching:** The React UI uses `supervisedRepos` to populate
   a repo selector. Selecting a repo scopes all views to that repo's data.
   An "All repos" option triggers the aggregated view.

5. **WebSocket fan-out:** The supervisor dashboard maintains one WebSocket per
   managed repo and fans out events to connected frontend clients, tagged with
   the source repo slug.

## Consequences

**Positive:**
- Single entry point for multi-repo visibility — no port-hopping.
- Per-repo isolation preserved: each repo still runs its own orchestrator.
- Incremental adoption: users can start with single-repo and add repos later.
- Session aggregation is natural since sessions are already shared.

**Trade-offs:**
- Supervisor becomes a bottleneck for dashboard traffic (mitigated by direct
  proxy passthrough for detail views).
- WebSocket fan-out adds connection management complexity.
- Aggregated views may have higher latency than single-repo views.
- Supervisor must handle partial failures (one repo's dashboard down).

## Alternatives considered

1. **Embedded multi-repo in a single orchestrator process.**
   Rejected: breaks the subprocess isolation model and complicates resource
   management. See ADR-0006 for the `RepoRuntime` isolation decision.

2. **Client-side aggregation (frontend fetches from multiple ports).**
   Rejected: exposes internal port topology to the browser, requires CORS
   configuration per repo, and complicates deployment behind reverse proxies.

3. **Shared database backend (replace JSON files with PostgreSQL/Redis).**
   Rejected for now: adds operational dependencies. May revisit for
   large-scale deployments where filesystem-based state becomes a bottleneck.

## Related

- Source memory: #1619
- Implementation: #1469
- `src/hf_cli/supervisor_service.py` (`_start_repo`, `RUNNERS`)
- `src/dashboard.py`, `src/dashboard_routes.py`
- `src/ui/src/context/HydraFlowContext.jsx`
- ADR-0006 (RepoRuntime isolation)
- ADR-0007 (Dashboard API multi-repo scoping)
