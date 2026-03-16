# ADR-0021: Persistence Architecture and Data Layout

**Status:** Proposed
**Date:** 2026-02-28

## Context

HydraFlow must persist state across process restarts, track active issues through
the pipeline, store event history, and organise logs/plans/memory/metrics for each
managed repository. The persistence layer must support:

- **Crash recovery**: if the orchestrator is killed mid-run, it must resume
  without re-processing completed work or losing track of in-flight issues.
- **Multi-repo isolation**: when a supervisor spawns one HydraFlow process per
  repository, each process must write to its own data directory without collisions.
- **Operational visibility**: dashboards and CLI tools need structured access to
  metrics snapshots, event streams, and session history.
- **Configuration flexibility**: operators must be able to relocate the data
  directory (e.g. to a mounted volume in Docker) without code changes.

Prior to formalising this decision, the data layout had grown organically. This ADR
captures the current architecture and makes the conventions explicit so that future
features (e.g. multi-repo dashboard aggregation, remote state backends) build on a
documented foundation.

## Decision

All HydraFlow persistent data lives under `config.data_root`, which defaults to
`<repo_root>/.hydraflow/`. The data root is resolved at startup with the following
precedence:

1. `HYDRAFLOW_HOME` environment variable (highest priority).
2. Explicit `data_root` field in `HydraFlowConfig`.
3. Default: `<repo_root>/.hydraflow/`.

Full config load order is: Pydantic defaults, config file, env vars, CLI args.
Path resolution runs in the order `_resolve_paths` then `_resolve_repo_and_identity`
then `_apply_env_overrides`.

### Data layout

```
<data_root>/                        # default: <repo_root>/.hydraflow/
  state.json                        # StateTracker crash-recovery state
  events.jsonl                      # EventBus append-only event log
  sessions.jsonl                    # Session history
  config.json                       # Persisted config snapshot
  logs/                             # Transcript and log files
  plans/                            # Saved implementation plans
  memory/                           # Memory and review-insight files
  metrics/<owner-repo>/             # Per-repo metrics (repo-slug namespaced)
    snapshots.jsonl                 # Dashboard-consumable metric snapshots
  runs/                             # Run artifacts
  manifest/                         # Codebase manifest snapshots
  cache/                            # Ephemeral caches
  verification/                     # Verification artifacts
```

### Persistence guarantees

- **Atomic writes**: `StateTracker.save()` uses `atomic_write()` (from
  `file_util`) to write `state.json`, preventing corruption from partial writes
  or crashes mid-flush.
- **Immediate persistence**: every state mutation calls `save()` immediately; there
  is no batching or deferred flush.
- **Pydantic validation on load**: `StateTracker.load()` deserialises with
  `StateData.model_validate()`. Corrupt or unreadable state files are reset to
  empty defaults and logged, rather than crashing the process.
- **Automatic migration**: legacy `bg_worker_states` entries are migrated to the
  newer `worker_heartbeats` schema on first load.

### Multi-repo namespacing

- `MetricsManager` scopes metric files under `metrics/{repo_slug}/` where
  `repo_slug` is `config.repo.replace("/", "-")`.
- `config.repo_data_root` provides a general-purpose repo-scoped subdirectory
  at `data_root / repo_slug`.
- The supervisor spawns isolated processes per repo with separate `HYDRAFLOW_HOME`
  values, giving each process its own `data_root`.
- Worktrees are scoped under `worktree_base / repo_slug / issue-{N}` to prevent
  collisions between same-numbered issues across repositories.

### Derived paths

The following `HydraFlowConfig` properties derive directories from `data_root`:

| Property | Path |
|----------|------|
| `log_dir` | `data_root / "logs"` |
| `plans_dir` | `data_root / "plans"` |
| `memory_dir` | `data_root / "memory"` |
| `state_file` | `data_root / "state.json"` |
| `event_log_path` | `data_root / "events.jsonl"` |
| `repo_data_root` | `data_root / repo_slug` |

All paths can be individually overridden via their respective config fields,
but the defaults ensure a single `data_root` change relocates everything.

## Consequences

**Positive:**

- **Single knob relocation**: setting `HYDRAFLOW_HOME` or `data_root` moves all
  persistent data, which is essential for Docker volume mounts and CI environments.
- **Crash resilience**: atomic writes and Pydantic-validated loads mean the
  orchestrator can be killed at any point and resume cleanly.
- **Multi-repo safety**: repo-slug namespacing in metrics and worktrees prevents
  data collisions when multiple repos are managed from a shared filesystem.
- **Structured layout**: dedicated subdirectories for logs, plans, memory, and
  metrics make it straightforward to add retention policies, backup scripts, or
  dashboard queries targeting specific data categories.

**Negative / Trade-offs:**

- **Single-file state bottleneck**: `state.json` is a single file rewritten on
  every mutation. This is adequate for current throughput but would not scale to
  hundreds of concurrent issues without moving to a database or partitioned state.
- **No built-in replication**: the data directory is local-only. High-availability
  setups require external solutions (e.g. shared NFS, object-store sync).
- **Flat event log**: `events.jsonl` grows without bound until rotation triggers
  (configurable via `event_log_max_size_mb` and `event_log_retention_days`). Large
  deployments should tune these values.
- **Implicit directory creation**: subdirectories are created on first use rather
  than at startup, which can obscure the full layout until the system has exercised
  all code paths.

## Alternatives considered

- **SQLite for state**: would remove the single-file bottleneck and enable
  concurrent reads, but adds a dependency and complicates atomic snapshot export.
  Not justified at current scale.
- **Per-issue state files**: would reduce write contention, but complicates
  querying across issues and makes crash recovery harder (must scan many files).
- **Remote state backend (S3/Redis)**: would enable multi-instance deployments,
  but introduces network failure modes and latency. Deferred until there is a
  concrete multi-instance requirement.

## Related

- Source memory: [#1624 — HydraFlow persistence architecture and data layout](https://github.com/T-rav/hydra/issues/1624)
- This ADR: [#1633](https://github.com/T-rav/hydra/issues/1633)
- `src/state.py:StateTracker` — crash-recovery state persistence
- `src/config.py:_resolve_paths` — data root and path resolution
- `src/config.py:HydraFlowConfig.data_root` — data root configuration
- `src/metrics_manager.py` — repo-slug namespaced metrics
- `src/file_util.py:atomic_write` — atomic file write helper
- ADR-0003 (Git Worktrees for Issue Isolation) — worktree isolation (complementary filesystem layout)
- ADR-0006 (RepoRuntime Isolation Architecture) — RepoRuntime isolation (per-repo process boundaries)
