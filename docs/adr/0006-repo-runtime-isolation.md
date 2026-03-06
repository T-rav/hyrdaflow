# ADR-0006: RepoRuntime Isolation Architecture

**Status:** Superseded by ADR-0009
**Date:** 2026-02-28

## Context

HydraFlow is fundamentally single-repo per process. Each `HydraFlowOrchestrator`
owns one `IssueStore` (deque-based queues), one `StateTracker` (JSON file), one
`EventBus`, and 11 async loop tasks. The supervisor (`supervisor_service.py`)
uses a module-global `RUNNERS` dict of `RepoProcess` structs and
`subprocess.Popen` to spawn per-repo workers. State isolation is implicit via
the filesystem: each repo has its own `.hydraflow/` directory.
`SessionLog.repo` is the only explicit repo-namespaced field.

This implicit isolation model has several drawbacks:

- No formal lifecycle boundary between repos running in the same process.
- Adding in-process multi-repo support requires threading repo identity through
  every component manually.
- Shared global state (e.g., background loop registries) creates coupling between
  repos that should be independent.

## Decision

Introduce a `RepoRuntime` abstraction that wraps `Orchestrator + StateTracker +
EventBus + IssueStore` as a formal isolation boundary. Each repo slug gets one
`RepoRuntime` instance that owns its full mutable runtime state.

Key elements:

1. **`RepoRuntime` class** bundles per-repo orchestrator, state tracker, event
   bus, issue store, and worker pools into a single lifecycle unit.
2. **`RepoRuntimeRegistry`** manages runtime creation, lookup by slug, and
   graceful shutdown ordering.
3. **CLI entry point** (`cli.py`) constructs a `RepoRuntime` instead of manually
   assembling individual services.
4. **Supervisor integration** uses `RepoRuntime` as the unit of start/stop
   rather than raw `subprocess.Popen`.

## Consequences

**Positive:**
- Explicit lifecycle boundary makes multi-repo support tractable.
- Per-repo state is fully encapsulated — no shared globals between repos.
- Graceful shutdown can drain one repo without affecting others.
- Testing becomes simpler: instantiate a `RepoRuntime` with test config.

**Trade-offs:**
- One additional abstraction layer between CLI and orchestrator.
- Existing single-repo users see no behavior change but get a new code path.
- Migration requires refactoring `cli.py` and supervisor service.

## Alternatives considered

1. **Keep implicit isolation via subprocess boundaries.**
   Rejected: limits in-process multi-repo support and makes shared dashboard
   proxying complex.
2. **Thread repo slug through all components without a wrapper.**
   Rejected: high coupling, error-prone, and every component needs repo awareness.

## Related

- Source memory: #1615
- Implementation: #1467
- `src/orchestrator.py`, `src/state.py`, `src/issue_store.py`, `src/events.py`
- `src/hf_cli/supervisor_service.py`
