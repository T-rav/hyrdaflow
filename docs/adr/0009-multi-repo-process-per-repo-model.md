# ADR-0009: Multi-Repo Process-Per-Repo Model

**Status:** Accepted
**Date:** 2026-02-28

## Context

HydraFlow needs to manage multiple GitHub repositories simultaneously while
keeping each repo's pipeline state, worktrees, and agent processes fully
isolated. A single-process multi-repo model would require threading repo
identity through every component (`StateTracker`, `EventBus`, `IssueStore`,
`WorktreeManager`, worker pools) and risk shared-state bugs between repos.

The supervisor (`hf_cli/supervisor_service.py`) already manages repo lifecycle
via a module-global `RUNNERS` dict of `RepoProcess` structs. Each
`RepoProcess` holds a `subprocess.Popen` handle, a dynamically allocated TCP
port, and the repo's filesystem path. The orchestrator (`orchestrator.py`)
creates a full `HydraFlowOrchestrator` per process with its own `StateTracker`,
`EventBus`, `IssueStore`, and service registry built by `build_services()`.

Runtime state for each managed repo lives under `.hydraflow/` in the repo
directory (or under `$HYDRAFLOW_HOME/<repo_slug>/` when the supervisor sets
`HYDRAFLOW_HOME`). Worktree paths are scoped via
`config.worktree_path_for_issue()` which resolves to
`<worktree_base>/<repo_slug>/issue-<num>`. The `_namespace_repo_paths()` helper
in `config.py` ensures state files (`state.json`, `events.jsonl`,
`sessions.jsonl`, `config.json`) are placed under the repo slug subdirectory,
with automatic migration of legacy flat files.

Cross-repo coordination is limited to the supervisor's TCP JSON protocol
(actions: `ping`, `list_repos`, `add_repo`, `remove_repo`) served on
`127.0.0.1` with the port persisted to `~/.hydraflow/supervisor-state.json`.

## Decision

Adopt the **process-per-repo** model as the canonical multi-repo architecture:

1. **One subprocess per repo.** The supervisor spawns a separate `cli.py`
   process for each managed repository via `subprocess.Popen` with
   `start_new_session=True`. Each process runs its own `asyncio` event loop
   with five concurrent pipeline stages (see ADR-0001).

2. **Environment-driven isolation.** The supervisor sets `HYDRAFLOW_HOME` to a
   repo-scoped directory (`STATE_DIR / slug`). Config resolution in
   `_resolve_paths()` reads this environment variable to set `data_root`,
   ensuring all state files, event logs, and session logs are isolated per repo.

3. **Repo-scoped worktrees.** `WorktreeManager` resolves worktree paths under
   `<worktree_base>/<repo_slug>/issue-<num>`, eliminating collision risk for
   same-numbered issues across repos. Per-repo `asyncio.Lock` instances
   (`_WORKTREE_LOCKS` keyed by `wt:<repo_slug>`) prevent concurrent
   create/destroy races within a single process.

4. **TCP supervisor protocol.** Cross-repo coordination (add/remove/list repos,
   health checks) uses a lightweight TCP JSON line protocol. The supervisor
   maintains `supervisor-state.json` for crash recovery of the repo registry.

5. **No shared mutable state.** Each repo process gets independent instances of
   `StateTracker`, `EventBus`, `IssueStore`, and the full service registry.
   The only shared artifact is the supervisor state file, which is written
   exclusively by the supervisor process.

## Consequences

**Positive:**
- Complete fault isolation: a crash in one repo's orchestrator does not affect
  other repos.
- No shared-state synchronization complexity — each process owns its data.
- Horizontal scaling: repos can be distributed across machines by running
  supervisors on different hosts.
- Simple mental model: debugging a repo means inspecting one process and its
  `$HYDRAFLOW_HOME` directory.
- Graceful lifecycle: the supervisor can stop/restart individual repo processes
  without affecting others (5-second graceful timeout before `SIGKILL`).

**Trade-offs:**
- Higher memory footprint: each repo process loads the full Python runtime,
  agent dependencies, and service registry independently.
- Branch naming uses `agent/issue-<num>` without repo scoping, relying on
  process-level git repo isolation rather than branch-name uniqueness across
  repos.
- TCP protocol is minimal (no auth, no TLS) — suitable for localhost only.
- Dynamic port allocation means ports change across restarts; consumers must
  read `supervisor-state.json` or query `list_repos` to discover dashboard
  URLs.
- GitHub API rate limits are per-token, not per-process — multiple repo
  processes sharing the same token compete for rate limit budget.

## Alternatives considered

1. **Single-process multi-repo with `RepoRuntime` abstraction.**
   Explored in ADR-0006. Provides tighter integration and lower overhead, but
   requires refactoring all components to accept a repo context parameter and
   risks shared-state coupling. The process-per-repo model achieves isolation
   without component refactoring.

2. **Container-per-repo (Docker).**
   Maximum isolation but adds Docker as a runtime dependency, complicates local
   development, and increases startup latency. May be revisited for
   cloud deployments.

3. **Thread-per-repo in a single process.**
   Python's GIL limits true parallelism for CPU-bound agent orchestration.
   Subprocess isolation avoids GIL contention and provides OS-level fault
   boundaries.

## Related

- **Supersedes ADR-0006** — ADR-0006 proposed in-process `RepoRuntime` isolation
  with the supervisor using `RepoRuntime` as the unit of start/stop. This ADR
  adopts `subprocess.Popen` process-per-repo instead, making ADR-0006's
  supervisor integration decision obsolete.
- Source memory: #1627
- ADR-0001 (Five concurrent async loops — per-process architecture)
- ADR-0006 (RepoRuntime isolation — superseded by this ADR)
- ADR-0008 (Multi-repo dashboard — supervisor-proxied aggregation)
- `src/hf_cli/supervisor_service.py` (`_start_repo`, `RUNNERS`, TCP protocol)
- `src/config.py` (`_resolve_paths`, `_namespace_repo_paths`, `worktree_path_for_issue`)
- `src/orchestrator.py` (`HydraFlowOrchestrator.__init__`)
- `src/worktree.py` (`WorktreeManager`, `_WORKTREE_LOCKS`)
- `src/state.py` (`StateTracker`)
