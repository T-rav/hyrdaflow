# State & Persistence Area Review — Slice 5.6

**Date:** 2026-05-12
**Auditor:** Claude Code (slice #5.6 of 5)
**Branch:** `audit+coverage-matrix-baseline` from `origin/staging`
**ADR reference:** ADR-0021 (Persistence Architecture and Data Layout), ADR-0028 (Event-Driven Report Pipeline)

## Overview

Per-area review of the State & Persistence functional area as defined in
`docs/arch/functional_areas.yml`. This area has no loops. Members are:

- `src/state/**` — `StateTracker` + 33 domain-specific mixins
- `src/events.py` — `EventBus` + `EventLog` (JSONL persistence)
- `src/file_util.py` — `atomic_write`, `append_jsonl`, `file_lock`, `rotate_backups`
- `src/models.py:StateData` + `LifetimeStats` + `SessionLog` — schema layer
- `src/metrics_manager.py` — snapshots.jsonl under repo-scoped metrics dir
- `src/dedup_store.py` — `DedupStore` (atomic JSON set, used by 14+ callers)
- `src/state_restorer.py` — startup restoration from persisted state

Audit dimensions (adapted for a persistence area — no loops, no subprocess runners):

1. **Schema quality** — clean / minor / needs-rewrite
2. **Migration test coverage** — covered / thin / missing
3. **Schema-doc fidelity** — matches-reality / drift-risk / undocumented
4. **Persistence safety** — safe / unsafe / not-applicable
5. **Wiki/ADR currency** — documented / sparse / undocumented

Cell vocabulary: ✅ / ⚠️ / ❌ / N/A

---

## Component Audit Matrix

| Component | Schema quality | Migration tests | Schema-doc fidelity | Persistence safety | Docs |
|-----------|---------------|----------------|---------------------|--------------------|------|
| `StateTracker` (core) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `StateData` (Pydantic schema, 91 fields) | ⚠️ | ⚠️ | ✅ | N/A | ⚠️ |
| `LifetimeStats` | ✅ | ✅ | ✅ | N/A | ✅ |
| `SessionLog` / `_session.py` | ✅ | ✅ | ✅ | ✅ | ✅ |
| Worker heartbeat migration (`_worker.py`) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `EventLog` / `EventBus` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `file_util` (`atomic_write`, etc.) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `metrics_manager.py` (snapshots.jsonl) | ✅ | ✅ | ⚠️ | ✅ | ⚠️ |
| `dedup_store.py` | ✅ | ✅ | ❌ | ✅ | ❌ |
| `log_dir` / `plans_dir` / `memory_dir` (flat paths) | N/A | N/A | ⚠️ | N/A | ⚠️ |
| `diagnostics_dir` / `visual_reports_dir` | N/A | N/A | ❌ | N/A | ❌ |

### Column totals

| Dimension | ✅ | ⚠️ | ❌ | N/A |
|-----------|---|---|---|-----|
| Schema quality | 8 | 1 | 0 | 2 |
| Migration tests | 8 | 1 | 0 | 2 |
| Schema-doc fidelity | 7 | 3 | 2 | 2 (log/plans/memory + diagnostics/visual) |
| Persistence safety | 8 | 0 | 0 | 3 |
| Docs | 7 | 2 | 2 | 2 |

**Total gap cells (⚠️ or ❌): 12**

---

## Per-Component Notes

### StateTracker (core)

- **Schema quality ✅:** Well-structured mixin decomposition into 33 domain files.
  `StateTracker.__init__.py` is 275 lines; each mixin is focused and has a clear
  domain (worker, session, issue, lifetime, etc.). No dead fields found in the core
  class.
- **Migration tests ✅:** `test_state_persistence.py`, `test_state.py`, and
  `test_integration_file_io.py` together cover atomic save, backup/restore from
  corrupt primaries, backup rotation, rollback on fsync failure, and roundtrip
  model validation. `test_state_tracking.py` covers the legacy
  `bg_worker_states → worker_heartbeats` migration.
- **Schema-doc fidelity ✅:** `load()` -> `_load_from_file()` -> `_maybe_migrate_worker_states()`
  chain is documented in ADR-0021 §Automatic migration.
- **Persistence safety ✅:** Every mutation calls `save()` immediately. `save()` uses
  `atomic_write()` (fsync + os.replace). Backup rotation is timed-interval, not per-call.
  Backup restore from `.bak`/`.bak.1`/`.bak.2` is tested for all three levels.
- **Docs ✅:** ADR-0021 references `src/state:StateTracker` directly.

### StateData (Pydantic schema, 91 fields)

- **Schema quality ⚠️:** The schema has grown to 91 fields. Four fields use weakly
  typed containers: `rc_budget_duration_history: list[dict[str, Any]]`,
  `escalation_contexts: dict[str, dict[str, object]]`,
  `diagnostic_attempts: dict[str, list[dict[str, object]]]`, and
  `trace_runs: dict[str, dict[str, object]]`. These are pockets of structural opacity
  that resist type checking and make schema evolution harder to verify. The rest of
  the schema is well-typed and uses Pydantic models.
- **Migration tests ⚠️:** Backward migration (old file without new fields) is
  well-tested — Pydantic defaults handle it automatically and there is a test for it
  (`test_handles_partial_data`). Forward migration (loading a file that has fields
  not in the current schema) is not explicitly tested. Pydantic's default behavior
  is `extra='ignore'` (confirmed at runtime: `StateData.model_config` returns `{}`
  meaning the default applies), which silently drops unknown fields. This is the
  correct behavior for forward compatibility, but the lack of an explicit test means
  future changes to `model_config` could break forward compat without a test failure.
- **Schema-doc fidelity ✅:** Field comments in `models.py` generally explain which
  loop or spec section each field serves. ADR-0021 notes the `schema_version: int = 1`
  field, and its tests exist in `test_state.py`.
- **Docs ⚠️:** ADR-0021 documents the overall layout but does not enumerate the 91
  fields or their growth policy. As the schema grows, there is no documented plan for
  when fields graduate to their own sub-model or get retired. Several fields added
  for specific loops carry only inline comments (`# Trust fleet — ...`), not wiki entries.

### LifetimeStats

- **Schema quality ✅:** Clean; all counters have clear names and documented purpose.
  Duration-list fields (`plan_durations`, `implement_durations`, etc.) are
  appropriately typed as `list[float]`.
- **Migration tests ✅:** `test_state_persistence.py::TestLifetimeStatsModel` covers
  zeroed defaults and model_copy independence. Roundtrip tested in
  `TestStateDataModel.test_model_dump_roundtrip`.
- **Schema-doc fidelity ✅:** `LifetimeStats.reset()` logic in `StateTracker.reset()`
  preserves lifetime stats across resets — this matches the ADR intent.
- **Persistence safety N/A:** Pure data model.
- **Docs ✅:** Well-named; no wiki entry needed beyond what exists in ADR-0021.

### SessionLog / `_session.py`

- **Schema quality ✅:** `SessionLog` and `SessionCounters` are clean Pydantic models.
  Session JSONL is append-only with atomic rewrite for pruning. Deduplication by
  `session.id` (last-write-wins) handles crash-interrupted double-writes.
- **Migration tests ✅:** `test_state_sessions.py` covers corrupt lines, OSError on
  save, UnicodeDecodeError, `prune_sessions`, deduplication, and `get_session`.
- **Schema-doc fidelity ✅:** ADR-0021 §Session history documents `sessions.jsonl`
  at `repo_data_root / "sessions.jsonl"` and the flat-layout migration on first load.
  `_sessions_path` property in `_session.py` resolves to `self._path.parent / "sessions.jsonl"`,
  which equals `repo_data_root / "sessions.jsonl"` — consistent with the ADR.
- **Persistence safety ✅:** `save_session` uses `f.flush()` (no fsync, acceptable for
  append-only). `prune_sessions` uses `atomic_write`.
- **Docs ✅:** ADR-0021 §Session history covers it. `functional_areas.yml` references
  `src/session_log.py` but this file does not exist — session logic is in
  `src/state/_session.py`. Minor manifest drift (low impact).

### Worker heartbeat migration (`_worker.py`)

- **Schema quality ✅:** `_maybe_migrate_worker_states()` is a clean one-direction migration
  (`bg_worker_states → worker_heartbeats`) that runs on load and self-heals.
- **Migration tests ✅:** `test_state_tracking.py::TestBGWorkerStateTracking.test_legacy_state_file_migrates_bg_worker_states_to_heartbeats`
  covers the migration explicitly.
- **Schema-doc fidelity ✅:** Documented in ADR-0021 §Automatic migration.
- **Persistence safety ✅:** Migration triggers `save()` which uses `atomic_write`.
- **Docs ✅:** The `active_workspaces / active_worktrees` alias is also handled via
  `AliasChoices` in `StateData` — tested by the worktree alias test in
  `test_state_tracking.py`.

### EventLog / EventBus

- **Schema quality ✅:** `EventLog` is clean — append via `asyncio.to_thread` +
  `file_lock`, rotate under lock (prevents TOCTOU), load with per-line error
  handling. `EventBus.flush_persists()` for deterministic drain in tests is a
  thoughtful test-seam.
- **Migration tests ✅:** `test_event_persistence.py` is comprehensive: 36 tests
  covering append, load with filters, corrupt lines, rotation under size threshold,
  rotation atomicity, empty lines, EventBus history ID advance after load.
- **Schema-doc fidelity ✅:** `events.jsonl` is at `data_root/<repo_slug>/events.jsonl`
  in code and matches ADR-0021 layout table.
- **Persistence safety ✅:** Append uses `file_lock` + `append_jsonl` (fsync). Rotate
  holds lock across the read-filter-atomic_write cycle, preventing the append-race
  that would lose events on the old inode.
- **Docs ✅:** ADR-0021 §Flat event log covers it. ADR-0028 covers `EventBus` event
  types for the report pipeline.

### `file_util` (`atomic_write`, `append_jsonl`, `file_lock`, `rotate_backups`)

- **Schema quality ✅:** 113 lines, no debt. The `atomic_write` cleanup on `BaseException`
  uses `contextlib.suppress` to avoid swallowing the original exception.
- **Migration tests ✅:** `test_state_persistence.py::TestAtomicSave` and
  `test_integration_file_io.py::TestAtomicWrite/TestAppendJsonl/TestFileLock`
  together give fsync failure, fdopen failure, temp-file cleanup, same-directory
  placement, and concurrent-access serialization (10 iterations, 3 threads).
- **Schema-doc fidelity ✅:** Matches wiki entry "Atomic writes with fsync and replace
  for crash safety" in `docs/wiki/architecture-state-persistence.md`.
- **Persistence safety ✅:** All three guarantees met: temp file in same directory,
  fsync before replace, cleanup on any failure.
- **Docs ✅:** Wiki covers this area well.

### `metrics_manager.py` (snapshots.jsonl)

- **Schema quality ✅:** `MetricsManager` is clean. Hash-based dedup avoids writing
  unchanged snapshots. `MetricsSnapshot` is a well-typed Pydantic model.
- **Migration tests ✅:** Tests exist in `tests/test_review_phase_metrics.py` and
  `tests/test_dashboard_routes_state.py`.
- **Schema-doc fidelity ⚠️:** ADR-0021 data layout shows:
  `<data_root>/<repo_slug>/metrics/snapshots.jsonl`. The actual code puts snapshots at
  `<data_root>/<repo_slug>/metrics/<repo_slug>/snapshots.jsonl` (an extra sub-directory).
  `get_metrics_cache_dir()` in `metrics_manager.py` uses
  `config.state_file.parent / "metrics" / repo_slug`, which adds the repo slug again
  inside the `metrics/` directory. The ADR diagram shows no nested slug here. This is
  a layout drift between doc and implementation.
- **Persistence safety ✅:** Snapshots use `atomic_write`.
- **Docs ⚠️:** The ADR layout drift is a documentation gap. The `metrics_manager.py`
  module docstring says ``.hydraflow/metrics/{repo_slug}/`` which matches code but
  not the ADR.

### `dedup_store.py`

- **Schema quality ✅:** 45 lines, clean. Sorted JSON list, atomic write, graceful
  error handling.
- **Migration tests ✅:** Unit and integration tests cover get/add/set_all and
  error handling. `test_dedup_store.py` exists.
- **Schema-doc fidelity ❌:** `DedupStore` files land at
  `data_root/dedup/*.json` (as wired in `service_registry.py`). The ADR-0021 data
  layout table does not include a `dedup/` directory. It also does not appear in the
  `cache/` directory (the ADR shows `cache/` for ephemeral caches — `dedup/` is not
  ephemeral). This is an undocumented path. With 14+ callers across the codebase,
  `dedup/` is a real part of the data layout that any backup or migration script
  would miss.
- **Persistence safety ✅:** `atomic_write` used throughout.
- **Docs ❌:** Not mentioned in ADR-0021, not mentioned in the wiki. The absence
  means the data layout documented in ADR-0021 is incomplete by at least one
  top-level directory.

### `log_dir` / `plans_dir` / `memory_dir` (flat paths)

- **Schema-doc fidelity ⚠️:** ADR-0021 has an explicit footnote [^1] acknowledging
  these paths are still at `data_root/logs`, `data_root/plans`, `data_root/memory`
  rather than the mandated `data_root/<repo_slug>/logs` etc. ADR-0010 (Worktree and
  Path Isolation Architecture) mandates the repo-scoped layout but the migration
  has not landed. One callsite in `health_monitor_loop.py` (line 461) accesses
  `config.data_root / "logs"` directly instead of `config.log_dir`, bypassing even
  the property.
- **Docs ⚠️:** The ADR footnote is honest about the gap. The migration work item
  (ADR-0010 compliance for log/plans/memory) is not tracked as a GitHub issue.

### `diagnostics_dir` / `visual_reports_dir`

- **Schema-doc fidelity ❌:** `HydraFlowConfig` exposes `diagnostics_dir` returning
  `data_root / "diagnostics"` and `visual_reports_dir` returning
  `data_root / "visual-reports"`. Neither appears in the ADR-0021 data layout tree.
  These are real runtime paths that are created on first use.
- **Docs ❌:** Not mentioned in ADR-0021 or the wiki. Any operator following the ADR
  data layout to plan Docker volume mounts or backup scripts would miss these
  directories.

---

## Findings Summary

### Gaps requiring follow-up issues

**Gap 1 — `dedup/` directory missing from ADR-0021 layout (❌ schema-doc fidelity)**

The `data_root/dedup/` directory holds 14+ dedup sets used by loops across the
system. It is not listed in ADR-0021's data layout tree, not categorized as
`cache/` (it is not ephemeral — it survives across restarts by design), and not
mentioned in the wiki. Any operator following the ADR to set up volume mounts or
backups will miss this directory.

Recommended action: file a `hydraflow-find` issue to update ADR-0021's layout tree
to include `dedup/` with a description of its contents and retention policy.

**Gap 2 — `diagnostics/` and `visual-reports/` missing from ADR-0021 layout (❌ schema-doc fidelity)**

Both `diagnostics_dir` (`data_root/diagnostics/`) and `visual_reports_dir`
(`data_root/visual-reports/`) are live runtime paths not mentioned in ADR-0021.
`diagnostics_dir` holds `factory_metrics.jsonl` — a long-lived operational store.

Recommended action: include these in the same ADR-0021 update as Gap 1.

**Gap 3 — Metrics snapshots path drifts from ADR-0021 layout (⚠️ schema-doc fidelity)**

ADR-0021 shows `<data_root>/<repo_slug>/metrics/snapshots.jsonl`. The code puts
snapshots at `<data_root>/<repo_slug>/metrics/<repo_slug>/snapshots.jsonl` — the
repo slug appears twice. This creates an unexpected extra sub-directory for any
operator reading the ADR.

Recommended action: either update ADR-0021 to reflect the actual nested layout, or
simplify the code to match the ADR (remove the extra slug in `get_metrics_cache_dir`).

**Gap 4 — Forward-compatibility (`extra='ignore'`) not explicitly tested for StateData (⚠️ migration tests)**

Pydantic's default behavior ignores unknown fields, which is the right forward-compat
behavior. But `StateData` has no `model_config = ConfigDict(extra='ignore')` set
explicitly, and no test asserts that a state file with unknown fields loads without
error. If someone adds `model_config = ConfigDict(extra='forbid')` to `StateData`
for stricter validation, it would immediately break all deployments on the next
restart. A single test and an explicit `model_config` declaration would lock in the
behavior.

Recommended action: add `model_config = ConfigDict(extra='ignore')` to `StateData`
and a test: `StateData.model_validate({"processed_issues": {}, "future_field": 42})`
should succeed without error.

**Gap 5 — `StateData` has four weakly-typed `dict[str, Any]` / `dict[str, object]` fields (⚠️ schema quality)**

`rc_budget_duration_history`, `escalation_contexts`, `diagnostic_attempts`, and
`trace_runs` use untyped containers. These cannot be validated by Pydantic on load.
If a bug writes the wrong structure, it will be silently accepted and only surface
as a runtime AttributeError elsewhere.

Recommended action: where the structure is stable, define typed sub-models.
`trace_runs` in particular has a fixed structure (`{"active": {}, "next_run_id": {}}`)
that could be a `TraceRunsState` model.

**Gap 6 — `log_dir`/`plans_dir`/`memory_dir` flat-path migration tracked only in ADR footnote (⚠️ docs)**

ADR-0010 mandates moving these to `data_root/<repo_slug>/logs` etc. ADR-0021 has
an honest footnote but the migration item has no corresponding GitHub issue. One
`health_monitor_loop.py` callsite (line 461) bypasses even the `config.log_dir`
property and hardcodes `config.data_root / "logs"`.

Recommended action: file a GitHub issue to track the ADR-0010 path migration
and fix the hardcoded `health_monitor_loop.py` callsite.

**Gap 7 — `functional_areas.yml` lists `src/session_log.py` which does not exist (minor manifest drift)**

Session logic lives in `src/state/_session.py`, not a top-level `session_log.py`.
This is a cosmetic drift in the area manifest.

Recommended action: update `functional_areas.yml` to reference `src/state/_session.py`
or remove the non-existent module entry.

---

## Strengths

The persistence layer is a standout strength of the codebase:

- **Atomic-write discipline is consistent.** Every mutation path uses `atomic_write`
  or `append_jsonl` (both backed by fsync). No bare `Path.write_text` calls were
  found in the state/event hot paths.
- **Corruption recovery is multi-layered.** StateTracker tries `.bak`, `.bak.1`,
  `.bak.2` before resetting. EventLog skips corrupt lines with logged warnings.
  Session loading does the same. The backup rotation timer (5-minute default) is
  tested.
- **Migration story is ahead of most systems.** Pydantic defaults handle backward
  compat automatically. The `bg_worker_states → worker_heartbeats` migration is the
  only explicit one needed and it is tested. `AliasChoices` handles the
  `active_worktrees → active_worktrees/active_workspaces` rename.
- **Test coverage is deep.** 31 test files, ~8,000 lines total across the
  state/persistence domain. Both unit and integration layers exist. Crash-safety
  properties (fsync failure, file truncation, non-JSON array file) all have tests.
- **File-locking is correct.** `EventLog.rotate` holds the lock across the entire
  read-filter-atomic_write cycle, preventing the append-race that would silently drop
  events written to an unlinked inode during rotation.

---

## Recommended Issues to File

| # | Title | Labels | Priority |
|---|-------|--------|----------|
| 1 | `docs(adr-0021): add dedup/, diagnostics/, visual-reports/ to data layout` | `area-review-gap`, `area:state_persistence`, `docs` | High |
| 2 | `fix(metrics): metrics snapshots path drifts from ADR-0021 layout` | `area-review-gap`, `area:state_persistence`, `bug` | Medium |
| 3 | `fix(models): explicitly set StateData model_config extra=ignore + add forward-compat test` | `area-review-gap`, `area:state_persistence`, `testing` | Medium |
| 4 | `fix(models): type trace_runs and escalation_contexts with typed sub-models` | `area-review-gap`, `area:state_persistence` | Low |
| 5 | `fix(adr-0010): file migration issue for log_dir/plans_dir/memory_dir + hardcoded path in health_monitor_loop.py` | `area-review-gap`, `area:state_persistence`, `tech-debt` | Low |
| 6 | `fix(arch): update functional_areas.yml — session_log.py → state/_session.py` | `area-review-gap`, `area:state_persistence`, `docs` | Low |
