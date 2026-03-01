# ADR-0010: Worktree and Path Isolation Architecture

**Status:** Proposed
**Date:** 2026-02-28

## Context

HydraFlow's supervisor spawns separate `cli.py` processes per repository, each
with an isolated `HYDRAFLOW_HOME` environment variable. This provides
process-level `data_root` isolation: state files, event logs, and session data
are scoped under `data_root/<repo_slug>/` via `_namespace_repo_paths` in
`config.py`.

However, not all filesystem paths follow the same scoping discipline:

1. **Worktree base** defaults to `repo_root.parent / "hydraflow-worktrees"` — a
   flat sibling directory. When multiple repos share the same parent directory,
   worktrees from different repos could collide if issue numbers overlap (e.g.,
   both `org/repo-a` and `org/repo-b` have issue #42).

2. **Log, plan, and memory directories** (`config.log_dir`, `config.plans_dir`,
   `config.memory_dir`) resolve to `data_root/logs/`, `data_root/plans/`, and
   `data_root/memory/` respectively — flat paths with no repo-slug scoping.
   When `HYDRAFLOW_HOME` points to a shared directory, transcript files
   (e.g., `transcript-issue-42.jsonl`) and plan files (e.g., `issue-42.md`)
   from different repos overwrite each other.

3. **Docker mounts** bind `config.log_dir` to `/logs` inside the container.
   Since `log_dir` is unscoped, containers for different repos share the same
   host log directory.

4. **Metrics cache** already follows the repo-slug pattern correctly:
   `state_file.parent / "metrics" / repo_slug / snapshots.jsonl`. This
   demonstrates the desired scoping pattern.

The net result is a mixed isolation model: some paths are fully repo-scoped
(state, events, sessions, metrics, worktrees via `worktree_path_for_issue`)
while others (logs, plans, memory) are not, creating collision risk in
multi-repo deployments with a shared `HYDRAFLOW_HOME`.

## Decision

Adopt the following path isolation strategy for all per-repo filesystem
artifacts:

1. **Worktree paths are repo-scoped.** `worktree_path_for_issue` already
   resolves to `worktree_base / repo_slug / issue-{N}/`, preventing cross-repo
   worktree collisions. This is the correct behavior and must be preserved.

2. **State, events, and session files are repo-scoped.** `_namespace_repo_paths`
   moves `state.json`, `events.jsonl`, and `sessions.jsonl` under
   `data_root/<repo_slug>/`. This is correct and must be preserved.

3. **Logs, plans, and memory directories should follow the repo-slug pattern.**
   These properties in `HydraFlowConfig` should resolve to
   `data_root/<repo_slug>/logs/`, `data_root/<repo_slug>/plans/`, and
   `data_root/<repo_slug>/memory/` respectively, matching the scoping model
   used by state files and metrics.

4. **Docker log mounts inherit from the scoped `log_dir`.** No change is needed
   in `DockerRunner._build_mounts` once `config.log_dir` itself is repo-scoped.

5. **Backward-compatible cleanup.** `WorktreeManager.destroy_all` already scans
   both the repo-scoped layout (`worktree_base/<slug>/issue-N/`) and the legacy
   flat layout (`worktree_base/issue-N/`) for backward compatibility. A similar
   migration approach should be used if log/plan directories are relocated.

## Consequences

**Positive:**
- Eliminates collision risk for logs, plans, and memory when multiple repos
  share a `HYDRAFLOW_HOME` directory.
- Aligns all per-repo paths with a single consistent pattern
  (`data_root/<repo_slug>/<artifact>/`), making the isolation model easier to
  reason about.
- Docker containers automatically inherit correct scoping without mount changes.
- The existing `repo_slug` property (`config.repo.replace("/", "-")`) provides
  a proven, collision-free namespace key.

**Trade-offs:**
- Relocating `log_dir`, `plans_dir`, and `memory_dir` changes existing file
  paths. Deployments that reference these paths in external tooling (log
  aggregators, backup scripts) need to update their configuration.
- Single-repo deployments (where `data_root` defaults to
  `<repo_root>/.hydraflow/`) gain an extra directory level with no functional
  benefit, since isolation is already implicit.
- The metrics cache path becomes triple-nested
  (`data_root/<slug>/metrics/<slug>/`) which is redundant but harmless.

## Alternatives considered

1. **Keep flat directories, rely on process isolation.**
   Rejected: works only when each process has a unique `HYDRAFLOW_HOME`.
   Breaks when a shared home is used intentionally (e.g., centralized logging).

2. **Scope by repo only at the file level (e.g., `logs/repo-slug-issue-42.jsonl`).**
   Rejected: requires changes to every file-writing callsite. Directory-level
   scoping is simpler and requires only property changes in `config.py`.

3. **Introduce a `RepoRuntime` wrapper that manages all paths.**
   Deferred to ADR-0006. `RepoRuntime` is the right long-term abstraction but
   path scoping can be applied incrementally via config properties without
   waiting for the full `RepoRuntime` refactor.

## Related

- Source memory: #1635
- Implementation: #1677
- ADR-0003 — Git Worktrees for Issue Isolation (original worktree decision)
- ADR-0006 — RepoRuntime Isolation Architecture (broader isolation abstraction)
- `src/config.py:HydraFlowConfig` — `_resolve_paths`, `worktree_path_for_issue`,
  `log_dir`, `plans_dir`, `memory_dir` properties
- `src/worktree.py:WorktreeManager` — worktree lifecycle and cleanup
- `src/docker_runner.py:DockerRunner._build_mounts` — container mount strategy
- `src/metrics_manager.py:get_metrics_cache_dir` — repo-slug scoping reference
